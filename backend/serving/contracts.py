"""A build's contract directory (design §7.5): ``contracts/{build_id}/`` with its manifest.

The loader writes the directory once and the backend mounts it read-only. Its
``manifest.json`` names the build and the sha256 of every contract file; a file is
handed out only when its bytes hash to the manifest, so nothing the backend reads
from here can differ from what the release pinned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

MANIFEST = "manifest.json"
# The files the R2 backend reads: routing words (lexicon v2), the query-alias table
# (validated only; its presence also tells an R2 build from an R1 build), the event
# registry (variant R2) and the encoder fingerprint the startup probes are compared with.
REQUIRED = ("routing_lexicon.json", "query_aliases.json", "event_registry.json",
            "encoder_fingerprint.json")
KG_META = "kg_meta.json"                # only a KG build's manifest lists it (handshake.check_kg)
KG_SCHEMA = "ragdata.kg.v1"


@dataclass(frozen=True)
class Contracts:
    """What a contract directory holds: the verified files by name, and every mismatch."""

    manifest: Mapping[str, Any] = field(default_factory=dict)
    files: Mapping[str, bytes] = field(default_factory=dict)
    mismatches: tuple[str, ...] = ()

    def json(self, name: str) -> Any:
        return json.loads(self.files[name])


@dataclass(frozen=True)
class KgMeta:
    """``kg_meta.json``: what the build's graph holds. ``sha256`` is the file's, which the projection
    in Neo4j names as ``kg_sha256``."""

    schema_version: str
    nodes: Mapping[str, int]
    edges: Mapping[str, int]
    nodes_sha256: str
    edges_sha256: str
    sha256: str


def _kg_counts(counts: Any, key: str) -> Mapping[str, int]:
    found = counts.get(key) if isinstance(counts, dict) else None
    if not isinstance(found, dict) or any(type(n) is not int for n in found.values()):
        raise ValueError(f"{KG_META}: counts.{key} is not a table of counts")
    return MappingProxyType(found)


def _kg_sha(doc: Mapping[str, Any], key: str) -> str:
    found = doc.get(key)
    if not (isinstance(found, str) and len(found) == 64):
        raise ValueError(f"{KG_META}: {key} is not a sha256")
    return found


def parse_kg_meta(data: bytes) -> KgMeta:
    """Raises ``ValueError`` for anything but the graph layer's meta document."""
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise ValueError(f"{KG_META} is not JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError(f"{KG_META} is not an object")
    if doc.get("schema_version") != KG_SCHEMA:
        raise ValueError(f"{KG_META}: schema_version must be {KG_SCHEMA}, got {doc.get('schema_version')!r}")
    return KgMeta(KG_SCHEMA, _kg_counts(doc.get("counts"), "nodes"), _kg_counts(doc.get("counts"), "edges"),
                  _kg_sha(doc, "nodes_sha256"), _kg_sha(doc, "edges_sha256"),
                  hashlib.sha256(data).hexdigest())


def resolve_dir(contracts_dir: str, contracts_root: str | None) -> Path:
    """``contracts_dir`` of rag_meta.builds, re-rooted under the mount when one is set."""
    path = Path(contracts_dir)
    return Path(contracts_root) / path.name if contracts_root else path


def _manifest(directory: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = directory / MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"contracts: {path} unreadable: {exc}"
    if not isinstance(doc, dict) or not isinstance(doc.get("files"), dict):
        return None, f"contracts: {path} has no files table"
    return doc, None


def _checked_file(directory: Path, name: str, expected: str) -> tuple[bytes | None, str | None]:
    try:
        data = (directory / name).read_bytes()
    except OSError as exc:
        return None, f"contracts: {name} unreadable: {exc}"
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        return None, f"contracts: {name} sha256 {actual[:12]} != manifest {str(expected)[:12]}"
    return data, None


def verify(directory: Path, build_id: str) -> Contracts:
    """Read ``directory``; every problem becomes a mismatch, nothing is raised."""
    doc, problem = _manifest(Path(directory))
    if doc is None:
        return Contracts(mismatches=(problem,))
    problems = []
    if doc.get("build_id") != build_id:
        problems.append(f"contracts: manifest names build {doc.get('build_id')!r}, not {build_id}")
    problems += [f"contracts: manifest does not list {name}"
                 for name in REQUIRED if name not in doc["files"]]
    files = {}
    for name, sha in sorted(doc["files"].items()):
        data, problem = _checked_file(Path(directory), name, sha)
        if problem:
            problems.append(problem)
        else:
            files[name] = data
    return Contracts(MappingProxyType(doc), MappingProxyType(files), tuple(problems))
