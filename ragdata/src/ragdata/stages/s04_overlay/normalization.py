"""S4: the normalization rules of the text layer (design §2.0), declared and counted.

``text`` may differ from ``text_pdf`` only at errata, so no rule rewrites a
character here: the whitespace rules ran in S2 and are reversible from what the
layers keep (``line_breaks`` offsets, the glyph coordinates of the src layer),
and NFC is verified, never applied (G-TEXT fails on a non-NFC string). The
registry also holds the ASCII allow-list G-TEXT enforces. The overlay report
records each rule with how often it applied to the built rows.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import yaml

from ragdata.stages.s04_overlay.errata import REPO, OverlayError

DEFAULT_PATH = REPO / "config" / "registries" / "normalization.yaml"
SCHEMA = "ragdata.normalization.v1"
RULE_KEYS = ("id", "stage", "what", "applies_to", "reversible_by")
TEXT_TYPES = ("verse_units", "chapter_texts", "headings", "footnotes", "speakers",
              "parallel_refs")
Rows = Mapping[str, Sequence[Mapping[str, Any]]]


def _line_breaks(rows: Rows) -> int:
    return sum(len(u["line_breaks"]) for u in rows.get("verse_units", ()))


def _not_nfc(rows: Rows) -> int:
    """Records with a text field that NFC would change."""
    return sum(1 for name in TEXT_TYPES for row in rows.get(name, ())
               if any(unicodedata.normalize("NFC", row[f]) != row[f]
                      for f in ("text_pdf", "text", "raw") if f in row))


# rule id -> how many times it applied to the built rows (None: counted in the src layer)
COUNTERS: Mapping[str, Callable[[Rows], int] | None] = MappingProxyType({
    "N1": _line_breaks, "N2": None, "N3": _not_nfc,
})


@dataclass(frozen=True)
class Rule:
    id: str
    stage: str
    what: str
    applies_to: tuple[str, ...]
    reversible_by: str


@dataclass(frozen=True)
class Normalization:
    rules: tuple[Rule, ...]
    ascii_allowed: Mapping[str, frozenset[str]]
    why: Mapping[str, str]


def _rule(raw: Mapping[str, Any]) -> Rule:
    missing = [k for k in RULE_KEYS if not raw.get(k)]
    if missing:
        raise OverlayError(f"rule {raw.get('id')!r} lacks {missing}")
    if raw["id"] not in COUNTERS:
        raise OverlayError(f"rule {raw['id']} is not implemented (known: {sorted(COUNTERS)})")
    applies = raw["applies_to"]
    return Rule(raw["id"], str(raw["stage"]), str(raw["what"]),
                tuple(applies) if isinstance(applies, list) else (str(applies),),
                str(raw["reversible_by"]))


def _allowed(raw: Mapping[str, Any]) -> tuple[dict[str, frozenset[str]], dict[str, str]]:
    chars, why = {}, {}
    for type_name, entry in raw.items():
        if type_name not in TEXT_TYPES:
            raise OverlayError(f"ascii_allowed: {type_name} is not a text record type")
        if not isinstance(entry, dict) or not entry.get("why"):
            raise OverlayError(f"ascii_allowed.{type_name}: give chars and why")
        if not str(entry.get("chars", "")).isascii():
            raise OverlayError(f"ascii_allowed.{type_name}: chars must be ASCII")
        chars[type_name], why[type_name] = frozenset(str(entry["chars"])), str(entry["why"])
    return chars, why


def load_normalization(path: Path | str = DEFAULT_PATH) -> Normalization:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OverlayError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise OverlayError(f"{path}: schema must be {SCHEMA}")
    rules = tuple(_rule(raw) for raw in doc.get("rules") or [])
    ids = [r.id for r in rules]
    if len(set(ids)) != len(ids):
        raise OverlayError(f"{path}: a rule is listed twice: {ids}")
    chars, why = _allowed(doc.get("ascii_allowed") or {})
    return Normalization(rules, MappingProxyType(chars), MappingProxyType(why))


def report(norm: Normalization, rows: Rows) -> dict[str, Any]:
    """Each rule with its application count, and the ASCII allow-list, for the overlay report."""
    return {"rules": [{"id": r.id, "stage": r.stage, "what": r.what,
                       "applies_to": list(r.applies_to), "reversible_by": r.reversible_by,
                       "applied": None if COUNTERS[r.id] is None else COUNTERS[r.id](rows)}
                      for r in norm.rules],
            "ascii_allowed": {t: "".join(sorted(c)) for t, c in norm.ascii_allowed.items()}}
