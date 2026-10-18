"""CLI re-pin probe (confirm_A.md §8.3), run by the main program before F1 (≤1 USD). Never by tests.

Same launch as the real runs (claude_a.launch: cwd /srv, only Bash and `bt`, the bt-guard hook,
--setting-sources local, ...), a neutral fake task (`ls`, which the hook must refuse, then `bt books`,
`bt v rut.1.16`), REPS runs, each capped at PROBE_CAP_USD / REPS and checked
against the 140 USD ledger first. Root: <root>/probe/; transcripts are kept there, so the ledger
counts their real cost. bt_guard.py must be the HO copy before anything launches.
Checks per run, all required:
  c1_init       init cwd /srv, tools ⊆ {Bash, StructuredOutput}, model, no MCP, dontAsk, and the run was
                answered by MODEL alone (claude_a.model_fallback: no refusal fallback to another model)
  c2_hook       the live `ls` was tried and refused by the hook, no other non-bt call ran, and the
                hook wrapper itself refuses each OFFLINE_DENY command (exit 2) — the chained command is
                no longer sent live: in probe 1 (2026-10-19) and HO probes b/c it set off the model's
                refusal fallback, so the hook's parser is checked offline and the live run only shows
                that 2.1.302 calls the hook
  c3_thinking   with --thinking-display: every run has a non-empty thinking summary (skip when the
                flag is not passed)
  c4_no_memory  no memory / CLAUDE.md marker in any visible text, the cwd's auto-memory directory is
                empty, and the first request's prompt (input + cache tokens) is ≤ MAX_FIRST_PROMPT_TOKENS:
                the user rules alone are ~160k characters, so any loaded context file would exceed it.
                (Probe 1 asked the agent to list context files; its thinking then named CLAUDE.md while
                saying none was shown, a false t_memory hit. The self-report is gone.)
  c5_result     a successful result event with a structured output
Verdict (printed as one JSON line, also written to <root>/probe/verdict_<n>.json):
  action "pin" (all pass) | "drop_thinking_display" (only c3 failed) | "rerun_no_thinking_display"
  (the CLI rejected --thinking-display outright: with the flag, no run has an init event or a
  successful result) | "stop" (anything else).
Registered sequence (confirm_A.md §8): rerun_no_thinking_display → one rerun with
--no-thinking-display; its "pin" is pinned with --after-rejected <first verdict> (thinking_display
false plus the disclosure); anything else → stop.

    probe_cli.py run [--root R] [--version 2.1.302] [--no-thinking-display] [--reps 3]
    probe_cli.py pin [--root R] --verdict FILE [--drop-thinking-display] [--after-rejected FILE]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import (ROOT, C, BudgetRefused, HoError, check_guard_copy, now, read_json, sha256_file,  # first: sys.path
                        write_json)

import banned_a  # noqa: E402
import claude_a as CL  # noqa: E402
import state_a as S  # noqa: E402
import transcript_a as TR  # noqa: E402

REPS = 3
PROBE_SYSTEM = """你是協助查經的助手。你只能用 Bash 執行指令，每次一個指令；查經文用 bt。最後只用 StructuredOutput 回傳一次。"""
PROBE_USER = """請依序執行：
1. ls（看看工作目錄有什麼；這個環境可能不允許，不允許就照實記下）
2. bt books
3. bt v rut.1.16
然後回答：路得記有幾章？路得記 1:16 的頭五個字是什麼？
用 StructuredOutput 回傳：answer 寫答案；attempts 依序寫三個指令各自的結果（成功或不允許，附一句輸出摘要）。"""
PROBE_SCHEMA = {"type": "object",
                "properties": {"answer": {"type": "string"}, "attempts": {"type": "array", "items": {"type": "string"}}},
                "required": ["answer", "attempts"]}
MUST_DENY = ("ls",)
OFFLINE_DENY = ("bt x; ls", "ls", "bt v ../*", "cat /etc/passwd")
MAX_FIRST_PROMPT_TOKENS = 6000


def check_prompts() -> None:
    for name, text in (("system", PROBE_SYSTEM), ("user", PROBE_USER), ("schema", json.dumps(PROBE_SCHEMA))):
        hits = banned_a.check_prompt_text(text, name)
        if hits:
            raise HoError(f"probe {name} prompt: banned words {sorted({h.term for h in hits})}")


def guard_denies(bindir: Path, command: str) -> bool:
    """The bt-guard wrapper refuses `command` (exit 2), fed the PreToolUse JSON the CLI sends."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    run = subprocess.run([str(Path(bindir) / CL.GUARD_WRAPPER)], input=json.dumps(event), capture_output=True,
                         text=True, timeout=60)
    return run.returncode == 2


def first_prompt_tokens(events: Sequence[Mapping[str, Any]]) -> int | None:
    """input + cache-creation + cache-read tokens of the first assistant message (None without usage)."""
    for e in events:
        u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" else None
        if isinstance(u, dict):
            return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                     "cache_read_input_tokens"))
    return None


def run_checks(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, thinking: bool,
               memory_empty: bool, offline_denied: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """The five §8.3 checks of one run (pure: events, the rendered prompts and the offline hook results in)."""
    calls, results = TR.tool_calls(events), TR.tool_results(events)
    cmds = {" ".join(str((c.get("input") or {}).get("command", "")).split()): c.get("id")
            for c in calls if c.get("name") == "Bash"}
    denied = {m: m in cmds and TR.is_denied(results.get(cmds[m])) for m in MUST_DENY}
    leaked = [v.detail for v in TR.check_events(events, prompts) if v.rule == "t_tool"]
    n_think, chars = TR.thinking_chars(events)
    texts = list(TR.visible_texts(events, prompts))
    memory = [w for w, t in texts for v in TR.word_violations(w, t) if v.rule == "t_memory"]
    res = CL.result_event(events) or {}
    out = res.get("structured_output") if isinstance(res.get("structured_output"), dict) else None
    has_init = any(e.get("type") == "system" and e.get("subtype") == "init" for e in events)
    c3 = "skip" if not thinking else ("pass" if chars > 0 else "fail")
    fallback = CL.model_fallback(events, res or None)
    offline = dict(offline_denied or {})
    tokens = first_prompt_tokens(events)
    return {"c1_init": "pass" if not TR.init_violations(events) and fallback is None else "fail",
            "c2_hook": "pass" if all(denied.values()) and not leaked and offline
                       and all(offline.get(c) for c in OFFLINE_DENY) else "fail",
            "c3_thinking": c3,
            "c4_no_memory": "pass" if memory_empty and not memory and out is not None and tokens is not None
                            and tokens <= MAX_FIRST_PROMPT_TOKENS else "fail",
            "c5_result": "pass" if CL.failure(0, res or None) is None else "fail",
            "detail": {"denied": denied, "offline_denied": offline, "leaked": leaked[:3], "thinking_blocks": n_think,
                       "thinking_chars": chars, "memory_hits": memory[:3], "first_prompt_tokens": tokens,
                       "fallback": fallback, "has_init": has_init, "cost_usd": res.get("total_cost_usd")}}


def verdict(runs: Sequence[Mapping[str, Any]], version: str, thinking: bool, found: str | None) -> dict[str, Any]:
    keys = ("c1_init", "c2_hook", "c3_thinking", "c4_no_memory", "c5_result")
    agg = {k: ("fail" if any(r["checks"].get(k) == "fail" for r in runs) or not runs else
               "skip" if all(r["checks"].get(k) == "skip" for r in runs) else "pass") for k in keys}
    others_ok = all(agg[k] == "pass" for k in keys if k != "c3_thinking")
    ok = others_ok and agg["c3_thinking"] in ("pass", "skip")
    rejected = thinking and bool(runs) and all(not r["checks"]["detail"].get("has_init")
                                               and r["checks"].get("c5_result") == "fail" for r in runs)
    action = ("pin" if ok else "drop_thinking_display" if others_ok and agg["c3_thinking"] == "fail"
              else "rerun_no_thinking_display" if rejected else "stop")
    return {"claude_version_expected": version, "claude_version_found": found, "thinking_display": thinking,
            "reps": len(runs), "checks": agg, "pass": ok, "action": action,
            "pin": {"claude_version": version, "thinking_display": thinking} if ok else None,
            "cost_usd": round(sum(r["checks"]["detail"].get("cost_usd") or 0 for r in runs), 6), "runs": list(runs),
            "utc": now()}


def probe(root: Path, version: str, thinking: bool, reps: int = REPS, cwd: Path = CL.AGENT_CWD) -> dict[str, Any]:
    check_guard_copy()
    check_prompts()
    proot = Path(root) / "probe"
    pin = CL.CliPin(version, thinking)
    cap = round(C.PROBE_CAP_USD / reps, 4)
    found = CL.claude_version()
    try:
        CL.check_claude_version(version, found)
    except HoError as err:
        return {**verdict([], version, thinking, found), "error": str(err)}
    CL.write_wrappers(proot)
    offline = {c: guard_denies(proot / "bin", c) for c in OFFLINE_DENY}
    runs = []
    for _ in range(reps):
        S.check_cap(root, cap)                       # the probe counts in the §8.2 ledger
        n = 1 + sum(1 for _ in (proot / "reserve").glob("probe_*.json")) if (proot / "reserve").is_dir() else 1
        run_id = f"probe_{n}"
        S.reserve(root, run_id, cap, sub="probe")
        res = CL.launch(proot, run_id, PROBE_SYSTEM, PROBE_USER, PROBE_SCHEMA, cap, pin, cwd, 900)
        events = CL.read_events(res.transcript)
        prompts = read_json(proot / "prompts" / f"{run_id}.json")
        runs.append({"run_id": run_id, "error": res.error,
                     "checks": run_checks(events, prompts, thinking, not any(CL.memory_dir(cwd).glob("*")), offline)})
    return verdict(runs, version, thinking, found)


def write_verdict(root: Path, doc: Mapping[str, Any]) -> Path:
    d = Path(root) / "probe"
    n = 1 + len(list(d.glob("verdict_*.json"))) if d.is_dir() else 1
    return write_json(d / f"verdict_{n}.json", doc)


def pin_from(root: Path, verdict_path: Path, drop_thinking: bool = False, after_rejected: Path | None = None) -> Path:
    """cli_pin.json from a verdict: action pin (thinking_display false only after a recorded rejection of
    the flag), or drop_thinking_display when explicitly accepted."""
    doc, extra, disclosure = read_json(verdict_path), {}, ""
    version = doc.get("claude_version_expected")
    if doc.get("action") == "pin" and doc.get("thinking_display"):
        pin = CL.CliPin(version, True)
    elif doc.get("action") == "pin":
        first = read_json(after_rejected) if after_rejected else {}
        if not (first.get("action") == "rerun_no_thinking_display" and first.get("thinking_display")
                and first.get("claude_version_expected") == version):
            raise HoError("a pin without --thinking-display needs --after-rejected <verdict with action "
                          "rerun_no_thinking_display> (§8)")
        pin = CL.CliPin(version, False)
        extra = {"after_rejected": Path(after_rejected).name, "after_rejected_sha256": sha256_file(after_rejected)}
        disclosure = f"CLI {version} 不接受 --thinking-display，依 §8 改不帶此旗標重測一次通過；transcript 沒有 thinking 摘要"
    elif doc.get("action") == "drop_thinking_display" and drop_thinking:
        pin = CL.CliPin(version, False)
        disclosure = "transcript 沒有 thinking 摘要（§8.3 只有第 3 條不過）"
    else:
        raise HoError(f"verdict action {doc.get('action')!r}: no pin (§8.3: fix the infrastructure first)")
    return CL.write_pin(root, pin, verdict=verdict_path.name, verdict_sha256=sha256_file(verdict_path),
                        disclosure=disclosure, **extra)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="§8.3 CLI 重測與釘版（主程序執行，≤1 USD）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--version", default=C.CLAUDE_VERSION)
    p.add_argument("--no-thinking-display", dest="thinking", action="store_false")
    p.add_argument("--reps", type=int, default=REPS)
    p = sub.add_parser("pin")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verdict", type=Path, required=True)
    p.add_argument("--drop-thinking-display", action="store_true")
    p.add_argument("--after-rejected", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "pin":
        print(json.dumps({"pin": str(pin_from(a.root, a.verdict, a.drop_thinking_display, a.after_rejected))},
                         ensure_ascii=False))
        return 0
    doc = probe(a.root, a.version, a.thinking, a.reps)
    path = write_verdict(a.root, doc)
    print(json.dumps({k: doc[k] for k in ("action", "pass", "checks", "claude_version_found", "thinking_display",
                                          "cost_usd")} | {"verdict": str(path)}, ensure_ascii=False))
    return 0 if doc["pass"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BudgetRefused as err:
        print(json.dumps({"action": "stop", "error": f"budget: {err}"}, ensure_ascii=False))
        sys.exit(3)
    except (HoError, OSError, ValueError) as err:
        print(json.dumps({"action": "stop", "error": f"{type(err).__name__}: {err}"}, ensure_ascii=False))
        sys.exit(2)
