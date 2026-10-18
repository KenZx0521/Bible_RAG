"""Confirmation-set driver (confirm_A.md §4–§6). Host python3 -B; only collect, seeds and arms call the
backend / Ollama, and only in an authorised Ollama window.

usage: python3 -B run_c.py k0-1b                         # K0_1b from Kay's ho/kay/k0_1b.json (§7) into k0_status.json
       python3 -B run_c.py collect                       # §4 contexts.json (backend + gemma routing)
       python3 -B run_c.py prepare                       # items.json, k0_status.json, F3 manifest (CPU)
       python3 -B run_c.py dry-run                       # synthetic set: every prompt built, sha checked
       python3 -B run_c.py seeds  [--num-ctx 131072]
       python3 -B run_c.py arms   [--num-ctx 131072] [--canary-fixed NOTE]
       python3 -B run_c.py canary | trunc | score | analyze   # CPU
       any of prepare / seeds / arms / score / analyze: [--code-change NOTE]
All outputs go to store A_confirm/ (formal only, no smoke). Guards (stage-0 A.6 plus): frozen sha of
questions_frozen.json / contexts.json / items.json against inputs_manifest.json, the stage-0 layers,
cards_common, prompts and A0 code (c_common.frozen_mismatches), the four prompt sha values and every
job's system prompt, num_ctx 131072 only, k0_status.json (K0_1, K0_1b, K0_2, K0_3) all pass; a rerun
whose run_meta options, prompts or frozen sha differ is refused; arms needs every seed job done.
confirm/*.py must equal inputs_manifest.json code_confirm (set at prepare): a change is refused unless
--code-change NOTE, which logs {t, files, note} in the manifest's code_changes (listed in the report).
Canary (instead of a smoke): after all seeds and the first 30 arm calls, any error line or missing
call stops the run. Truncation is counted, not a stop: num_ctx is C0 and num_predict is frozen, so a
truncated call is a format failure (a truncated seed = no seeds, the G arms abstain; prereg §1).
Only counts and job ids are printed, never an answer.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import guards_c as G
from c_common import (ARMS_JOBS, ARMS_META, CANARY_ARM_CALLS, CONTEXTS, GEN_ARMS, GEN_SEED, HERE, ITEMS, K0_STATUS,
                      KAY_K0_1B, LAYER_AUTO, LAYER_REF, MANIFEST, NUM_CTX, OPTIONS, OUT, QUESTIONS_FROZEN, SEGMENTS,
                      ST0_K0, ac, cc, jsonl, read_json, sha256_file)

CANARY = OUT / "canary.json"


# ---------------------------------------------------------------- guards
def check_frozen(manifest: Path = MANIFEST, files=G.FROZEN_FILES) -> dict:
    bad = G.frozen_problems(manifest, files)
    if bad:
        raise SystemExit(f"frozen inputs do not match: {bad}")
    return {Path(p).name: sha256_file(p) for p in files}


def k0_gate(k0_path: Path = K0_STATUS, kay_path: Path = KAY_K0_1B) -> None:
    bad = G.k0_problems(k0_path, kay_path)
    if bad:
        raise SystemExit(f"K0 gate: {bad}")
    stop = G.k0_1b_stop(read_json(k0_path))
    if stop:
        raise SystemExit(stop)


def check_code(note: str | None, manifest: Path = MANIFEST, here: Path = HERE) -> list[str]:
    """Refuse changed confirm/*.py unless a --code-change note is given; then log it and re-pin."""
    if not (Path(manifest).is_file() and "code_confirm" in read_json(manifest)):
        raise SystemExit(f"{Path(manifest).name} has no code_confirm: run prepare first")
    bad = G.code_problems(manifest, here)
    if not bad:
        return []
    if not note:
        raise SystemExit(f"confirm/ code changed since prepare: {bad}; infra fixes only (§0), "
                         "rerun with --code-change NOTE")
    man = read_json(manifest)
    log = man.get("code_changes", []) + [{"t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                          "files": bad, "note": note}]
    cc.write_json(manifest, {**man, "code_confirm": G.code_sha(here), "code_changes": log})
    return bad


def options(num_ctx: int | None) -> dict:
    if num_ctx is not None and num_ctx != NUM_CTX:
        raise SystemExit(f"--num-ctx {num_ctx}: confirm_A.md §0 fixes num_ctx {NUM_CTX}")
    return dict(OPTIONS)


def check_prompts(seed_jobs=(), arm_jobs=()) -> None:
    bad = G.prompt_problems(seed_jobs, arm_jobs)
    if bad:
        raise SystemExit(f"prompt check: {bad[:5]}{' …' if len(bad) > 5 else ''}")


def guard(path: Path, opts: dict, sha: str, tag: str, frozen: dict) -> dict:
    """Refuse to resume into outputs made with other options, prompts or frozen inputs; returns run_meta."""
    meta_p = path.parent / f"run_meta_{tag}.json"
    if meta_p.exists():
        old = read_json(meta_p)
        if old["options"] != opts or old["prompts_sha256"] != sha or old.get("frozen") != frozen:
            raise SystemExit(f"{meta_p}: options, prompts or frozen inputs differ from the earlier run")
        keep = {k: v for k, v in old.items() if k not in ("finished", "n_done", "n_jobs")}
        return {**keep, "resumed": old.get("resumed", []) + [time.strftime("%Y-%m-%dT%H:%M:%S")]}
    if path.exists():
        raise SystemExit(f"{path} exists without {meta_p.name}")
    return {"options": opts, "prompts_sha256": sha, "frozen": frozen, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}


def run(jobs: list[dict], path: Path, opts: dict, meta: dict, tag: str) -> dict:
    meta_p = path.parent / f"run_meta_{tag}.json"
    cc.write_json(meta_p, {**meta, "n_jobs": len(jobs)})
    done = cc.run_jobs(jobs, path, options=opts)
    cc.write_json(meta_p, {**meta, "n_jobs": len(jobs), "n_done": len(done),
                           "finished": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return done


def items() -> list[dict]:
    return read_json(ITEMS)["items"]


# ---------------------------------------------------------------- CPU steps
def k0_1b(_args) -> None:
    k0 = read_json(K0_STATUS) if K0_STATUS.exists() else {}
    try:
        rec = G.k0_1b_from_kay(KAY_K0_1B)
    except ValueError as err:
        raise SystemExit(str(err))
    cc.write_json(K0_STATUS, {**k0, "K0_1b": rec})
    print("K0_1b", rec)


def k0_status(st0_k0: Path = ST0_K0, out: Path = K0_STATUS, kay_path: Path = KAY_K0_1B) -> dict:
    """K0_1, K0_2, K0_3 cite stage-0 (same layer sha, num_ctx 131072); K0_1b from Kay's record when it exists."""
    st0 = read_json(st0_k0)
    old = read_json(out) if out.exists() else {}
    doc = {**old, **{k: {**st0[k], "src": f"stage-0 A/k0_status.json {k} (same layer sha)"} for k in G.K0_PASS}}
    try:
        doc["K0_1b"] = G.k0_1b_from_kay(kay_path)
    except ValueError as err:
        doc["K0_1b"] = {"pass": None, "pending": f"Kay 抽查頁 20 列（§7）：{err}"}
    cc.write_json(out, doc)
    return doc


def prepare(args) -> None:
    import collect_ctx
    import items_c
    from regnal import load_ref
    if MANIFEST.is_file() and "code_confirm" in read_json(MANIFEST):
        check_code(args.code_change)
    if G.frozen_problems(MANIFEST, (QUESTIONS_FROZEN,)):
        raise SystemExit(f"F2 check: {G.frozen_problems(MANIFEST, (QUESTIONS_FROZEN,))}")
    if not CONTEXTS.is_file():
        raise SystemExit(f"{CONTEXTS} missing: run collect first")
    man = read_json(MANIFEST)
    frozen = dict(man.get("frozen") or {})
    if frozen.get(CONTEXTS.name, sha256_file(CONTEXTS)) != sha256_file(CONTEXTS):
        raise SystemExit(f"{CONTEXTS} differs from its frozen sha")
    qs, _ = collect_ctx.frozen_questions()
    doc = items_c.build_items(qs, items_c.contexts_of(read_json(CONTEXTS)), read_json(SEGMENTS)["segments"],
                              load_ref(LAYER_REF))
    doc["inputs_sha256"] = {n: sha256_file(OUT / n) for n in (QUESTIONS_FROZEN.name, CONTEXTS.name, SEGMENTS.name)}
    if ITEMS.exists() and ITEMS.name in frozen:
        old = read_json(ITEMS)
        if old != doc or sha256_file(ITEMS) != frozen[ITEMS.name]:
            raise SystemExit(f"{ITEMS} is frozen and a rebuild differs; not overwritten")
    else:
        cc.write_json(ITEMS, doc)
    k0_status()
    frozen.update({CONTEXTS.name: sha256_file(CONTEXTS), ITEMS.name: sha256_file(ITEMS)})
    code = {p.name: sha256_file(p) for p in sorted(HERE.glob("*.py"))}
    cc.write_json(MANIFEST, {**man, "frozen": frozen, "code_confirm": code,
                             "prepared": time.strftime("%Y-%m-%dT%H:%M:%S")})
    print("items", doc["n_items"], "units", doc["n_units"], "manifest", MANIFEST)


def collect(_args) -> None:
    import collect_ctx
    collect_ctx.main([])


def dry_run(_args) -> None:
    from dry_run_c import dry_run as go
    go()


# ---------------------------------------------------------------- Ollama steps
def seeds(args) -> None:
    from seeds_a import seed_jobs
    check_code(args.code_change)
    frozen = check_frozen()
    k0_gate()
    opts, jobs = options(args.num_ctx), seed_jobs(items())
    check_prompts(seed_jobs=jobs)
    meta = guard(GEN_SEED, opts, ac.prompts_sha256(jobs), "seeds", frozen)
    run(jobs, GEN_SEED, opts, meta, "seeds")


def error_lines(path: Path, ids=None) -> int:
    if not path.exists():
        return 0
    return sum(r.get("type") == "error" and (ids is None or r.get("job_id") in ids) for r in jsonl(path))


def canary_ids(its: list[dict], jobs: list[dict]) -> tuple[set, set]:
    return {f"A|{it['id']}|seed|1" for it in its}, {j["job_id"] for j in jobs[:CANARY_ARM_CALLS]}


def canary_errors(d: Path, its: list[dict], jobs: list[dict]) -> dict:
    """Error lines of the canary jobs so far (ignored by a --canary-fixed rerun)."""
    seed_ids, arm_ids = canary_ids(its, jobs)
    return {GEN_SEED.name: error_lines(d / GEN_SEED.name, seed_ids), GEN_ARMS.name: error_lines(d / GEN_ARMS.name, arm_ids)}


def canary_status(d: Path, its: list[dict], jobs: list[dict], num_ctx: int, ignore: dict | None = None) -> dict:
    """Counts only: seeds (all) and the first CANARY_ARM_CALLS arm jobs must be done and error-free;
    truncated calls are listed but do not fail the canary (format failures, prereg §1)."""
    from score_a import truncated
    ignore = ignore or {}
    seed_ids, arm_ids = canary_ids(its, jobs)
    sd, ad = cc.done_jobs(d / GEN_SEED.name), cc.done_jobs(d / GEN_ARMS.name)
    st = {"n_seed_jobs": len(seed_ids), "n_canary_arm_jobs": len(arm_ids),
          "seed_missing": sorted(seed_ids - set(sd)), "arm_missing": sorted(arm_ids - set(ad)),
          "seed_truncated": sorted(i for i in seed_ids & set(sd) if truncated(sd[i], num_ctx)),
          "arm_truncated": sorted(i for i in arm_ids & set(ad) if truncated(ad[i], num_ctx)),
          "seed_errors": error_lines(d / GEN_SEED.name, seed_ids) - ignore.get(GEN_SEED.name, 0),
          "arm_errors": error_lines(d / GEN_ARMS.name, arm_ids) - ignore.get(GEN_ARMS.name, 0)}
    st["pass"] = not any(st[k] for k in ("seed_missing", "arm_missing", "seed_errors", "arm_errors"))
    return st


def canary_passed(p: Path = CANARY) -> bool:
    return p.exists() and read_json(p).get("pass") is True


def record_canary(st: dict, note: str | None, ignore: dict | None = None, p: Path = CANARY) -> None:
    old = read_json(p) if p.exists() else {}
    hist = old.get("history", []) + [{**st, "note": note, "ignore": ignore or {}, "t": time.strftime("%Y-%m-%dT%H:%M:%S")}]
    cc.write_json(p, {**st, "note": note, "ignore": ignore or {}, "history": hist})


def recorded_ignore(p: Path = CANARY) -> dict:
    """Error-line counts a --canary-fixed rerun set aside (the latest record; cumulative)."""
    return (read_json(p).get("ignore") or {}) if p.exists() else {}


def arm_build(opts: dict) -> tuple[list[dict], list[dict], dict]:
    from arms_c import build_arms
    from regnal import load_auto, load_ref
    from run_a import seed_texts
    its = items()
    text, trunc_ids = seed_texts(OUT, its, opts)
    jobs, meta = build_arms(its, text, load_auto(LAYER_AUTO), load_ref(LAYER_REF))
    for i in trunc_ids:
        meta[i]["seed_truncated"] = True
    return its, jobs, meta


def arms(args) -> None:
    check_code(args.code_change)
    frozen = check_frozen()
    k0_gate()
    opts = options(args.num_ctx)
    its, jobs, meta = arm_build(opts)
    check_prompts(arm_jobs=jobs)
    run_meta = guard(GEN_ARMS, opts, ac.prompts_sha256(jobs), "arms", frozen)
    cc.write_json(ARMS_JOBS, jobs)
    cc.write_json(ARMS_META, meta)
    if not canary_passed():
        ignore = canary_errors(OUT, its, jobs) if args.canary_fixed else {}
        cc.write_json(OUT / "run_meta_arms.json", {**run_meta, "n_jobs": len(jobs), "canary_phase": True})
        cc.run_jobs(jobs[:CANARY_ARM_CALLS], GEN_ARMS, options=opts)
        st = canary_status(OUT, its, jobs, opts["num_ctx"], ignore)
        record_canary(st, args.canary_fixed, ignore)
        if not st["pass"]:
            raise SystemExit(f"canary 未過，先修基礎設施（不看答案）：{ {k: v for k, v in st.items() if v} }")
        print("canary passed:", st["n_seed_jobs"], "seeds,", st["n_canary_arm_jobs"], "arm calls")
    run(jobs, GEN_ARMS, opts, run_meta, "arms")


def canary(_args) -> None:
    its = items()
    jobs = read_json(ARMS_JOBS) if ARMS_JOBS.exists() else []
    st = canary_status(OUT, its, jobs, NUM_CTX, recorded_ignore())
    print({k: v for k, v in st.items() if k != "pass" and v}, "pass", st["pass"])


def trunc(_args) -> None:
    from score_a import trunc_report
    rep = trunc_report(OUT, NUM_CTX)
    cc.write_json(OUT / "trunc_report.json", rep)
    print(rep)


def score(args) -> None:
    from score_c import score_all
    check_code(args.code_change)
    doc = score_all()
    print("scored", doc["n_records"], "records; missing", len(doc["missing_jobs"]), "; seeds", doc["seeds"])


def analyze(args) -> None:
    from analyze_c import analyze as go
    check_code(args.code_change)
    rep = go()
    print(rep["verdict"]["result"], "|", rep["verdict"]["wording"])


CMDS = {"k0-1b": k0_1b, "collect": collect, "prepare": prepare, "dry-run": dry_run, "seeds": seeds, "arms": arms,
        "canary": canary, "trunc": trunc, "score": score, "analyze": analyze}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="實驗 A 確認集執行（confirm_A.md §4–§6）")
    ap.add_argument("cmd", choices=list(CMDS))
    ap.add_argument("--num-ctx", type=int, default=None, help=f"只接受 {NUM_CTX}")
    ap.add_argument("--canary-fixed", default=None, help="arms：修過基礎設施後重跑 canary，寫明修了什麼")
    ap.add_argument("--code-change", default=None, help="prepare 之後改過 confirm/*.py（只限基礎設施）：寫明修了什麼")
    args = ap.parse_args(argv)
    CMDS[args.cmd](args)


if __name__ == "__main__":
    main()
