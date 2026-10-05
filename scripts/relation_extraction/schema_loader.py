"""Load biblical_relations.yaml and provide candidate-set lookups.

The schema is the closed candidate pool for the R4 LLM classifier, ensuring
nothing outside the ontology can be emitted; 6.05 checks domain/range against it.

Its `direction_pairs` table names the directed relations whose reading
direction is carried by the relation name (FATHER_OF vs SON_OF). The 6.05
direction flag and validate_kg H11 read it through id_order_relations(); it is
independent of `inverse`, which only R5 materialisation reads.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Sequence

from .models import RelationSchemaEntry

logger = logging.getLogger(__name__)


class RelationSchema:
    def __init__(self, entries: dict[str, RelationSchemaEntry], version: str | None = None,
                 direction_pairs: Sequence[Sequence[str]] = ()):
        self._entries = entries
        self.version = version   # the yaml's top-level version; 6.05 stamps it on every row
        self.direction_pairs = _checked_pairs(entries, direction_pairs)

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
                examples=list(body.get("examples") or []),
                confidence_priors=dict(body.get("confidence_priors") or {}),
            )

        logger.info("Loaded %d relations from %s", len(entries), path)
        version = data.get("version")
        return cls(entries, version=None if version is None else str(version),
                    direction_pairs=data.get("direction_pairs") or ())

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

    def is_direction_paired(self, name: str) -> bool:
        return any(name in pair for pair in self.direction_pairs)

    def id_order_relations(self) -> frozenset[str]:
        """Directed relations with one type at both ends and no direction pair.

        Nothing but head/tail order tells which way such a row reads, and an
        llm row has its ends in id order, so 6.05 marks it direction-unverified.
        """
        return frozenset(
            e.name for e in self._entries.values()
            if e.direction == "directed"
            and set(e.domain_types) == set(e.range_types)
            and not self.is_direction_paired(e.name)
        )

    def inverse_of(self, name: str) -> str | None:
        entry = self._entries.get(name)
        return entry.inverse if entry else None

    def iter_entries(self) -> Iterable[RelationSchemaEntry]:
        return self._entries.values()

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)


def _checked_pairs(entries: dict[str, RelationSchemaEntry],
                   pairs: object) -> tuple[tuple[str, str], ...]:
    """direction_pairs as tuples, in file order; ValueError on a malformed table.

    Each pair is two distinct directed relations of the schema whose domain and
    range mirror each other: A(x, y) and B(y, x) read one tie from either end.
    """
    if not isinstance(pairs, (list, tuple)):
        raise ValueError(f"direction_pairs must be a list of [A, B] pairs, got {pairs!r}")
    checked = []
    for pair in pairs:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                and all(isinstance(name, str) for name in pair) and pair[0] != pair[1]):
            raise ValueError(f"direction_pairs: {pair!r} is not two distinct relation names")
        a, b = (entries.get(name) for name in pair)
        if a is None or b is None:
            raise ValueError(f"direction_pairs: {pair!r} names a relation not in the schema")
        if a.direction != "directed" or b.direction != "directed":
            raise ValueError(f"direction_pairs: {pair!r} has an undirected member")
        if set(a.domain_types) != set(b.range_types) or set(a.range_types) != set(b.domain_types):
            raise ValueError(f"direction_pairs: {pair!r} domain/range do not mirror")
        checked.append((a.name, b.name))
    return tuple(checked)
