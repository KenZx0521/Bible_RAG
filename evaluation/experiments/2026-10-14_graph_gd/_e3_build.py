"""§8 E3 raw_responses.json of one arm at one k (private part of e3_raw.py).

One raw item per GT v2 question, in GT order, in the collector's raw format
(evaluation/src/collector.py) that quick_retrieval_eval.py --from-raw reads back
(samples_from_raw): exactly k passage sources, the arm's §3 top-k
sorted(pool, key=(−score, pid))[:k]. A source carries the fields the backend's /query
returns for a passage (backend routers/query.py _source, database/postgres.py _passage):
id, book (the Chinese book name), chapter, title, verse_range, score (the reranker score),
strategy, kind "passage", start_key and end_key, read from the pinned struct and text
layers. route_used is "OFFLINE" and strategy "OFFLINE_<arm>". run_meta.json beside it
is what /health reports for the build (src/provenance.py read_run_meta): data_build_id
b20261008_e05d3e55 and the encoder fingerprint of the §10 pins (embedder, reranker).
check_raw() is the one validator of that shape, for built and synthetic raw files alike.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import gd_common as gd
from _gd_store import _layer_bytes

__all__ = ["RAW_NAME", "RUN_META_NAME", "BUILD_NAME", "ROUTE", "KIND", "E3_ARMS", "SOURCE_KEYS",
           "SourceRow", "load_source_rows", "strategy_of", "passage_source", "raw_item",
           "top_k", "arm_items", "run_meta_doc", "check_run_meta", "check_raw", "read_raw",
           "write_json", "write_raw_dir", "sha256_bytes"]

RAW_NAME = "raw_responses.json"
RUN_META_NAME = "run_meta.json"             # src/provenance.py RUN_META
BUILD_NAME = "e3_build.json"                # §10 meta of the build step (lists, scores, arm, k)
ROUTE = "OFFLINE"                           # §8: route_used of every offline raw item
KIND = "passage"
E3_ARMS = ("C", "GD")                       # §8: E3 runs C and GD only
SOURCE_KEYS = ("id", "book", "chapter", "title", "verse_range", "score", "strategy", "kind",
               "start_key", "end_key")      # the SourceInfo fields the collector keeps


@dataclass(frozen=True)
class SourceRow:
    pid: str
    book: str               # text layer books.jsonl name (the PG books.name the backend returns)
    chapter: int
    title: str
    verse_range: str
    start_key: str
    end_key: str


def _jsonl(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


@functools.cache
def load_source_rows(root: Path = gd.LAYERS_ROOT) -> Mapping[str, SourceRow]:
    """pid -> SourceRow of every passage of the pinned struct layer, book name from text."""
    books = {b["book_id"]: b["name"] for b in _jsonl(_layer_bytes(root, "text", "books.jsonl"))}
    gd.expect("text books", len(books), gd.N_BOOKS)
    rows: dict[str, SourceRow] = {}
    for p in _jsonl(_layer_bytes(root, "struct", "passages.jsonl")):
        book_id, _, chapter = p["chapter_key"].rpartition(".")
        if book_id not in books or not p["start_key"].startswith(p["chapter_key"] + "."):
            raise gd.IntegrityError(f"{p['passage_id']}: chapter_key {p['chapter_key']!r} does "
                                    f"not name a book and hold start_key {p['start_key']!r}")
        rows[p["passage_id"]] = SourceRow(p["passage_id"], books[book_id], int(chapter),
                                          p.get("title") or "", p["verse_range"] or "",
                                          p["start_key"], p["end_key"])
    gd.expect("struct passages", len(rows), gd.N_PASSAGES)
    return MappingProxyType(rows)


def strategy_of(arm: str) -> str:
    return f"{ROUTE}_{arm}"


def passage_source(row: SourceRow, score: float | None, arm: str) -> dict[str, Any]:
    """One /query passage source (SOURCE_KEYS order)."""
    return {"id": row.pid, "book": row.book, "chapter": row.chapter, "title": row.title,
            "verse_range": row.verse_range, "score": score, "strategy": strategy_of(arm),
            "kind": KIND, "start_key": row.start_key, "end_key": row.end_key}


def raw_item(qid: str, question: str, sources: Sequence[Mapping[str, Any]], arm: str) -> dict:
    """One collector raw item (src/collector.py collected_raw) without an answer."""
    return {"question_id": qid, "question": question, "rag_answer": "", "contexts": [],
            "context_source": "", "sources": [dict(s) for s in sources], "route_used": ROUTE,
            "strategies_used": [strategy_of(arm)], "strategy_errors": {}, "use_graph": False,
            "graph_strategies": []}


def top_k(pool: Sequence[str], scores: Mapping[str, float], k: int) -> tuple[str, ...]:
    """§3: sorted(pool, key=(−score, pid))[:k]; a pool passage without a score raises."""
    absent = [p for p in pool if p not in scores]
    if absent:
        raise gd.IntegrityError(f"pool passages without a reranker score (§10 分數缺漏): {absent[:5]}")
    top = tuple(sorted(pool, key=lambda p: (-scores[p], p))[:k])
    if len(top) != k:
        raise gd.IntegrityError(f"a pool of {len(pool)} passages cannot give k={k}")
    return top


def arm_items(qset: gd.QuestionSet, pools: Mapping[str, Sequence[str]],
              scores: Mapping[str, Mapping[str, float]], arm: str, k: int,
              rows: Mapping[str, SourceRow]) -> list[dict]:
    """The raw items of `arm` at `k`, in question-set order."""
    items = []
    for q in qset.questions:
        top = top_k(pools[q.qid], scores[q.qid], k)
        stray = [p for p in top if p not in rows]
        if stray:
            raise gd.IntegrityError(f"{q.qid}: passages outside the struct layer {stray}")
        items.append(raw_item(q.qid, q.question,
                              [passage_source(rows[p], float(scores[q.qid][p]), arm) for p in top], arm))
    return items


def run_meta_doc() -> dict[str, Any]:
    """run_meta.json: the build and the /health-shaped encoder fingerprint (§8, §10 pins)."""
    return {"data_build_id": gd.BUILD_ID,
            "encoder_fingerprint": {k: dict(gd.FINGERPRINTS[k]) for k in ("embedder", "reranker")}}


def check_run_meta(doc: Any, where: str) -> None:
    gd.expect(f"{where} (build + encoder fingerprint)", doc, run_meta_doc())


def _check_source(qid: str, src: Any, arm: str | None) -> str:
    if not (isinstance(src, dict) and set(src) == set(SOURCE_KEYS)):
        raise gd.IntegrityError(f"{qid}: a source must have exactly the keys {list(SOURCE_KEYS)}")
    if src["kind"] != KIND or not all(isinstance(src[k], str) and src[k]
                                      for k in ("id", "book", "start_key", "end_key")):
        raise gd.IntegrityError(f"{qid}: source {src.get('id')!r} is not a passage with id, book, "
                                "start_key and end_key")
    if arm is not None and src["strategy"] != strategy_of(arm):
        raise gd.IntegrityError(f"{qid}: source strategy {src['strategy']!r} is not {strategy_of(arm)!r}")
    return src["id"]


def check_raw(items: Any, qset: gd.QuestionSet, k: int, arm: str | None = None) -> None:
    """A raw file for E3: one item per question of `qset` in its order, its own question text,
    route OFFLINE, no strategy error and exactly k distinct passage sources (SOURCE_KEYS)."""
    if not isinstance(items, list):
        raise gd.IntegrityError("raw_responses.json must be a list of items")
    gd.expect("raw question ids (set order)", [i.get("question_id") for i in items
                                               if isinstance(i, dict)], list(qset.ids))
    by_id = qset.by_id()
    for item in items:
        qid = item["question_id"]
        if item.get("question") != by_id[qid].question:
            raise gd.IntegrityError(f"{qid}: raw question differs from the set's question text")
        if item.get("route_used") != ROUTE or item.get("strategy_errors"):
            raise gd.IntegrityError(f"{qid}: route_used must be {ROUTE!r} with no strategy_errors")
        sources = item.get("sources")
        if not (isinstance(sources, list) and len(sources) == k):
            raise gd.IntegrityError(f"{qid}: needs exactly k={k} sources (§8)")
        pids = [_check_source(qid, s, arm) for s in sources]
        if len(set(pids)) != k:
            raise gd.IntegrityError(f"{qid}: duplicate sources {pids}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_raw(raw_dir: Path) -> tuple[list, dict, dict[str, str]]:
    """(items, run_meta, {file name: sha256}) of a raw dir; run_meta must be the pinned one."""
    raw_dir = Path(raw_dir)
    blobs = {}
    for name in (RAW_NAME, RUN_META_NAME):
        try:
            blobs[name] = (raw_dir / name).read_bytes()
        except OSError as err:
            raise gd.IntegrityError(f"{raw_dir}: cannot read {name} ({err.strerror})") from None
    meta = json.loads(blobs[RUN_META_NAME])
    check_run_meta(meta, str(raw_dir / RUN_META_NAME))
    return json.loads(blobs[RAW_NAME]), meta, {n: sha256_bytes(b) for n, b in blobs.items()}


def write_json(path: Path, doc: Any, indent: int = 1) -> None:
    """Write `doc` whole via <path>.partial, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_raw_dir(out: Path, items: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """raw_responses.json (indent 2, as the collector writes it) and run_meta.json in a new
    or empty-of-them `out`; returns their sha256. Raw outputs are never overwritten."""
    out = Path(out)
    taken = [n for n in (RAW_NAME, RUN_META_NAME, BUILD_NAME) if (out / n).exists()]
    if taken:
        raise gd.GdError(f"{out} already holds {taken}; raw outputs are not overwritten")
    write_json(out / RAW_NAME, list(items), indent=2)
    write_json(out / RUN_META_NAME, run_meta_doc(), indent=2)
    return {n: gd.file_sha256(out / n) for n in (RAW_NAME, RUN_META_NAME)}
