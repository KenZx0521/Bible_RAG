"""Shared helpers of the A confirmation-set question-writing tests (test_kg_cards_confirm_a_*.py).

Synthetic questions are built at test time from segments.json candidates and the reference layer's
king names with fixed template wording (no question text of the real set, no scripture text).
FakeLauncher stands in for claude_a.launch: it writes a stream-json transcript and the prompts
record like the real launch and returns canned structured outputs; nothing is launched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

HO_A = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_kg_cards" / "A" / "confirm" / "ho_a"
import sys  # noqa: E402

if str(HO_A) not in sys.path:
    sys.path.insert(0, str(HO_A))

import hoa_common as H  # noqa: E402

C = H.C
CN = {1: "一", 2: "二", 3: "三", 4: "四"}
STORE_OK = C.LAYER_REF.is_file() and C.LAYER_AUTO.is_file() and C.SEGMENTS.is_file()
NO_RESULT = "<no result event>"   # an agent output that makes FakeLauncher write no result event (infra failure)


def seg_doc() -> dict:
    return H.read_json(C.SEGMENTS)


def seg_row(sid: str) -> dict:
    return next(s for s in seg_doc()["segments"] if s["id"] == sid)


def _basis(seg: dict, x: str) -> list[str]:
    import segments as SG
    import support as SU
    keys = [v for v in SG.kverses(x) if SU.in_range(seg, v)]
    return keys[:1] or [seg["range"][0]]


def _named(seg: dict, x: str) -> tuple[str, str | None]:
    """How a question names king x: 「name（F的兒子）」 for a same-kingdom namesake."""
    import support as SU
    nm, f = SU.ref()[x]["name"], SU.required_tag(x)
    return (f"{nm}（{f}的兒子）", f) if f else (nm, None)


def make_question(qid: str, seg: dict, cand: dict) -> dict:
    """A §2.8 question for one segment candidate (template wording)."""
    import support as SU
    kn, qt = seg["kingdom_name"], cand["qtype"]
    kings = seg["kings"]
    if qt == "S1b":
        a, b = kings.index(cand["a"]), kings.index(cand["b"])
        path, seeds = kings[a:b + 1], [cand["a"], cand["b"]]
    else:
        i, j = kings.index(cand["seed"]), kings.index(cand["answer"])
        path = kings[i:j + 1] if j > i else kings[j:i + 1][::-1]
        seeds = [cand["seed"]]
    names = [_named(seg, x) for x in seeds]
    s0 = names[0][0]
    if qt == "S1a":
        word = "之後" if cand["k"] > 0 else "之前"
        question = f"{kn}王{s0}{word}的第{CN[abs(cand['k'])]}位{kn}王是誰？"
    elif qt == "S1b":
        question = f"從{kn}王{s0}到{kn}王{names[1][0]}，王位一共交接了幾次（{s0}傳給下一位算第一次）？"
    elif qt == "S1c":
        question = f"{kn}王{s0}之後，第{CN[cand['n']]}個篡位得國的{kn}王是誰？"
    else:
        question = f"依經文記載的登基年齡與歷代在位年數，各王在位年數前後相接推算，猶大王{s0}出生時在位的猶大王是誰？"
    roles = ["seed"] + ["step"] * (len(path) - 2) + ["answer"]
    chain = [{"king": SU.ref()[x]["name"], "father": _named(seg, x)[1], "role": r, "fact": "（測試）",
              "basis": _basis(seg, x)} for x, r in zip(path, roles)]
    count = qt == "S1b"
    ans_name = SU.ref()[path[-1]]["name"]
    return {"id": qid, "segment": seg["id"], "qtype": qt, "kingdom": kn, "question": question,
            "seeds": [{"name": SU.ref()[x]["name"], "father": f} for x, (_n, f) in zip(seeds, names)],
            "k": cand.get("k") if qt == "S1a" else None, "n": cand.get("n") if qt == "S1c" else None,
            "answer": {"kind": "count" if count else "name", "text": f"{cand['value']}次" if count else ans_name,
                       "accept": [], "value": cand["value"] if count else None, "unit": "次" if count else None},
            "chain": chain, "convention": "（測試）甲、乙兩種算法" if qt == "S4" else "",
            "shortcut_search": "（測試）", "conflict_search": "（測試）", "notes": "", "change_log": ""}


# ---------------------------------------------------------------- transcripts

def init_event(cwd: str = "/srv") -> dict:
    return {"type": "system", "subtype": "init", "cwd": cwd, "tools": ["Bash", "StructuredOutput"],
            "model": "claude-opus-5-5", "permissionMode": "dontAsk", "mcp_servers": []}


def tool_pair(n: int, command: str, result: str, denied: bool = False) -> list[dict]:
    use = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{n}", "name": "Bash",
                                                         "input": {"command": command}}]}}
    res = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}", "is_error": denied,
                                                    "content": f"denied: {result}" if denied else result}]}}
    return [use, res]


def events_for(output: dict | None, cost: float, extra: list | None = None, thinking: str = "（摘要）",
               subtype: str = "error_max_turns") -> list[dict]:
    """A stream-json run; output None ends on an agent-limit error result (subtype)."""
    ev = [init_event(), {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": thinking}]}},
          *tool_pair(1, "bt v 1ki.15.8", "1ki.15.8 （測試經文）"), *(extra or [])]
    ev.append({"type": "result", "subtype": "success", "is_error": False, "structured_output": output,
               "total_cost_usd": cost, "num_turns": 3} if output is not None else
              {"type": "result", "subtype": subtype, "is_error": True, "total_cost_usd": cost})
    return ev


class FakeLauncher:
    """claude_a.launch stand-in: agent(kind, qid, user, root) -> (output | None, cost, extra events)."""

    def __init__(self, agent: Callable[..., tuple]):
        self.agent, self.calls = agent, []

    def __call__(self, root, run_id, system, user, schema, budget, pin, cwd=None, timeout_s=None, extra_record=None):
        import claude_a as CL
        root, rec = Path(root), dict(extra_record or {})
        (root / "transcripts").mkdir(parents=True, exist_ok=True)
        (root / "prompts").mkdir(parents=True, exist_ok=True)
        (root / "prompts" / f"{run_id}.json").write_text(json.dumps(
            {"run_id": run_id, "system": system, "user": user, "budget_usd": budget, **rec}, ensure_ascii=False))
        output, cost, extra = self.agent(rec.get("kind"), rec.get("qid"), user, root)
        events = events_for(None, cost, extra)[:-1] if output == NO_RESULT else events_for(output, cost, extra)
        path = root / "transcripts" / f"{run_id}.jsonl"
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
        self.calls.append((rec.get("kind"), rec.get("qid"), run_id))
        result = CL.result_event(events)
        return CL.RunResult(run_id, path, 0, 0.1, result, CL.run_error(0, result, events),
                           CL.usage_of(result, events))


def write_pin(root: Path) -> None:
    import claude_a as CL
    CL.write_pin(root, CL.CliPin("2.1.302", True), verdict="test")
