"""Load biblical_relations.yaml and provide candidate-set lookups.

The schema is the closed candidate pool for both rule and LLM classifiers,
ensuring nothing outside the ontology can be emitted.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .models import RelationSchemaEntry

logger = logging.getLogger(__name__)


class RelationSchema:
    def __init__(self, entries: dict[str, RelationSchemaEntry]):
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "RelationSchema":
        try:
            import yaml
        except ImportError as e:
            raise RuntimeError(
                "PyYAML is required to load relation schema. "
                "Install with `uv pip install pyyaml` or update scripts/pyproject.toml."
            ) from e

        if not path.exists():
            raise FileNotFoundError(f"Relation schema not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        relations_blob = data.get("relations", {})
        if not isinstance(relations_blob, dict):
            raise ValueError(f"Schema 'relations' must be a mapping in {path}")

        entries: dict[str, RelationSchemaEntry] = {}
        for name, body in relations_blob.items():
            if not isinstance(body, dict):
                logger.warning("Skipping malformed relation entry: %s", name)
                continue
            entries[name] = RelationSchemaEntry(
                name=name,
                domain_types=list(body.get("domain_types") or []),
                range_types=list(body.get("range_types") or []),
                direction=str(body.get("direction") or "directed"),
                inverse=body.get("inverse"),
                description_zh=str(body.get("description_zh") or ""),
                prompt_signals=list(body.get("prompt_signals") or []),
                examples=list(body.get("examples") or []),
                confidence_priors=dict(body.get("confidence_priors") or {}),
            )

        logger.info("Loaded %d relations from %s", len(entries), path)
        return cls(entries)

    def all_names(self) -> list[str]:
        return list(self._entries.keys())

    def get(self, name: str) -> RelationSchemaEntry | None:
        return self._entries.get(name)

    def candidates_for(self, head_type: str, tail_type: str) -> list[RelationSchemaEntry]:
        """Return the schema subset legal for this (head_type, tail_type)."""
        return [
            entry for entry in self._entries.values()
            if entry.accepts_pair(head_type, tail_type)
        ]

    def inverse_of(self, name: str) -> str | None:
        entry = self._entries.get(name)
        return entry.inverse if entry else None

    def iter_entries(self) -> Iterable[RelationSchemaEntry]:
        return self._entries.values()

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)
