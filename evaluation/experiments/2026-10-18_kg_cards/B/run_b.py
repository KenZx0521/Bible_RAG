"""Experiment B stage-0 runner (prereg §3). Data: store reports/kg_cards_20261018/B/.

usage: python3 -B run_b.py dry-run                  # CPU only: items, K0 files, appendix numbers
       python3 -B run_b.py arms  --smoke 3 [--num-ctx N]   # Ollama; then /api/ps -> B/smoke/ps.json
       python3 -B run_b.py ps                       # Ollama /api/ps only -> B/smoke/ps.json
       python3 -B run_b.py seeds [--num-ctx N]
       python3 -B run_b.py arms  [--num-ctx N] [--build-only]
       python3 -B run_b.py score [--ctx-len N]      # default: context_length from B/smoke/ps.json
       python3 -B run_b.py analyze
seeds/arms/ps call Ollama (only in Kay's window; cards_common.run_jobs, reruns skip done jobs).
--smoke N runs every rep-1 job of the N items with the longest prompts into B/smoke/ (dry-run seeds
if seeds are absent; never scored), saves /api/ps and the truncation count. A smoke with a --num-ctx other
than the one recorded in B/smoke/smoke_ctx.json first moves the old smoke files to B/smoke/superseded/
(so every smoke call is made again at the new num_ctx); /api/ps is saved only if the model's
context_length equals --num-ctx. After a smoke, seeds and arms refuse a --num-ctx other than the smoke's. Order: dry-run -> K0 by hand -> arms --smoke 3 (rerun
with one --num-ctx if truncated) -> B/k0_result.json -> seeds -> arms -> score -> analyze.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

import b_arms as A
import b_lib as L
from b_lib import cc

ITEMS, DRYRUN = L.OUT / "items.json", L.OUT / "dryrun.json"
SEEDS, ARMS = L.OUT / "seeds.jsonl", L.OUT / "arms.jsonl"
EXCLUSIONS = L.OUT / "gold_exclusions.json"
SMOKE = L.OUT / "smoke"
PS = SMOKE / "ps.json"
SMOKE_CTX = SMOKE / "smoke_ctx.json"


def sha_file(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_items() -> list[dict]:
    want = L.load_json(DRYRUN)["sha256"]["items.json"]
    if sha_file(ITEMS) != want:
        raise SystemExit("items.json differs from the dry-run freeze; rerun dry-run before any seed")
    return L.load_json(ITEMS)["items"]


def options(args) -> dict | None:
    return dict(cc.OPTIONS, num_ctx=args.num_ctx) if args.num_ctx else None


def ps_ctx(ps: dict) -> int | None:
    """context_length of the generation model in an /api/ps response (None: not loaded)."""
    for m in ps.get("models", []):
        if cc.MODEL in (m.get("name"), m.get("model")) and m.get("context_length"):
            return int(m["context_length"])
    return None


def save_ps(num_ctx: int | None) -> dict:
    """Write B/smoke/ps.json only if the loaded model's context_length is the one asked for."""
    ps = cc.api_ps()
    got = ps_ctx(ps)
    if got is None or (num_ctx is not None and got != num_ctx):
        raise SystemExit(f"沒有寫 smoke/ps.json：/api/ps 裡 {cc.MODEL} 的 context_length 是 {got}，"
                         f"--num-ctx 是 {num_ctx}（模型已卸載，或仍以舊 num_ctx 載入）。"
                         f"把 B/smoke/ 下的檔案移走後，用同一個 --num-ctx 重跑 smoke。")
    rec = dict(taken_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), num_ctx_requested=num_ctx, ps=ps)
    cc.write_json(PS, rec)
    return rec


def smoke_guard(num_ctx: int | None) -> None:
    """Smoke results are valid only for the num_ctx they ran with (prereg §1: set num_ctx, rerun the smoke).
    If this smoke's --num-ctx differs from the recorded one (or none is recorded), move the old smoke
    files to smoke/superseded/<n>_ctx<old>/ so run_jobs makes every smoke call again."""
    old_files = [f for f in sorted(SMOKE.glob("*")) if f.is_file()] if SMOKE.exists() else []
    old = L.load_json(SMOKE_CTX)["num_ctx"] if SMOKE_CTX.exists() else "unknown"
    if old_files and old != num_ctx:
        sup = SMOKE / "superseded"
        n = len(list(sup.glob("*"))) + 1 if sup.exists() else 1
        dest = sup / f"{n:02d}_ctx{old}"
        dest.mkdir(parents=True)
        for f in old_files:
            f.rename(dest / f.name)
        print(f"smoke --num-ctx {num_ctx} 與上次 {old} 不同：舊 smoke 檔已移到 {dest}，全部重跑")
    cc.write_json(SMOKE_CTX, dict(num_ctx=num_ctx))


def check_num_ctx(args) -> None:
    """After a smoke, the formal run uses the smoke's num_ctx (prereg §1: one num_ctx for all arms)."""
    if not PS.exists():
        return
    rec = L.load_json(PS)
    if rec["num_ctx_requested"] != args.num_ctx:
        raise SystemExit(f"--num-ctx {args.num_ctx} differs from the smoke's "
                         f"{rec['num_ctx_requested']} (B/smoke/ps.json); rerun the smoke or match it")
    if args.num_ctx is not None and ps_ctx(rec["ps"]) != args.num_ctx:
        raise SystemExit(f"B/smoke/ps.json context_length {ps_ctx(rec['ps'])} != --num-ctx {args.num_ctx}; rerun the smoke")


def seed_contents(items: list[dict], simulate_missing: bool) -> dict:
    done = cc.done_jobs(SEEDS)
    out = {}
    for it in items:
        rec = done.get(A.seed_job(it)["job_id"])
        if rec is None and not simulate_missing:
            raise SystemExit(f"seed of {it['id']} missing; run seeds first")
        out[it["id"]] = rec["content"] if rec else A.simulated_seed(it)
    return out


def cmd_dry_run(args) -> None:
    import b_dryrun
    b_dryrun.run()


def cmd_seeds(args) -> None:
    items = load_items()
    jobs = [A.seed_job(it) for it in items]
    out = SEEDS
    if args.smoke:
        jobs, out = jobs[:args.smoke], SMOKE / "seeds.jsonl"
        smoke_guard(args.num_ctx)
    else:
        check_num_ctx(args)
    cc.run_jobs(jobs, out, options=options(args))


def cmd_ps(args) -> None:
    import score_b
    rec = save_ps(args.num_ctx)
    print(json.dumps(dict(ctx_len=score_b.ctx_from_ps(), num_ctx_requested=rec["num_ctx_requested"])))


def longest(items: list[dict], cards: dict, cap: int, n: int) -> list[dict]:
    def size(it):
        jobs = A.arm_jobs([it], {it["id"]: cards[it["id"]]}, cap)
        return max(len(j.get("user") or j["user_template"]) for j in jobs)
    return sorted(items, key=size, reverse=True)[:n]


def cmd_arms(args) -> None:
    items = load_items()
    seeds = seed_contents(items, simulate_missing=bool(args.smoke))
    cards = {it["id"]: A.cards(it, seeds[it["id"]]) for it in items}
    k0_cap = L.load_json(DRYRUN)["slot_cap_chars_k0"]
    cap = A.slot_cap(cards, k0_cap)
    caps = dict(slot_cap_chars=cap, slot_cap_k0=k0_cap, longest_G_card=A.longest_card(cards))
    if args.smoke:
        import score_b
        pick = longest(items, cards, cap, args.smoke)
        jobs = [j for j in A.arm_jobs(pick, cards, cap) if j["rep"] == 1]
        smoke_guard(args.num_ctx)
        cc.write_json(SMOKE / "arm_jobs.json", dict(caps, num_ctx=args.num_ctx, jobs=jobs))
        cc.run_jobs(jobs, SMOKE / "arms.jsonl", options=options(args))
        save_ps(args.num_ctx)
        print(json.dumps(score_b.smoke_report(None), ensure_ascii=False))
        return
    check_num_ctx(args)
    if not args.build_only and not PS.exists():
        raise SystemExit("no smoke yet (B/smoke/ps.json): run `arms --smoke 3` first (prereg §1 共同 K0)")
    jobs = A.arm_jobs(items, cards, cap)
    frozen = L.OUT / "arm_jobs.json"
    if ARMS.exists() and frozen.exists() and L.load_json(frozen)["jobs"] != jobs:
        raise SystemExit("arms.jsonl exists and the rebuilt jobs differ from arm_jobs.json; not mixing runs")
    cc.write_json(L.OUT / "cards.json", dict(caps, cards=cards))
    cc.write_json(frozen, dict(caps, num_ctx=args.num_ctx, n_jobs=len(jobs), jobs=jobs))
    print(json.dumps(dict(caps, n_jobs=len(jobs),
                          n_G_fired=sum(c["G"]["status"] == "fire" for c in cards.values()),
                          n_GO_fired=sum(c["GO"]["status"] == "fire" for c in cards.values())), ensure_ascii=False))
    if not args.build_only:
        cc.run_jobs(jobs, ARMS, options=options(args))


def cmd_score(args) -> None:
    import score_b
    s = score_b.run(args.ctx_len)
    print(json.dumps(dict(n_items=s["n_items"], n_gen_jobs=s["n_gen_jobs"], n_missing=s["n_missing"],
                          ctx_len=s["ctx_len"], ctx_source=s["ctx_source"])))


def cmd_analyze(args) -> None:
    import analyze_b
    rep = analyze_b.run()
    print(rep["verdict"], rep["verdict_detail"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("dry-run", "seeds", "arms", "ps", "score", "analyze"))
    ap.add_argument("--num-ctx", type=int, default=None)
    ap.add_argument("--smoke", type=int, default=0)
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--ctx-len", type=int, default=None)
    args = ap.parse_args(argv)
    {"dry-run": cmd_dry_run, "seeds": cmd_seeds, "arms": cmd_arms, "ps": cmd_ps, "score": cmd_score,
     "analyze": cmd_analyze}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
