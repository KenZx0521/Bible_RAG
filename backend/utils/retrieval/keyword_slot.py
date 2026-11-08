"""The keyword slot: one passage BM25 finds, appended after everything else.

Dense retrieval reads meaning; a question that repeats a passage's own words (a quoted phrase, a
rare name, a run of names) can still miss it. The slot gives BM25's best passage or chunk that
holds no verse the results already hold one place at the very end, after the top-k, the walk's
place and the event registry's anchor. It never enters the reranker's pool, so the top-k, its order
and the rerank cost stay as they were. The request handler appends it after the cards are made, so
the chronology card's seeds read the same results as without it.

The index is Okapi BM25 (k1 1.2, b 0.75) over the character bigrams of each run of CJK characters,
or of Latin letters and digits (a one-character run is one term), of the text each passage and
chunk record was embedded with (``書名 第N章 標題 (a-b節)：`` and the content). It is built once at
startup from the build's embedding_records; verse records are left out, as a verse hit would stand
for its passage. numpy only.

Measured on the development set (exploratory, store reports/keyword_eval_20261104/, 2026-11-06):
on the 113 complex questions +0.054 coverage over the same pipeline without it (all of it on the 82
written with grep), on 200 of the 500 ordinary ones +0.008 (its CI holds 0); faithfulness showed no
drop, though one batch cannot rule out one of up to about 4 points.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from database import postgres
from utils.retrieval import candidates as cands

logger = logging.getLogger(__name__)

LABEL = "keyword"
# BM25 hits looked at for one that holds no verse of the results
DEPTH = 30
K1, B = 1.2, 0.75
# CJK Extension A, the unified ideographs and the compatibility ideographs (U+F900, not the
# unified 豈 U+8C48 it looks like): written as escapes so no look-alike can slip in
_RUNS = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[A-Za-z0-9]+")
_KINDS = ("passage", "chunk")


def terms(text: str) -> list[str]:
    """The text's terms: the character bigrams of each run, a one-character run as itself."""
    out: list[str] = []
    for run in _RUNS.findall(text):
        out += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return out


@dataclass(frozen=True)
class Hit:
    record_id: str
    kind: str
    score: float


@dataclass(frozen=True)
class Index:
    """BM25 by term: term ``j``'s postings are ``docs[ptr[j]:ptr[j + 1]]``, each with its
    idf-weighted, length-normalised term frequency in ``weights``."""

    ids: tuple[str, ...]
    kinds: tuple[str, ...]
    vocab: Mapping[str, int]
    ptr: np.ndarray
    docs: np.ndarray
    weights: np.ndarray

    def __len__(self) -> int:
        return len(self.ids)

    def top(self, query: str, n: int) -> list[Hit]:
        """The ``n`` records scoring above 0, best first; a tie goes to the earlier record."""
        cols = sorted({j for t in terms(query) if (j := self.vocab.get(t)) is not None})
        if not cols:
            return []
        scores = np.zeros(len(self.ids))
        for j in cols:
            lo, hi = self.ptr[j], self.ptr[j + 1]
            scores[self.docs[lo:hi]] += self.weights[lo:hi]
        hit = np.flatnonzero(scores > 0)
        best = hit[np.lexsort((hit, -scores[hit]))][:n]
        return [Hit(self.ids[i], self.kinds[i], float(scores[i])) for i in best]


def build(records: Iterable[tuple[str, str, str]]) -> Index:
    """The index of ``(record_id, kind, text)`` rows, ties ranked in the order given."""
    ids: list[str] = []
    kinds: list[str] = []
    lengths: list[int] = []
    vocab: dict[str, int] = {}
    cols: list[int] = []
    rows: list[int] = []
    counts: list[int] = []
    for doc, (record_id, kind, text) in enumerate(records):
        if kind not in _KINDS:
            raise ValueError(f"{record_id}: a {kind} record has no place in the keyword index")
        found = terms(text)
        ids.append(record_id)
        kinds.append(kind)
        lengths.append(len(found))
        for term, count in Counter(found).items():
            cols.append(vocab.setdefault(term, len(vocab)))
            rows.append(doc)
            counts.append(count)
    col, row, tf = np.asarray(cols, np.int64), np.asarray(rows, np.int64), np.asarray(counts, float)
    order = np.lexsort((row, col))
    col, row, tf = col[order], row[order], tf[order]
    df = np.bincount(col, minlength=len(vocab))
    ptr = np.concatenate(([0], np.cumsum(df))).astype(np.int64)
    weights = np.zeros(0)
    if len(col):
        dl = np.asarray(lengths, float)
        idf = np.log(1 + (len(ids) - df + 0.5) / (df + 0.5))
        norm = K1 * (1 - B + B * dl / dl.mean())
        weights = idf[col] * tf * (K1 + 1) / (tf + norm[row])
    return Index(tuple(ids), tuple(kinds), vocab, ptr, row, weights)


async def load() -> Index:
    """The served build's index (its passage and chunk records, by record id)."""
    started = time.perf_counter()
    index = build(await postgres.keyword_records())
    logger.info("Keyword index: %d records, %d terms, %.1f s", len(index), len(index.vocab),
                time.perf_counter() - started)
    return index


@dataclass(frozen=True)
class Slot:
    """What the slot did for one request: the candidate it appended (None when every hit it looked
    at holds a verse of the results, BM25 found nothing, or it failed), that hit's 1-based rank
    and score, and the error when it failed."""

    candidate: dict | None = None
    rank: int | None = None
    score: float | None = None
    looked_at: int = 0
    error: str | None = None

    def to_stats(self) -> dict:
        return {"id": self.candidate["id"] if self.candidate else None, "rank": self.rank,
                "score": self.score, "looked_at": self.looked_at}


async def pick(query: str, results: Sequence[dict], index: Index | None) -> Slot:
    """BM25's best passage or chunk among its first ``DEPTH`` that shares no verse with
    ``results``, as a candidate labelled ``keyword`` (weight 0, no rerank or fused score)."""
    if index is None:
        return Slot(error="no keyword index")
    hits = index.top(query, DEPTH)
    if not hits:
        return Slot()
    try:
        sources = await postgres.fetch_sources([h.record_id for h in hits if h.kind == "passage"],
                                               [h.record_id for h in hits if h.kind == "chunk"])
    except Exception as exc:  # noqa: BLE001 — recorded in strategy_errors, the answer goes on
        logger.warning("Keyword slot lookup failed: %s", exc)
        return Slot(looked_at=len(hits), error=repr(exc)[:200])
    for rank, hit in enumerate(hits, 1):
        found = sources[hit.record_id]
        if not any(cands.shares_verse(found, r) for r in results):
            return Slot({**found, "source_strategy": LABEL, "weight": 0.0, "found_by": [LABEL]},
                        rank, hit.score, len(hits))
    return Slot(looked_at=len(hits))


def apply(results: list[dict], stats: Mapping, slot: Slot) -> tuple[list[dict], dict]:
    """``results`` with the slot's candidate last, and ``stats`` saying what the slot did."""
    out = {**stats, "keyword_slot": slot.to_stats()}
    if slot.error:
        out["strategy_errors"] = {**stats.get("strategy_errors", {}), LABEL: slot.error}
    if slot.candidate is None:
        return results, out
    out["strategies_used"] = [*stats.get("strategies_used", []), LABEL]
    return [*results, slot.candidate], out
