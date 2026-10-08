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
# The files the R1 backend reads: routing words, the event registry (v2) and the
# encoder fingerprint the startup probes are compared with.
REQUIRED = ("routing_lexicon.json", "event_registry.json", "encoder_fingerprint.json")


@dataclass(frozen=True)
class Contracts:
    """What a contract directory holds: the verified files by name, and every mismatch."""

    manifest: Mapping[str, Any] = field(default_factory=dict)
    files: Mapping[str, bytes] = field(default_factory=dict)
    mismatches: tuple[str, ...] = ()

    def json(self, name: str) -> Any:
        return json.loads(self.files[name])


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
