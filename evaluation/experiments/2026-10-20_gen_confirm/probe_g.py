"""CLI probe and pin of the GEN confirmation set (prereg §3.1, §8.1-2, §8.2); the main program runs it, tests never.

Copy of experiment A's ho_a/probe_cli.py (the original untouched) for both tools modes of claude_g. One invocation
copies the CLI ~/.local/share/claude/versions/<v> into CLI_DIR/<v>/ (copy_cli; §3.1: the source must hash as the
qset's known sha256 for its version, or for any other version as the operator's --cli-sha256; no trust on first
use) and runs, from that copy, in its own root PROBE_ROOT/<n>/:

* mode bt, Opus 5.5, REPS_BT runs: A's neutral fake task (`ls`, which the hook must refuse, then `bt books`,
  `bt v rut.1.16`) and A's five checks:
    c1_init       init cwd, tools ⊆ {Bash, StructuredOutput}, model, CLI version, no MCP, dontAsk, and the run was
                  answered by the model alone (claude_g.model_fallback)
    c2_hook       the live `ls` was tried and refused by the hook, no other non-bt call ran, and the hook wrapper
                  refuses each OFFLINE_DENY command (exit 2); the chained command is not sent live (in A's probe 1
                  and HO probes b/c it set off the model's refusal fallback)
    c3_thinking   with --thinking-display: every run has a non-empty thinking summary (skip without the flag)
    c4_no_memory  no memory marker in any visible text, the cwd's auto-memory directory empty, a structured output,
                  and the first request's prompt (input + cache tokens) ≤ MAX_FIRST_PROMPT_TOKENS (the user rules
                  alone are ~160k characters: any loaded context file would exceed it)
    c5_result     a successful result event with a structured output
* mode none (the qset writers, §5.4), one run each with Opus 5.5 and Sonnet 5.5: a neutral no-tool task and the
  qset probe's five checks: c1_init (tools ⊆ {StructuredOutput}), c2_structured_output (StructuredOutput offered,
  no other tool call, the output has the schema's fields), c3_model (init model, modelUsage only that model, no
  fallback), c4_no_memory, c5_result. Thinking is recorded, not checked (the pin's flag is c3_thinking's).

Verdict (one JSON line; also PROBE_ROOT/verdict_<n>.json; it records the sha basis and the source's size and mtime,
the probed (mode, model) pairs and the names of the environment variables the agents got): action "pin" |
"drop_thinking_display" (only c3_thinking failed) | "rerun_no_thinking_display" (with the flag no run had an init
event or a successful result: the CLI rejected it) | "stop". Registered sequence (A): rerun_no_thinking_display →
one rerun with --no-thinking-display, whose "pin" is pinned with --after-rejected <first verdict>.
``pin`` writes the single pin file claude_g.PIN_PATH (store cli_pin.json, shared by HO and qset) from a passing
verdict: version, the copy's path and sha256 (rechecked), thinking flag, the model ids that answered, the probed
(mode, model) pairs (all of claude_g.PROBED_COMBOS), with the sha basis and the environment key names recorded.
`claude --version` with no answer (CliUnavailable) stops the invocation before any run, like a version mismatch.

Budget (ledger_g, kind probe): every run is reserved before it starts; at most PROBE_MAX_RUNS invocations and
PROBE_CAP_USD over all of them, and an invocation starts only when its whole plan fits (INVOCATION_CAP_USD).
Caps come from the real costs (result events of the store transcripts, read-only, CLI 2.1.302, effort xhigh):
  A's probe (A_confirm/ho/probe/, mode bt, Opus 5.5): invocation 1 0.0577 / 0.1022 / 0.1016 (runs 2 and 3 sent the
  chained command and fell back to Opus 4.8, now offline), invocation 2 0.0488 / 0.0267 / 0.0273; 0.364 in all.
  The qset probe (regnal_qset_20261019/probe/, mode none, a 3-slot writer job): Opus 0.0251, Sonnet 0.0146.
So a bt run is capped at 0.12 (above every run seen, fallbacks included; 2× the largest one without), a none run at
0.06 (Opus, 2.4×) and 0.04 (Sonnet, 2.7×); one invocation reserves at most 3 × 0.12 + 0.06 + 0.04 = 0.46 and two
0.92 ≤ 1 USD, leaving 0.08 for --max-budget-usd overshoot. Expected about 0.16 per invocation (prereg §8.2: 0.4).

    probe_g.py run --version 2.1.302 [--cli-sha256 SHA] [--no-thinking-display] [--reps 3]
    probe_g.py pin --verdict FILE [--drop-thinking-display] [--after-rejected FILE]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import banned_g as B
import claude_g as CL
import g_common as GC
import hog_common as H
import k0_g as K0
import ledger_g as L
import transcript_g as TR
from hog_common import BudgetRefused, HoError, now, read_json, write_json

REPS_BT = GC.PROBE_REPS_BT
RUN_CAP_USD = GC.PROBE_RUN_CAP_USD
NONE_MODELS = ("opus", "sonnet")
INVOCATION_CAP_USD = GC.PROBE_INVOCATION_CAP_USD    # REPS_BT bt runs + one none run per model: 0.46
PROBE_TIMEOUT_S = 900
PROBE_SYSTEM = """你是協助查經的助手。你只能用 Bash 執行指令，每次一個指令；查經文用 bt。最後只用 StructuredOutput 回傳一次。"""
PROBE_USER = """請依序執行：
1. ls（看看工作目錄有什麼；這個環境可能不允許，不允許就照實記下）
2. bt books
3. bt v rut.1.16
然後回答：路得記有幾章？路得記 1:16 的頭五個字是什麼？
用 StructuredOutput 回傳：answer 寫答案；attempts 依序寫三個指令各自的結果（成功或不允許，附一句輸出摘要）。"""
PROBE_SCHEMA = {"type": "object", "required": ["answer", "attempts"],
                "properties": {"answer": {"type": "string"},
                               "attempts": {"type": "array", "items": {"type": "string"}}}}
NONE_SYSTEM = """你是協助整理文字的助手。這次沒有任何工具可用。最後只用 StructuredOutput 回傳一次。"""
NONE_USER = """請回答：一個星期有幾天？再寫一個和天氣有關的四字詞。
用 StructuredOutput 回傳：days 寫天數（整數）；word 寫那個四字詞。"""
NONE_SCHEMA = {"type": "object", "properties": {"days": {"type": "integer"}, "word": {"type": "string"}},
               "required": ["days", "word"]}
MUST_DENY = ("ls",)
OFFLINE_DENY = ("bt x; ls", "ls", "bt v ../*", "cat /etc/passwd")
MAX_FIRST_PROMPT_TOKENS = 6000
BT_KEYS = ("c1_init", "c2_hook", "c3_thinking", "c4_no_memory", "c5_result")
NONE_KEYS = ("c1_init", "c2_structured_output", "c3_model", "c4_no_memory", "c5_result")


def check_prompts() -> None:
    """Every probe prompt and schema passes banned_g's full prompt check."""
    parts = (("system", PROBE_SYSTEM), ("user", PROBE_USER), ("schema", json.dumps(PROBE_SCHEMA)),
             ("none system", NONE_SYSTEM), ("none user", NONE_USER), ("none schema", json.dumps(NONE_SCHEMA)))
    for name, text in parts:
        hits = B.prompt_hits(text, name)
        if hits:
            raise HoError(f"probe {name} prompt: blinded words {sorted({h.term for h in hits})}")


def plan(reps: int = REPS_BT) -> list[tuple[str, str, str, float]]:
    """(run id, tools mode, model key, cap) of one invocation."""
    return [(f"bt_{i}", "bt", "opus", RUN_CAP_USD["bt"]) for i in range(1, reps + 1)] + \
        [(f"none_{k}", "none", k, RUN_CAP_USD[f"none_{k}"]) for k in NONE_MODELS]


def guard_denies(hookbin: Path, command: str) -> bool:
    """The bt-guard wrapper refuses `command` (exit 2), fed the PreToolUse JSON the CLI sends."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}
    run = subprocess.run([str(Path(hookbin) / CL.GUARD_WRAPPER)], input=json.dumps(event), capture_output=True,
                         text=True, timeout=60)
    return run.returncode == 2


def _common(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, model: str, mode: str,
            cwd: Path, version: str | None) -> dict[str, Any]:
    vs = TR.check_events(events, prompts, model, mode, cwd, version)
    init, res = CL.init_event(events) or {}, CL.result_event(events) or {}
    out = res.get("structured_output") if isinstance(res.get("structured_output"), dict) else None
    used = sorted(res.get("modelUsage") or {})
    n_think, chars = TR.thinking_chars(events)
    return {"vs": vs, "init": init, "res": res, "out": out, "used": used,
            "fallback": CL.model_fallback(events, res or None, model), "tokens": TR.first_prompt_tokens(events),
            "memory": [v.detail for v in vs if v.rule == "t_memory"], "thinking": (n_think, chars),
            "init_bad": [v.detail for v in vs if v.rule == "t_init"]}


def _detail(c: Mapping[str, Any]) -> dict[str, Any]:
    return {"init_tools": list(c["init"].get("tools") or []), "init_model": c["init"].get("model"),
            "model_usage": c["used"], "resolved": c["init"].get("model") if c["used"] == [c["init"].get("model")]
            else None, "fallback": c["fallback"], "first_prompt_tokens": c["tokens"], "memory_hits": c["memory"][:3],
            "thinking_blocks": c["thinking"][0], "thinking_chars": c["thinking"][1],
            "has_init": bool(c["init"]), "cli": c["init"].get("claude_code_version"),
            "errors": [v.as_dict() for v in c["vs"] if v.level == "error"][:5],
            "cost_usd": c["res"].get("total_cost_usd")}


def _no_memory(c: Mapping[str, Any], memory_empty: bool) -> str:
    ok = memory_empty and not c["memory"] and c["out"] is not None and c["tokens"] is not None \
        and c["tokens"] <= MAX_FIRST_PROMPT_TOKENS
    return "pass" if ok else "fail"


def bt_checks(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, thinking: bool,
              memory_empty: bool, offline_denied: Mapping[str, bool], model: str = CL.MODELS["opus"],
              cwd: Path = CL.AGENT_CWD, version: str | None = None) -> dict[str, Any]:
    """A's five checks of one mode-bt run (pure: events, the prompts record and the offline hook results in)."""
    c = _common(events, prompts, model, "bt", cwd, version)
    calls, results = TR.tool_calls(events), TR.tool_results(events)
    cmds = {" ".join(str(H.as_mapping(x.get("input")).get("command", "")).split()): x.get("id")
            for x in calls if x.get("name") == "Bash"}
    denied = {m: m in cmds and TR.is_denied(results.get(cmds[m])) for m in MUST_DENY}
    leaked = [v.detail for v in c["vs"] if v.rule == "t_tool"]
    offline = dict(offline_denied)
    return {"c1_init": "pass" if not c["init_bad"] and c["fallback"] is None else "fail",
            "c2_hook": "pass" if all(denied.values()) and not leaked and offline
                       and all(offline.get(x) for x in OFFLINE_DENY) else "fail",
            "c3_thinking": "skip" if not thinking else ("pass" if c["thinking"][1] > 0 else "fail"),
            "c4_no_memory": _no_memory(c, memory_empty),
            "c5_result": "pass" if CL.failure(0, c["res"] or None) is None else "fail",
            "detail": {**_detail(c), "denied": denied, "offline_denied": offline, "leaked": leaked[:3]}}


def none_checks(events: Sequence[Mapping[str, Any]], prompts: Mapping[str, Any] | None, model: str,
                memory_empty: bool, schema: Mapping[str, Any] = NONE_SCHEMA, cwd: Path = CL.AGENT_CWD,
                version: str | None = None) -> dict[str, Any]:
    """The qset probe's five checks of one mode-none run."""
    c = _common(events, prompts, model, "none", cwd, version)
    calls = [x.get("name") for x in TR.tool_calls(events)]
    out, req = c["out"], schema.get("required", [])
    typed = {k: int if p.get("type") == "integer" else str for k, p in schema["properties"].items()}
    shaped = out is not None and all(k in out for k in req) and all(isinstance(out[k], t) for k, t in typed.items()
                                                                  if k in out)
    return {"c1_init": "pass" if not c["init_bad"] else "fail",
            "c2_structured_output": "pass" if TR.ANSWER_TOOL in (c["init"].get("tools") or []) and shaped
                                    and set(calls) <= {TR.ANSWER_TOOL} else "fail",
            "c3_model": "pass" if c["fallback"] is None and c["used"] == [model] and c["init"].get("model") == model
                        else "fail",
            "c4_no_memory": _no_memory(c, memory_empty),
            "c5_result": "pass" if CL.failure(0, c["res"] or None) is None else "fail",
            "detail": {**_detail(c), "tool_calls": calls}}


def _agg(runs: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, str]:
    return {k: ("fail" if not runs or any(r["checks"].get(k) == "fail" for r in runs) else
                "skip" if all(r["checks"].get(k) == "skip" for r in runs) else "pass") for k in keys}


def verdict(runs: Sequence[Mapping[str, Any]], version: str, cli_sha256: str, cli_path: str, thinking: bool,
            found: str | None) -> dict[str, Any]:
    bt = [r for r in runs if r["mode"] == "bt"]
    none = [r for r in runs if r["mode"] == "none"]
    agg = {"bt": _agg(bt, BT_KEYS), "none": _agg(none, NONE_KEYS)}
    others_ok = all(v == "pass" for k, v in agg["bt"].items() if k != "c3_thinking") and \
        all(v == "pass" for v in agg["none"].values()) and {r["model_key"] for r in none} == set(NONE_MODELS)
    ok = others_ok and agg["bt"]["c3_thinking"] in ("pass", "skip")
    rejected = thinking and bool(runs) and all(not r["checks"]["detail"].get("has_init")
                                               and r["checks"].get("c5_result") == "fail" for r in runs)
    action = ("pin" if ok else "drop_thinking_display" if others_ok and agg["bt"]["c3_thinking"] == "fail"
              else "rerun_no_thinking_display" if rejected else "stop")
    resolved = {r["model_key"]: r["checks"]["detail"].get("resolved") for r in runs}
    models = {k: v for k, v in resolved.items() if v}
    consistent = all(r["checks"]["detail"].get("resolved") == models.get(r["model_key"]) for r in runs)
    combos = combos_of(runs)
    pin = CL.CliPin(version, cli_sha256, cli_path, thinking, models, combos) if ok and consistent else None
    return {"claude_version_expected": version, "claude_version_found": found, "cli_sha256": cli_sha256,
            "cli_path": cli_path, "thinking_display": thinking, "reps": len(runs), "checks": agg,
            "combos": [list(c) for c in combos],
            "pass": ok and consistent, "action": action if consistent else "stop", "models": models,
            "pin": pin.as_dict() if pin else None,
            "cost_usd": round(sum(r["checks"]["detail"].get("cost_usd") or 0 for r in runs), 6), "runs": list(runs),
            "utc": now()}


def combos_of(runs: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
    """The (tools mode, model key) pairs these runs probed, in PROBED_COMBOS order."""
    ran = {(r["mode"], r["model_key"]) for r in runs}
    return tuple(c for c in CL.PROBED_COMBOS if c in ran)


def next_root(out_root: Path) -> Path:
    base = L.Ledger(out_root).base("probe")
    taken = [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()] if base.is_dir() else []
    return base / str(1 + max(taken, default=0))


def probe(version: str, thinking: bool = True, reps: int = REPS_BT, out_root: Path = GC.OUT_ROOT,
          versions_dir: Path = CL.CLI_VERSIONS_DIR, cwd: Path = CL.AGENT_CWD, home: Path | None = None,
          timeout_s: int = PROBE_TIMEOUT_S, cli_sha256: str | None = None) -> dict[str, Any]:
    """One invocation (BudgetRefused before anything starts when its plan does not fit the probe allowance)."""
    H.check_guard()
    check_prompts()
    ledger, proot, runs_plan = L.Ledger(out_root), next_root(Path(out_root)), plan(reps)
    ledger.check(round(sum(p[3] for p in runs_plan), 6), "probe", proot)
    exe, sha = CL.copy_cli(version, versions_dir, Path(out_root) / "cli", cli_sha256)
    pin = CL.CliPin(version, sha, str(exe), thinking, dict(CL.MODELS))
    CL.write_wrappers(proot, "bt")
    CL.pin_cli(proot, pin)
    meta = {"root": ledger.rel(proot), "cli_sha_basis": CL.sha_basis(version), "cli_source": CL.cli_source(exe),
            "env_keys": sorted(CL.child_env(proot, "bt", cwd))}
    try:
        found = CL.claude_version(proot)
    except CL.CliUnavailable as err:
        return {**verdict([], version, sha, str(exe), thinking, None), **meta, "error": str(err)}
    if found.split()[:1] != [version]:
        return {**verdict([], version, sha, str(exe), thinking, found), **meta,
                "error": f"claude --version is {found!r}; pinned {version}"}
    offline = {c: guard_denies(proot / "hookbin", c) for c in OFFLINE_DENY}
    runs = []
    for run_id, mode, key, cap in runs_plan:
        model = CL.MODELS[key]
        system, user, schema = (PROBE_SYSTEM, PROBE_USER, PROBE_SCHEMA) if mode == "bt" else \
            (NONE_SYSTEM, NONE_USER, NONE_SCHEMA)
        try:
            res = CL.run_reserved("probe", proot, run_id, system, user, schema, cap, model, pin, user_scope="prompt",
                                  out_root=out_root, tools_mode=mode, cwd=cwd, timeout_s=timeout_s, home=home,
                                  extra_record={"kind": "probe", "model_key": key})
        except HoError as err:                      # refused before starting (budget, pin, cwd): nothing ran
            doc = verdict(runs, version, sha, str(exe), thinking, found)
            return {**doc, **meta, "pass": False, "action": "stop", "pin": None,
                    "error": f"{run_id}: {type(err).__name__}: {err}"}
        events = CL.read_events(res.transcript)
        prompts = read_json(proot / "prompts" / f"{run_id}.json")
        empty = not any(CL.memory_dir(cwd, home).glob("*"))
        checks = bt_checks(events, prompts, thinking, empty, offline, model, cwd, version) if mode == "bt" else \
            none_checks(events, prompts, model, empty, schema, cwd, version)
        runs.append({"run_id": run_id, "mode": mode, "model_key": key, "cap_usd": cap, "error": res.error,
                     "limit": res.limit, "checks": checks})
    return {**verdict(runs, version, sha, str(exe), thinking, found), **meta}


def write_verdict(doc: Mapping[str, Any], out_root: Path = GC.OUT_ROOT) -> Path:
    n = Path(doc.get("root") or "probe/0").name
    return write_json(L.Ledger(out_root).base("probe") / f"verdict_{n}.json", doc)


def pin_from(verdict_path: Path, drop_thinking: bool = False, after_rejected: Path | None = None,
             pin_path: Path = CL.PIN_PATH) -> Path:
    """The pin file from a verdict: action pin (thinking_display false only after a recorded rejection of the flag),
    or drop_thinking_display when explicitly accepted; the CLI copy is rechecked first."""
    doc, extra, disclosure = read_json(verdict_path), {}, ""
    version, models = doc.get("claude_version_expected"), dict(doc.get("models") or {})
    if set(models) != set(NONE_MODELS) or any(models[k] != CL.MODELS[k] for k in models):
        raise HoError(f"verdict models {models} are not the expected {CL.MODELS}")
    combos = tuple(tuple(c) for c in doc.get("combos") or [])
    if set(combos) != set(CL.PROBED_COMBOS):
        raise HoError(f"verdict combos {doc.get('combos')} are not every probed pair {CL.PROBED_COMBOS}")
    base = dict(claude_version=version, cli_sha256=doc.get("cli_sha256"), cli_path=doc.get("cli_path"), models=models,
                combos=CL.PROBED_COMBOS)
    if doc.get("action") == "pin" and doc.get("thinking_display"):
        pin = CL.CliPin(**base, thinking_display=True)
    elif doc.get("action") == "pin":
        first = read_json(after_rejected) if after_rejected else {}
        if not (first.get("action") == "rerun_no_thinking_display" and first.get("thinking_display")
                and first.get("claude_version_expected") == version):
            raise HoError("a pin without --thinking-display needs --after-rejected <verdict with action "
                          "rerun_no_thinking_display> (prereg §8.1-2, A's sequence)")
        pin = CL.CliPin(**base, thinking_display=False)
        extra = {"after_rejected": Path(after_rejected).name, "after_rejected_sha256": H.sha256_file(after_rejected)}
        disclosure = f"CLI {version} 不接受 --thinking-display，依 A 的程序改不帶此旗標重測一次通過；transcript 沒有 thinking 摘要"
    elif doc.get("action") == "drop_thinking_display" and drop_thinking:
        pin = CL.CliPin(**base, thinking_display=False)
        disclosure = "transcript 沒有 thinking 摘要（probe 只有 c3_thinking 不過）"
    else:
        raise HoError(f"verdict action {doc.get('action')!r}: no pin (fix the infrastructure first, or stop)")
    CL.check_cli(pin)
    return CL.write_pin(pin, pin_path, verdict=Path(verdict_path).name, verdict_sha256=H.sha256_file(verdict_path),
                        disclosure=disclosure, cli_sha_basis=doc.get("cli_sha_basis"),
                        cli_source=doc.get("cli_source"), env_keys=doc.get("env_keys"), **extra)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CLI probe 與釘版（prereg §3.1、§8.1-2；主程序執行，≤1 USD）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--version", required=True)
    p.add_argument("--cli-sha256", default=None, help="required for a version without a known sha256")
    p.add_argument("--no-thinking-display", dest="thinking", action="store_false")
    p.add_argument("--reps", type=int, default=REPS_BT)
    p = sub.add_parser("pin")
    p.add_argument("--verdict", type=Path, required=True)
    p.add_argument("--drop-thinking-display", action="store_true")
    p.add_argument("--after-rejected", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "pin":
        print(json.dumps({"pin": str(pin_from(a.verdict, a.drop_thinking_display, a.after_rejected))},
                         ensure_ascii=False))
        return 0
    if bad := K0.k0_problems():
        raise HoError(f"K0 first (prereg §8.1-1: K0 before any USD): {bad[:3]}")
    if not 1 <= a.reps <= REPS_BT:
        raise HoError(f"--reps must be 1..{REPS_BT} (the caps are sized for {REPS_BT})")
    doc = probe(a.version, a.thinking, a.reps, cli_sha256=a.cli_sha256)
    path = write_verdict(doc)
    L.Ledger().write_snapshot()
    print(json.dumps({k: doc[k] for k in ("action", "pass", "checks", "claude_version_found", "thinking_display",
                                          "cost_usd", "models")} | {"verdict": str(path)}, ensure_ascii=False))
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
