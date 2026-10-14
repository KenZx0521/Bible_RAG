"""Lexical side of the §3 arms (private part of arms.py): G name linking and the L / LEXPRF BM25.

Import through arms.py. prereg.md §3 is the spec:

* G name linking (the 4 steps of the G row): mask book names, build surf_table from kg0
  names.jsonl then query_aliases.json, match longest first without overlap, keep the keys
  by start position.
* L / LEXPRF: BM25 over adjacent-character bigrams inside maximal [一-鿿]+ runs of the
  passage content (verse markers **n** blanked), k1 = 1.2, b = 0.75,
  idf = ln(1 + (N - df + 0.5) / (df + 0.5)); LEXPRF's query weights are q(t).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import gd_common as gd

BM25_K1, BM25_B = 1.2, 0.75
LEXPRF_TERMS = 40           # feedback terms kept by (-fb, term)
LEXPRF_MIX = 0.5            # q(t) = 0.5 question part + 0.5 feedback part
MIN_SURFACE = 2             # kg0 surfaces / norm_keys shorter than this are not linked
MASK = "□"

_CJK_RUN = re.compile(r"[一-鿿]+")
_VERSE_NO = re.compile(r"\*\*\d+[a-z]?(?:-\d+[a-z]?)?\*\*")

__all__ = ["BM25_K1", "BM25_B", "LEXPRF_TERMS", "LEXPRF_MIX", "MIN_SURFACE", "MASK",
           "book_masks", "surf_table", "NameLinker", "build_linker", "bigrams", "passage_bigrams",
           "Bm25Index", "build_bm25", "lexprf_query", "by_score"]


# ------------------------------------------------------------------ G name linking

def book_masks(book_names: Sequence[str]) -> tuple[str, ...]:
    """Book names plus the '上/下'-less form of those longer than 3, by (-length, string)."""
    stems = {n[:-1] for n in book_names if n[-1] in "上下" and len(n) > 3}
    return tuple(sorted(set(book_names) | stems, key=lambda s: (-len(s), s)))


def surf_table(kg0_names: Sequence[gd.Kg0Name],
               aliases: Sequence[tuple[str, str]]) -> dict[str, str]:
    """surface -> norm_key in insertion order: each kg0 row's surfaces then its norm_key (length
    >= 2), then the query aliases via setdefault. A surface claimed by two kg0 keys raises."""
    table: dict[str, str] = {}
    for name in kg0_names:
        for surface in (*name.surfaces, name.norm_key):
            if len(surface) < MIN_SURFACE:
                continue
            if table.setdefault(surface, name.norm_key) != name.norm_key:
                raise gd.IntegrityError(
                    f"surface {surface!r} names both {table[surface]} and {name.norm_key}")
    for surface, target in aliases:
        table.setdefault(surface, target)
    return table


@dataclass(frozen=True)
class NameLinker:
    masks: tuple[str, ...]
    surfaces: tuple[tuple[str, str], ...]   # (surface, norm_key): length desc, then table order

    def link(self, text: str) -> tuple[str, ...]:
        """Longest-first, non-overlapping surfaces of the book-masked text; keys by start, unique."""
        for book in self.masks:
            text = text.replace(book, MASK * len(book))
        taken = [False] * len(text)
        found = []
        for surface, key in self.surfaces:
            start = text.find(surface)
            while start != -1:
                end = start + len(surface)
                if not any(taken[start:end]):
                    taken[start:end] = [True] * len(surface)
                    found.append((start, surface, key))
                start = text.find(surface, start + 1)
        return tuple(dict.fromkeys(key for _, _, key in sorted(found)))


def build_linker(book_names: Sequence[str], kg0_names: Sequence[gd.Kg0Name],
                 aliases: Sequence[tuple[str, str]]) -> NameLinker:
    table = surf_table(kg0_names, aliases)
    order = sorted(table, key=len, reverse=True)       # stable: equal length keeps table order
    return NameLinker(book_masks(book_names), tuple((s, table[s]) for s in order))


# ------------------------------------------------------------------ BM25 (L, LEXPRF)

def bigrams(text: str) -> list[str]:
    """Adjacent-character bigrams inside each maximal [一-鿿]+ run, in text order."""
    return [run[i:i + 2] for run in _CJK_RUN.findall(text) for i in range(len(run) - 1)]


def passage_bigrams(content: str) -> list[str]:
    """Bigrams of passage content with its **n** verse markers blanked."""
    return bigrams(_VERSE_NO.sub(" ", content))


@dataclass(frozen=True)
class Bm25Index:
    pids: tuple[str, ...]                                   # passages.jsonl row order
    tf: tuple[Mapping[str, int], ...]                       # per passage, first-occurrence order
    length: tuple[int, ...]                                 # bigram count per passage
    avgdl: float
    idf: Mapping[str, float]
    postings: Mapping[str, tuple[tuple[int, int], ...]]     # term -> ((passage index, tf), ...)
    index_of: Mapping[str, int]                             # passage_id -> index

    def scores(self, weights: Mapping[str, float]) -> dict[int, float]:
        """BM25 of every passage holding a weighted term, summed in `weights` order."""
        out: dict[int, float] = {}
        k1, b, avgdl = BM25_K1, BM25_B, self.avgdl
        for term, w in weights.items():
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, f in self.postings[term]:
                norm = f + k1 * (1 - b + b * self.length[i] / avgdl)
                out[i] = out.get(i, 0.0) + w * idf * f * (k1 + 1) / norm
        return out


def build_bm25(pids: Sequence[str], contents: Sequence[str]) -> Bm25Index:
    if len(pids) != len(contents) or not pids:
        raise gd.GdError(f"BM25 needs one content per passage ({len(pids)} ids, {len(contents)} texts)")
    tfs = [dict(Counter(passage_bigrams(c))) for c in contents]
    lengths = tuple(sum(tf.values()) for tf in tfs)
    df: Counter = Counter()
    postings: dict[str, list[tuple[int, int]]] = {}
    for i, tf in enumerate(tfs):
        df.update(tf.keys())
        for term, f in tf.items():
            postings.setdefault(term, []).append((i, f))
    n = len(pids)
    idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    return Bm25Index(tuple(pids), tuple(MappingProxyType(tf) for tf in tfs), lengths,
                     sum(lengths) / n, MappingProxyType(idf),
                     MappingProxyType({t: tuple(v) for t, v in postings.items()}),
                     MappingProxyType({p: i for i, p in enumerate(pids)}))


def lexprf_query(index: Bm25Index, question: str, seeds: Sequence[int]) -> dict[str, float]:
    """q(t) = 0.5*tf_q/sum tf_q + 0.5*fb/sum fb, fb(t) = sum_seeds w*tf/len*idf with w = 1/rank
    (not normalised), keeping the top 40 fb terms by (-fb, term). Question terms come first."""
    fb: dict[str, float] = {}
    for rank, i in enumerate(seeds):
        w, size = 1.0 / (rank + 1), index.length[i] or 1
        for term, f in index.tf[i].items():
            fb[term] = fb.get(term, 0.0) + w * (f / size) * index.idf[term]
    top = sorted(fb.items(), key=lambda kv: (-kv[1], kv[0]))[:LEXPRF_TERMS]
    z_fb = sum(v for _, v in top) or 1
    q_tf = Counter(bigrams(question))
    z_q = sum(q_tf.values()) or 1
    weights: dict[str, float] = {}
    for term, f in q_tf.items():
        weights[term] = weights.get(term, 0.0) + LEXPRF_MIX * f / z_q
    for term, v in top:
        weights[term] = weights.get(term, 0.0) + (1 - LEXPRF_MIX) * v / z_fb
    return weights


def by_score(index: Bm25Index, scores: Mapping[int, float], idx: Iterable[int]) -> list[str]:
    """Passages `idx` by (-score, pid); a passage without a score counts as 0."""
    return [index.pids[i] for i in sorted(idx, key=lambda i: (-scores.get(i, 0.0), index.pids[i]))]
