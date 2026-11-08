"""What a collection's graph side did: per question (raw, CSV) and in total (run_meta, console).

The backend reports each request's ``graph_trace`` (backend/utils/graph_trace.py). A checkpoint or
backend from before 2026-11-02 does not (None): its operations are read back from what the record
has, the event_registry sources and the aux_card, with a card's hops unknown.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .validity import GENERATION_ERROR_PREFIX

# D3 (evaluation/experiments/2026-10-18_kg_cards/prereg.md): one edge is a lookup, not a graph walk
WALK_MIN_HOPS = 2
MAX_SKIPPED_SHARE = 0.05


def _read_back(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    events = record.get("event_registry_events") or []
    passages = [s.get("id") for s in record.get("sources") or [] if s.get("strategy") == "event_registry"]
    ops = []
    if events or passages:
        ops.append({"op": "event_registry", "hops": 1 if passages else 0, "nodes": list(events), "edges": [],
                    "injected": "context" if passages else "none", "passages": passages})
    card = record.get("aux_card")
    if card:
        ops.append({"op": f"{card.get('kind', 'regnal')}_card", "hops": None,
                    "nodes": list(card.get("kings") or []), "edges": [], "injected": "prompt", "passages": []})
    return ops


def ops_of(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The record's graph operations: as reported, else read back."""
    trace = record.get("graph_trace")
    return _read_back(record) if trace is None else trace


def _failed(record: Mapping[str, Any]) -> bool:
    """No answer came back: the request failed, or the generator answered with its error text."""
    return ("request" in (record.get("strategy_errors") or {})
            or str(record.get("rag_answer") or "").startswith(GENERATION_ERROR_PREFIX))


def _reached_answer(op: Mapping[str, Any]) -> bool:
    return op.get("injected") != "none"


def is_walk(op: Mapping[str, Any]) -> bool:
    """A graph walk whose result reached the context or the prompt."""
    hops = op.get("hops")
    return hops is not None and hops >= WALK_MIN_HOPS and _reached_answer(op)


def _by_op(per_question: list[list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    names = sorted({op["op"] for ops in per_question for op in ops})
    usage = {}
    for name in names:
        hit = [[op for op in ops if op["op"] == name] for ops in per_question]
        hit = [ops for ops in hit if ops]
        hops = [op["hops"] for ops in hit for op in ops if op.get("hops") is not None]
        usage[name] = {"n_questions": len(hit),
                       "n_injected": sum(any(_reached_answer(op) for op in ops) for ops in hit),
                       "max_hops": max(hops, default=None)}
    return usage


def _skipped(per_question: list[list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    """Operation -> why it gave nothing -> how many questions (graph_walk, kin_card report a reason)."""
    found: dict[str, dict[str, int]] = {}
    for ops in per_question:
        for op in ops:
            if op.get("skip_reason"):
                reasons = found.setdefault(op["op"], {})
                reasons[op["skip_reason"]] = reasons.get(op["skip_reason"], 0) + 1
    return found


def summarize(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts of questions, not of operations; ``n_walk`` is the one that says a graph was walked.
    A question with no answer (``n_failed``) is in no other count: nothing reached an answer."""
    records = list(records)
    answered = [r for r in records if not _failed(r)]
    per_question = [ops_of(r) for r in answered]
    return {
        "n_questions": len(records),
        "n_failed": len(records) - len(answered),
        "n_trace_reported": sum(r.get("graph_trace") is not None for r in answered),
        "n_with_op": sum(bool(ops) for ops in per_question),
        "n_injected": sum(any(_reached_answer(op) for op in ops) for ops in per_question),
        "n_walk": sum(any(is_walk(op) for op in ops) for ops in per_question),
        "n_hops_unknown": sum(any(op.get("hops") is None for op in ops) for ops in per_question),
        "n_nodes": sum(len(op.get("nodes") or []) for ops in per_question for op in ops),
        "n_edges": sum(len(op.get("edges") or []) for ops in per_question for op in ops),
        "n_cypher": sum(op.get("n_cypher") or 0 for ops in per_question for op in ops),
        "skipped": _skipped(per_question),
        "by_op": _by_op(per_question),
    }


def report_lines(usage: Mapping[str, Any], mode: str) -> list[str]:
    """What to print after a collection. The main arm is told plainly when nothing walked a graph."""
    n = usage["n_questions"] - usage["n_failed"]
    if n == 0:
        return [f"圖譜使用：{usage['n_failed']} 題全部請求或生成失敗，沒有圖譜數字。"]
    lines = [f"圖譜使用：走訪（≥{WALK_MIN_HOPS} 跳）{usage['n_walk']}/{n} 題｜"
             f"進到答案 {usage['n_injected']}/{n} 題｜有執行 {usage['n_with_op']}/{n} 題｜"
             f"節點 {usage['n_nodes']}、邊 {usage['n_edges']}"]
    lines += [f"  {name}：{op['n_questions']} 題，進到答案 {op['n_injected']} 題，"
              f"最長 {'未知' if op['max_hops'] is None else op['max_hops']} 跳"
              for name, op in usage["by_op"].items()]
    lines += [f"  {name} 沒有結果：" + "、".join(f"{why} {n} 題" for why, n in reasons.items())
              for name, reasons in usage["skipped"].items()]
    if usage["n_failed"]:
        lines.append(f"  另有 {usage['n_failed']} 題請求或生成失敗，不計入")
    if usage["n_trace_reported"] < n:
        lines.append(f"  backend 回報 trace {usage['n_trace_reported']}/{n} 題，"
                     f"其餘由 sources、aux_card 推得（{usage['n_hops_unknown']} 題卡片跳數未知）")
    if mode == "main" and usage["n_walk"] == 0 and usage["n_hops_unknown"] == 0:
        lines.append("[bold red]主架構這次沒有任何題走到圖譜走訪，這輪數字不含圖譜走訪的效果。[/bold red]")
    lines += _skip_warnings(usage, mode, n)
    return lines


def _skip_warnings(usage: Mapping[str, Any], mode: str, n: int) -> list[str]:
    """A main arm whose graph was off for many questions measures something else (2026-11-03: 81 of 112)."""
    if mode != "main":
        return []
    skipped = {name: sum(reasons.values()) for name, reasons in usage["skipped"].items()}
    return [f"[bold red]{name} 有 {count}/{n} 題沒跑成，這輪數字低估圖譜，先查原因再看結果。[/bold red]"
            for name, count in skipped.items() if count / n > MAX_SKIPPED_SHARE]


def csv_columns(trace: list[dict[str, Any]] | None) -> tuple[str, int | str]:
    """(graph_ops, graph_max_hops); both blank when the backend did not report, which is not 0."""
    if trace is None:
        return "", ""
    hops = [op["hops"] for op in trace if op.get("hops") is not None]
    return "|".join(op["op"] for op in trace), max(hops, default=0)
