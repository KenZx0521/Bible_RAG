"""Attachments: files stored beside a layer version without entering its digest.

The emb layer's vectors are an attachment (design §6): GPU encoding is not bit
for bit reproducible, so the layer version must not depend on them. An
attachment lives at ``{layer dir}.{name}/`` with its files and
``attachment_manifest.json`` (file sha256s, the layer version it belongs to and
free-form ``meta``). Like a layer it is published by one ``rename`` and never
overwritten; reads verify every file against the manifest.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragdata.store.cas import (
    IntegrityError, LayerExistsError, StoredLayer, _FILE_NAME_RE, _write_file, sha256_bytes,
)
from ragdata.store.jsonl import StoreError

MANIFEST = "attachment_manifest.json"
SCHEMA = "ragdata.attachment.v1"
_NAME_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Attachment:
    layer_version: str
    name: str
    path: Path
    meta: Mapping[str, Any]
    file_shas: Mapping[str, str]


def attachment_dir(layer_path: Path | str, name: str) -> Path:
    layer_path = Path(layer_path)
    return layer_path.parent / f"{layer_path.name}.{name}"


def _check(name: str, files: Mapping[str, bytes]) -> None:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise StoreError(f"illegal attachment name {name!r}")
    if not files:
        raise StoreError("an attachment needs at least one file")
    for file_name, data in files.items():
        if file_name == MANIFEST or not _FILE_NAME_RE.fullmatch(file_name):
            raise StoreError(f"illegal attachment file name {file_name!r}")
        if not isinstance(data, bytes):
            raise StoreError(f"{file_name}: content must be bytes")


def _manifest_bytes(layer_version: str, name: str, shas: Mapping[str, str],
                    meta: Mapping[str, Any]) -> bytes:
    doc = {"schema": SCHEMA, "layer_version": layer_version, "name": name,
           "files": dict(shas), "meta": dict(meta)}
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write_attachment(layer: StoredLayer, name: str, files: Mapping[str, bytes],
                     meta: Mapping[str, Any], exist_ok: bool = False) -> Attachment:
    """Publish ``files`` beside ``layer``; with ``exist_ok`` an existing attachment is
    verified and returned instead (never rewritten)."""
    _check(name, files)
    if not Path(layer.path).is_dir():
        raise StoreError(f"{layer.path}: no such layer version to attach to")
    target = attachment_dir(layer.path, name)
    if target.exists():
        if exist_ok:
            return read_attachment(layer.path, name)[0]
        raise LayerExistsError(f"{target} already exists")
    shas = {f: sha256_bytes(files[f]) for f in sorted(files)}
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{target.name}-", dir=target.parent))
    try:
        for file_name in shas:
            _write_file(tmp / file_name, files[file_name])
        _write_file(tmp / MANIFEST, _manifest_bytes(layer.version, name, shas, meta))
        os.chmod(tmp, 0o755)
        if target.exists():
            raise LayerExistsError(f"{target} already exists")
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return Attachment(layer.version, name, target, MappingProxyType(dict(meta)),
                      MappingProxyType(shas))


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"{path}: unreadable {MANIFEST}: {exc}") from None
    if not isinstance(doc, dict) or set(doc) != {"schema", "layer_version", "name", "files",
                                                 "meta"} or doc["schema"] != SCHEMA:
        raise IntegrityError(f"{path}: malformed {MANIFEST}")
    return doc


def read_attachment(layer_path: Path | str, name: str) -> tuple[Attachment, dict[str, bytes]]:
    """The attachment ``name`` of the layer at ``layer_path`` and its verified file bytes."""
    layer_path = Path(layer_path)
    path = attachment_dir(layer_path, name)
    if not path.is_dir():
        raise StoreError(f"{layer_path}: no {name} attachment at {path}")
    doc = _load_manifest(path)
    if (doc["layer_version"], doc["name"]) != (layer_path.name, name):
        raise IntegrityError(f"{path}: belongs to {doc['layer_version']}/{doc['name']}")
    listed = doc["files"]
    present = {p.name for p in path.iterdir()} - {MANIFEST}
    if present != set(listed):
        raise IntegrityError(f"{path}: files {sorted(present ^ set(listed))} disagree "
                             "with its manifest")
    contents = {f: (path / f).read_bytes() for f in sorted(listed)}
    for file_name, data in contents.items():
        if sha256_bytes(data) != listed[file_name]:
            raise IntegrityError(f"{path / file_name}: sha256 differs from its manifest")
    found = Attachment(doc["layer_version"], name, path, MappingProxyType(doc["meta"]),
                       MappingProxyType(dict(listed)))
    return found, contents
