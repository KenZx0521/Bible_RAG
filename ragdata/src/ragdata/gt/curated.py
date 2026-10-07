"""Hand decisions for GT v2 (``config/gold/gt_v2_curated.yaml``).

``quote_fixes``  a paraphrased quotation whose original is certain, written back
                 as service text: ``before`` must occur exactly once in the field
                 when the rule-based stages are done; ``after`` must be service text.
``quote_exempt`` text in 「」 that is not a scripture quotation (a term, a title,
                 a summary in quote marks); G-GT skips exactly these.
``kay_review``   questions left unchanged for Kay to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

SCHEMA = "ragdata.gt_v2_curated.v1"
SECTIONS = {
    "quote_fixes": ("qid", "field", "before", "after", "evidence_slot", "reason"),
    "quote_exempt": ("qid", "field", "quote", "reason"),
    "kay_review": ("qid", "issue", "detail"),
}


class CuratedError(ValueError):
    """A curated file that breaks its schema."""


@dataclass(frozen=True)
class QuoteFix:
    qid: str
    field: str
    before: str
    after: str
    evidence_slot: str
    reason: str


@dataclass(frozen=True)
class QuoteExempt:
    qid: str
    field: str
    quote: str
    reason: str


@dataclass(frozen=True)
class KayReview:
    qid: str
    issue: str
    detail: str


@dataclass(frozen=True)
class Curated:
    quote_fixes: tuple[QuoteFix, ...] = ()
    quote_exempt: tuple[QuoteExempt, ...] = ()
    kay_review: tuple[KayReview, ...] = ()


def _rows(doc: Mapping[str, Any], section: str) -> list[dict[str, str]]:
    rows = doc.get(section) or []
    keys = SECTIONS[section]
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != set(keys):
            raise CuratedError(f"{section}[{i}]: keys must be {keys}")
        if not all(isinstance(row[k], str) and row[k] for k in keys):
            raise CuratedError(f"{section}[{i}]: every value must be a non-empty string")
    return rows


def parse_curated(doc: Any) -> Curated:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise CuratedError(f"curated file must declare schema {SCHEMA}")
    unknown = set(doc) - set(SECTIONS) - {"schema"}
    if unknown:
        raise CuratedError(f"unknown sections {sorted(unknown)}")
    return Curated(
        quote_fixes=tuple(QuoteFix(**r) for r in _rows(doc, "quote_fixes")),
        quote_exempt=tuple(QuoteExempt(**r) for r in _rows(doc, "quote_exempt")),
        kay_review=tuple(KayReview(**r) for r in _rows(doc, "kay_review")),
    )


def load_curated(path: Path | str) -> Curated:
    return parse_curated(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
