"""Verse units and name spans written by hand for the kinship tests: a verse is given as its unit
key, its text and its name tokens from left to right (a name is found after the one before it)."""

from __future__ import annotations

from typing import Iterable, Sequence

from ragdata.kg.kin_tokens import Corpus, corpus

Verse = tuple[str, str, Sequence[str]]


def unit_row(unit_key: str, text: str) -> dict:
    book, chapter = unit_key.split(".")[:2]
    return {"unit_key": unit_key, "book_id": book, "chapter": int(chapter), "text": text}


def span_rows(unit_key: str, text: str, names: Iterable[str]) -> list[dict]:
    rows, at = [], 0
    for name in names:
        start = text.index(name, at)
        at = start + len(name)
        rows.append({"container_id": unit_key, "region": "body", "merge_group": None,
                     "start": start, "end": at, "surface": name, "norm_key": name})
    return rows


def make_corpus(*verses: Verse) -> Corpus:
    units = [unit_row(u, t) for u, t, _ in verses]
    spans = [row for u, t, names in verses for row in span_rows(u, t, names)]
    return corpus(units, spans, [])
