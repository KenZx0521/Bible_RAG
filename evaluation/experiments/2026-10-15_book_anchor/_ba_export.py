"""Collector-format export of the book_anchor ablation (prereg §5 量尺, §6 I6/I7, §9 3.4/3.6).

Host only. Writes what evaluation/src/collector.py writes for a run, so the repo's tools read
it unchanged: <dir>/raw_responses.json (a list of {question_id, question, rag_answer,
contexts, context_source "backend", sources, route_used, strategies_used, strategy_errors,
use_graph, graph_strategies}, plus "ba": {arm, rep, ctx_sha}) and <dir>/run_meta.json
({data_build_id, encoder_fingerprint}, from the retrieval meta lines).

sources follow backend routers/query.py ``_source`` (book ← book_name, chapter ←
chapter_num, score ← fused_score else rerank_score, strategy ← source_strategy) through
evaluation's SourceInfo, dumped without "context" as the collector does. contexts are the
generator blocks rebuilt here with context_blocks.format_context_block (host_blocks); their
sha must equal the ctx_sha the container recorded with the backend's own function, else
ExportError (I7's export-time check).

export_retr: retr/{ctrl,nopin,off}/ for every question (an arm the driver skipped, M1,
takes ctrl's record). export_ans: ans/{arm}_r{rep}/ for every gen_plan item, the latest gen
record of each (failed answers written as they are: validity.answer_failure → generation).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_EVAL_ROOT = _HERE.parents[1]
for _p in (str(_HERE), str(_EVAL_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _ba_io as bio  # noqa: E402
from src.context_blocks import CONTEXT_SOURCE_BACKEND, format_context_block  # noqa: E402
from src.models import SourceInfo  # noqa: E402

__all__ = ["ARMS", "ExportError", "host_blocks", "verified_contexts", "source_dict",
           "arm_record", "raw_item", "run_meta", "write_run", "export_retr", "export_ans"]

ARMS = ("ctrl", "nopin", "off")
RAW = "raw_responses.json"
RUN_META = "run_meta.json"


class ExportError(ValueError):
    """Records that cannot be exported as they are (hash, plan or provenance mismatch)."""


def host_blocks(results: Sequence[Mapping[str, Any]]) -> list[str]:
    """The generator's context blocks, built with evaluation's byte-identical header."""
    return [format_context_block(i, _source_info(r), r.get("content", ""))
            for i, r in enumerate(results, 1)]


def verified_contexts(results: Sequence[Mapping[str, Any]], expected_sha: str) -> list[str]:
    blocks = host_blocks(results)
    got = bio.sha256_bytes("\n\n".join(blocks).encode("utf-8"))
    if got != expected_sha:
        raise ExportError(f"contexts ctx_sha {got[:12]} != recorded {str(expected_sha)[:12]}")
    return blocks


def _source_info(r: Mapping[str, Any]) -> SourceInfo:
    fused = r.get("fused_score")
    return SourceInfo(
        id=r["id"], book=r.get("book_name", ""), chapter=r.get("chapter_num"),
        title=r.get("title", ""), verse_range=r.get("verse_range", ""),
        score=fused if fused is not None else r.get("rerank_score"),
        strategy=r.get("source_strategy"), kind=r.get("kind"),
        start_key=r.get("start_key"), end_key=r.get("end_key"))


def source_dict(r: Mapping[str, Any]) -> dict[str, Any]:
    return _source_info(r).model_dump(exclude={"context"})


def arm_record(row: Mapping[str, Any], arm: str) -> Mapping[str, Any]:
    """The arm's retrieval record; an arm the driver skipped (M1) is ctrl's."""
    out = row["arms"].get(arm)
    if out is None:
        if not row.get("arms_skipped"):
            raise ExportError(f"{row['qid']}: arm {arm} missing but arms_skipped not set")
        return row["arms"]["ctrl"]
    return out


def raw_item(row: Mapping[str, Any], arm: str, answer: str,
             rep: int | None = None) -> dict[str, Any]:
    rec = arm_record(row, arm)
    stats = rec["stats"]
    return {
        "question_id": row["qid"], "question": row["question"], "rag_answer": answer,
        "contexts": verified_contexts(rec["results"], rec["ctx_sha"]),
        "context_source": CONTEXT_SOURCE_BACKEND,
        "sources": [source_dict(r) for r in rec["results"]],
        "route_used": stats.get("route_used", ""),
        "strategies_used": stats.get("strategies_used", []),
        "strategy_errors": stats.get("strategy_errors", {}) or {},
        "use_graph": stats.get("use_graph", True),
        "graph_strategies": stats.get("graph_strategies"),
        "ba": {"arm": arm, "rep": rep, "ctx_sha": rec["ctx_sha"]},
    }


def run_meta(metas: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """{data_build_id, encoder_fingerprint} the retrieve meta lines agree on."""
    metas = list(metas)
    builds = {m.get("build_id") for m in metas}
    retrieve = [m for m in metas if m.get("mode") == "retrieve"]
    fps = {json.dumps(m.get("encoder_fingerprint"), sort_keys=True) for m in retrieve}
    if len(builds) != 1 or None in builds:
        raise ExportError(f"meta lines name builds {sorted(map(str, builds))}")
    if not retrieve or len(fps) != 1 or "null" in fps:
        raise ExportError("retrieve meta lines do not agree on one encoder fingerprint")
    return {"data_build_id": builds.pop(), "encoder_fingerprint": json.loads(fps.pop())}


def write_run(directory: Path, items: Sequence[Mapping[str, Any]],
              meta: Mapping[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RAW).write_text(json.dumps(list(items), ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    (directory / RUN_META).write_text(json.dumps(dict(meta), ensure_ascii=False, indent=2),
                                      encoding="utf-8")


def export_retr(metas: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]],
                out_dir: Path) -> dict[str, Path]:
    """retr/{arm}/ for every question, retrieval only (rag_answer "")."""
    meta = run_meta(metas)
    written = {}
    for arm in ARMS:
        items = [raw_item(rows[qid], arm, "") for qid in sorted(rows)]
        write_run(Path(out_dir) / arm, items, meta)
        written[arm] = Path(out_dir) / arm
    return written


def export_ans(metas: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]],
               gens: Iterable[Mapping[str, Any]], plan: Sequence[Mapping[str, Any]],
               out_dir: Path) -> dict[str, Path]:
    """ans/{arm}_r{rep}/ for every plan item, from the latest gen record of its key."""
    meta = run_meta(metas)
    latest = bio.latest_gens(gens)
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in plan:
        key = (item["qid"], item["arm"], int(item["rep"]))
        gen = latest.get(key)
        if gen is None:
            raise ExportError(f"{key}: no gen record")
        recorded = arm_record(rows[item["qid"]], item["arm"])["ctx_sha"]
        if not (gen.get("ctx_sha") == item.get("ctx_sha") == recorded):
            raise ExportError(f"{key}: ctx_sha of gen / plan / retrieval differ")
        groups[f"{item['arm']}_r{int(item['rep'])}"].append(
            raw_item(rows[item["qid"]], item["arm"], gen.get("answer") or "", int(item["rep"])))
    written = {}
    for name, items in sorted(groups.items()):
        items.sort(key=lambda x: x["question_id"])
        write_run(Path(out_dir) / name, items, meta)
        written[name] = Path(out_dir) / name
    return written
