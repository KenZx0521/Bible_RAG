"""S12: assemble a release (design §2.22, §4) from layer versions in the store.

A release names one version of every core layer (text, struct, emb, kg0, events,
route) and of every layer they were built on (src under text). The versions given
need not be all of them: the rest follow from each layer's ``depends_on``, and the
closure must agree, by content hash, everywhere: a layer built on another version
of a layer the release names is refused. Every layer is read through the store,
so each of its files is checked against its manifest and its version against the
digest.

The release document pins the versions and full digests, the declared
dependencies, the record counts, the encoder fingerprint and the sha256 of every
contract file (``release.contracts``). Its ``release_sha`` is the sha256 of that
body (canonical JSON), and ``build_id = b{date}_{release_sha[:8]}``; the date is
an argument (``git_date`` gives the commit date), never the clock, so assembling
the same layers again gives the same bytes. ``backend_image_digest`` is not
part of a release: the image is paired with the build when it is promoted
(``rag_meta.serving``), so the data alone names the build.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.contract.registry import EMB_REPORT, ENCODER_FINGERPRINT, record_type_for_file
from ragdata.release.contracts import ContractFileError, contract_files, encode
from ragdata.store import LayerData, StoreError, layer_digest, read_layer
from ragdata.store.cas import sha256_bytes

__all__ = ["CORE", "NAMING", "Release", "ReleaseError", "assemble", "encode", "git_date",
           "read_release", "resolve_layers", "sha256_bytes", "write_release"]

RELEASE_SCHEMA = "ragdata.release.v1"
CONTRACT_VERSION = "1.1.0"
CORE = ("text", "struct", "emb", "kg0", "events", "route")
NAMING = ("build_id", "build_date", "release_sha")    # what the body's sha names


class ReleaseError(ValueError):
    """The layers do not make a release, or a release file does not match the store."""


@dataclass(frozen=True)
class Release:
    build_id: str
    release_sha: str
    doc: Mapping[str, Any]
    data: bytes                         # releases/{build_id}.json
    layers: Mapping[str, LayerData]     # verified, by layer
    contracts: Mapping[str, bytes]      # contract files but manifest.json


def _layer_of(version: str) -> str:
    if not isinstance(version, str) or not ids.is_valid(version, "layer_version"):
        raise ReleaseError(f"{version!r} is not a layer version")
    return ids.parse(version).text


def _load(store_root: Path, version: str) -> LayerData:
    path = Path(store_root) / _layer_of(version) / version
    if not path.is_dir():
        raise ReleaseError(f"no layer {version} in {store_root}")
    try:
        return read_layer(path)
    except StoreError as exc:
        raise ReleaseError(f"{version}: {exc}") from None


def _chosen(versions: Sequence[str]) -> dict[str, str]:
    chosen: dict[str, str] = {}
    for version in versions:
        layer = _layer_of(version)
        if chosen.setdefault(layer, version) != version:
            raise ReleaseError(f"layer {layer} is named twice ({chosen[layer]}, {version})")
    return chosen


def resolve_layers(store_root: Path, versions: Sequence[str]) -> dict[str, LayerData]:
    """The named layers and their dependency closure, each verified; refuse disagreement."""
    chosen = _chosen(versions)
    loaded: dict[str, LayerData] = {}
    pending = list(chosen.values())
    while pending:
        data = _load(store_root, pending.pop())
        loaded[data.layer] = data
        for dep, version in sorted(data.depends_on.items()):
            if chosen.setdefault(dep, version) != version:
                raise ReleaseError(f"{data.version} was built on {version}, but the release "
                                   f"has {dep} {chosen[dep]}")
            if dep not in loaded and version not in pending:
                pending.append(version)
    missing = [layer for layer in CORE if layer not in loaded]
    extra = sorted(set(loaded) - {*CORE, "src"})
    if missing or extra:
        raise ReleaseError(f"a release holds the layers {list(CORE)} (and src under text); "
                           f"missing {missing}, not supported {extra}")
    return loaded


def _check_date(date: str) -> None:
    try:
        ok = isinstance(date, str) and len(date) == 8 and bool(dt.datetime.strptime(date, "%Y%m%d"))
    except ValueError:
        ok = False
    if not ok:
        raise ReleaseError(f"the build date must be YYYYMMDD, got {date!r}")


def _json_file(layer: LayerData, name: str) -> Any:
    try:
        return json.loads((layer.path / name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{layer.version}: cannot read {name}: {exc}") from None


def _counts(layers: Mapping[str, LayerData]) -> dict[str, int]:
    """Rows of every record file (src's extracts are not records)."""
    return {record_type_for_file(name).name: len(rows) for layer in layers.values()
            for name, rows in layer.rows.items() if record_type_for_file(name) is not None}


def _body(layers: Mapping[str, LayerData], contracts: Mapping[str, bytes]) -> dict[str, Any]:
    emb = layers["emb"]
    template = _json_file(emb, EMB_REPORT).get("template", {}).get("template_id")
    if not template:
        raise ReleaseError(f"{emb.version}: {EMB_REPORT} declares no template_id")
    return {
        "schema": RELEASE_SCHEMA, "contract_version": CONTRACT_VERSION, "template_id": template,
        "layers": {layer: (layers[layer].version if layer in layers else None)
                   for layer in ids.LAYERS},
        "layer_digests": {k: layer_digest(v.file_shas) for k, v in sorted(layers.items())},
        "depends_on": {k: dict(sorted(v.depends_on.items())) for k, v in sorted(layers.items())},
        "kg_enabled": False,
        "encoder_fingerprint_sha": emb.file_shas[ENCODER_FINGERPRINT],
        "contracts": {name: sha256_bytes(data) for name, data in sorted(contracts.items())},
        "counts": dict(sorted(_counts(layers).items())),
    }


def assemble(store_root: Path, versions: Sequence[str], date: str) -> Release:
    """The release of ``versions`` (and their closure) built on ``date`` (YYYYMMDD)."""
    _check_date(date)
    layers = resolve_layers(Path(store_root), versions)
    try:
        contracts = contract_files(layers)
    except ContractFileError as exc:
        raise ReleaseError(str(exc)) from None
    body = _body(layers, contracts)
    release_sha = sha256_bytes(encode(body))
    build_id = ids.build_id(date, release_sha)
    doc = {**body, "build_id": build_id, "build_date": date, "release_sha": release_sha}
    data = (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    return Release(build_id, release_sha, MappingProxyType(doc), data,
                   MappingProxyType(layers), MappingProxyType(contracts))


def write_release(release: Release, directory: Path) -> Path:
    """Write ``{build_id}.json`` once; the same bytes again is a no-op, other bytes an error."""
    directory = Path(directory)
    path = directory / f"{release.build_id}.json"
    if path.exists():
        if path.read_bytes() != release.data:
            raise ReleaseError(f"{path} exists and differs from this release")
        return path
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{release.build_id}-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(release.data)
        os.chmod(tmp, 0o444)
        os.rename(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def read_release(path: Path, store_root: Path) -> Release:
    """The release in ``path``, verified by assembling it again from the store."""
    try:
        data = Path(path).read_bytes()
        doc = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReleaseError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != RELEASE_SCHEMA \
            or not isinstance(doc.get("layers"), dict):
        raise ReleaseError(f"{path}: not a release ({RELEASE_SCHEMA})")
    versions = [v for v in doc["layers"].values() if v]
    again = assemble(store_root, versions, doc.get("build_date"))
    if again.data != data:
        raise ReleaseError(f"{path} does not match the release assembled from the store "
                           f"({again.build_id})")
    return again


def git_date(repo: Path) -> str:
    """The commit date (UTC, YYYYMMDD) of ``repo``'s HEAD: a release date that is not now."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%ct", "HEAD"],
                             check=True, capture_output=True, text=True).stdout
        stamp = int(out.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise ReleaseError(f"git cannot date HEAD of {repo}: {exc}") from None
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).strftime("%Y%m%d")
