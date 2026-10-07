"""Content-addressed layer store (design §1.3, §2.0).

A layer lives at ``{root}/{layer}/{layer_version}/`` with its files and a
``layer_manifest.json``. ``layer_version = {layer}@{digest[:12]}`` where
``digest`` is the sha256 of the sorted ``"{file name}\\t{file sha256}\\n"``
lines, so the version depends only on file names and bytes.

Writes go to a temp directory beside the target and are published with one
``rename``; an existing version is never overwritten. Reads verify every file
against the manifest and the version against the digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragcommon import ids
from ragdata.store.jsonl import StoreError, decode_jsonl

DEFAULT_ROOT = Path("/mnt/ollama-data/bible_rag_store/layers")
MANIFEST = "layer_manifest.json"
MANIFEST_SCHEMA = "ragdata.layer_manifest.v1"
_FILE_NAME_RE = re.compile(r"[a-z0-9_]+\.[a-z0-9]+")


class LayerExistsError(StoreError):
    """The target version already exists; versions are immutable."""


class IntegrityError(StoreError):
    """A stored layer does not match its manifest or its version."""


@dataclass(frozen=True)
class StoredLayer:
    layer: str
    version: str
    path: Path


@dataclass(frozen=True)
class LayerData:
    """A verified layer. ``rows`` maps each ``.jsonl`` file to freshly decoded rows."""

    layer: str
    version: str
    path: Path
    depends_on: Mapping[str, str]
    file_shas: Mapping[str, str]
    rows: Mapping[str, tuple[dict[str, Any], ...]]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def layer_digest(file_shas: Mapping[str, str]) -> str:
    lines = "".join(f"{name}\t{file_shas[name]}\n" for name in sorted(file_shas))
    return sha256_bytes(lines.encode("utf-8"))


def _check_layer(layer: str) -> None:
    if layer not in ids.LAYERS:
        raise StoreError(f"unknown layer {layer!r}")


def _check_file_name(name: str) -> None:
    if name == MANIFEST or not isinstance(name, str) or not _FILE_NAME_RE.fullmatch(name):
        raise StoreError(f"illegal layer file name {name!r}")


def _check_depends(depends_on: Mapping[str, str]) -> dict[str, str]:
    for layer, version in depends_on.items():
        _check_layer(layer)
        if not ids.is_valid(version, "layer_version") or ids.parse(version).text != layer:
            raise StoreError(f"depends_on[{layer!r}] is not a {layer} version: {version!r}")
    return dict(sorted(depends_on.items()))


def _manifest_bytes(layer: str, version: str, digest: str, shas: Mapping[str, str],
                    depends_on: Mapping[str, str]) -> bytes:
    manifest = {"schema": MANIFEST_SCHEMA, "layer": layer, "layer_version": version,
                "digest": digest, "files": dict(shas), "depends_on": dict(depends_on)}
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _write_file(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _publish(tmp: Path, target: Path) -> None:
    if target.exists():
        raise LayerExistsError(f"{target} already exists")
    try:
        os.rename(tmp, target)
    except OSError as exc:
        if target.exists():
            raise LayerExistsError(f"{target} already exists") from exc
        raise


def write_layer(root: Path | str, layer: str, files: Mapping[str, bytes],
                depends_on: Mapping[str, str] | None = None) -> StoredLayer:
    """Write a new immutable layer version; raise LayerExistsError if it exists."""
    _check_layer(layer)
    if not files:
        raise StoreError("a layer needs at least one file")
    for name, data in files.items():
        _check_file_name(name)
        if not isinstance(data, bytes):
            raise StoreError(f"{name}: content must be bytes")
    shas = {name: sha256_bytes(files[name]) for name in sorted(files)}
    digest = layer_digest(shas)
    version = ids.layer_version(layer, digest)
    deps = _check_depends(depends_on or {})
    layer_dir = Path(root) / layer
    target = layer_dir / version
    if target.exists():
        raise LayerExistsError(f"{target} already exists")
    layer_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{version}-", dir=layer_dir))
    try:
        for name in shas:
            _write_file(tmp / name, files[name])
        _write_file(tmp / MANIFEST, _manifest_bytes(layer, version, digest, shas, deps))
        _publish(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return StoredLayer(layer, version, target)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{path}: unreadable {MANIFEST}: {exc}") from None
    keys = {"schema", "layer", "layer_version", "digest", "files", "depends_on"}
    if not isinstance(manifest, dict) or set(manifest) != keys \
            or manifest["schema"] != MANIFEST_SCHEMA or not isinstance(manifest["files"], dict):
        raise IntegrityError(f"{path}: malformed {MANIFEST}")
    return manifest


def verify_layer(path: Path | str) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Check files and version against the manifest; return (manifest, file bytes)."""
    path = Path(path)
    manifest = _load_manifest(path)
    listed = manifest["files"]
    present = {p.name for p in path.iterdir()} - {MANIFEST}
    if present != set(listed):
        raise IntegrityError(f"{path}: files {sorted(present ^ set(listed))} disagree with manifest")
    contents = {name: (path / name).read_bytes() for name in sorted(listed)}
    for name, data in contents.items():
        if sha256_bytes(data) != listed[name]:
            raise IntegrityError(f"{path / name}: sha256 differs from manifest")
    digest = layer_digest(listed)
    try:
        version = ids.layer_version(manifest["layer"], digest)
    except ids.IdError as exc:
        raise IntegrityError(f"{path}: {exc}") from None
    if (manifest["digest"], manifest["layer_version"], path.name) != (digest, version, version):
        raise IntegrityError(f"{path}: version does not match its content ({version})")
    return manifest, contents


def read_layer(path: Path | str) -> LayerData:
    path = Path(path)
    manifest, contents = verify_layer(path)
    rows = {name: decode_jsonl(data, name) for name, data in contents.items()
            if name.endswith(".jsonl")}
    return LayerData(
        layer=manifest["layer"], version=manifest["layer_version"], path=path,
        depends_on=MappingProxyType(dict(manifest["depends_on"])),
        file_shas=MappingProxyType(dict(manifest["files"])), rows=MappingProxyType(rows),
    )
