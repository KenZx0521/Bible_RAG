"""Curated entity overrides: config/curated/entity_overrides.yaml (single source).

An override fixes an entity's final type without changing its id. D9 types
group:yehehua (耶和華) Person: Step 10.2 (cleanup_noise_entities --actions
yehehua) relabels the live stores from this file, and the offline Step 6.05
types entities.jsonl rows through final_type() before domain/range, so both
see the graph as 10.2 leaves it. Batch 1D extends the file (D9) and points
H7's allowlist at it.

    version: 1
    overrides:
      <entity_id>: {label: <one of check_identity.TYPE_LABELS>, reason: <why>}

Labels are interpolated into Cypher and SQL by 10.2, so the loader rejects
anything outside TYPE_LABELS, an unknown field and a duplicate id (YAML
itself would keep the last one silently).

PyYAML and the standard library only: 6.05 reads files and connects to no
database.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

try:  # imported as scripts.entity_extraction (6.05, run with -m from the repo root)
    from ..check_identity import TYPE_LABELS
except ImportError:  # imported as entity_extraction (scripts/ on sys.path)
    from check_identity import TYPE_LABELS

OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "config" / "curated" / "entity_overrides.yaml"
FORMAT_VERSION = 1
TOP_LEVEL_KEYS = {"version", "overrides"}
OVERRIDE_FIELDS = {"label", "reason"}


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping key it has already seen."""


def _construct_unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ValueError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                                 _construct_unique_mapping)


def _parse_override(path: Path, entity_id, entry) -> dict[str, str]:
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError(f"{path}: override id {entity_id!r} is not an entity id")
    if not isinstance(entry, Mapping):
        raise ValueError(f"{path}: {entity_id} must map to fields, not {entry!r}")
    unknown = sorted(set(entry) - OVERRIDE_FIELDS)
    if unknown:
        raise ValueError(f"{path}: {entity_id} has unknown field(s) {unknown}; "
                         f"allowed {sorted(OVERRIDE_FIELDS)}")
    label = entry.get("label")
    if label not in TYPE_LABELS:
        raise ValueError(f"{path}: {entity_id} label {label!r} is not one of {list(TYPE_LABELS)}")
    return {"label": label}


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, dict[str, str]]:
    """{entity_id: {'label': str}} from the overrides file; ValueError if malformed."""
    try:
        doc = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader) or {}
    except (ValueError, yaml.YAMLError) as e:
        raise ValueError(f"{path}: {e}") from e
    if not isinstance(doc, Mapping):
        raise ValueError(f"{path}: expected a mapping with {sorted(TOP_LEVEL_KEYS)}")
    unknown = sorted(set(doc) - TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown top-level key(s) {unknown}")
    if doc.get("version") != FORMAT_VERSION:
        raise ValueError(f"{path}: expected version {FORMAT_VERSION}, got {doc.get('version')!r}")
    overrides = doc.get("overrides") or {}
    if not isinstance(overrides, Mapping):
        raise ValueError(f"{path}: overrides must map entity ids to fields")
    return {entity_id: _parse_override(path, entity_id, entry)
            for entity_id, entry in overrides.items()}


def final_type(entity_id: str, extracted_type: str, overrides: Mapping[str, Mapping[str, str]]) -> str:
    """The type an entity ends up with: its override label, else the extracted type."""
    override = overrides.get(entity_id)
    return override["label"] if override else extracted_type
