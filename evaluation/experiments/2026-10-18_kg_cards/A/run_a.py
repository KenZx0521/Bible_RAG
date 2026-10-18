"""Experiment A stage-0 driver (prereg §2). Host python3 -B; only `seeds` and `arms` call Ollama.

usage: python3 -B run_a.py prepare                  # layers, items, K0 files, manifest (CPU)
       python3 -B run_a.py dry-run                  # gold seeds, builds every prompt, no Ollama
       python3 -B run_a.py seeds --num-ctx N [--items ID,..] [--out-dir DIR]
       python3 -B run_a.py arms  --num-ctx N [--items ID,..] [--out-dir DIR]
       python3 -B run_a.py trunc [--num-ctx N] [--out-dir DIR]   # K0-3 counts (CPU)
       python3 -B run_a.py score [--num-ctx N] [--out-dir DIR]
       python3 -B run_a.py analyze [--out-dir DIR]
Formal outputs: store A/gen_seed.jsonl, A/gen_arms.jsonl (+ arms_jobs.json, arms_meta.json, run_meta_*.json).
--items / --out-dir are for the 3-item smoke (prereg §1 K0); smoke outputs never go to A/ itself and
may omit --num-ctx (first smoke only). Guards: store A/k0_status.json must pass K0_1, K0_2 (smoke) and
also K0_3 with the same num_ctx (formal); a rerun into a directory whose run_meta options or prompts
differ is refused; arms needs every seed job done.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from a_common import (ARMS_JOBS, ARMS_META, GEN_ARMS, GEN_SEED, HERE, ITEMS, LAYER_AUTO, LAYER_REF, MANIFEST, OUT,
                      cc, prompts_sha256, read_json, sha256_file)

FROZEN = (LAYER_AUTO, LAYER_REF, ITEMS)
K0_STATUS = OUT / "k0_status.json"


def prepare(_args) -> None:
    import items_a
    import k0_prep
    import layer_check
    layer_check.main()
    items_a.main()
    k0_prep.main()
    cc.write_json(MANIFEST, {"frozen": {p.name: sha256_file(p) for p in FROZEN},
                             "code": {p.name: sha256_file(p) for p in sorted(HERE.glob("*.py"))},
                             "cards_common.py": sha256_file(HERE.parent / "cards_common.py")})
    print("manifest", MANIFEST)


def check_frozen() -> None:
    want = read_json(MANIFEST)["frozen"]
    for p in FROZEN:
        if sha256_file(p) != want[p.name]:
            raise SystemExit(f"{p} changed since prepare (manifest {MANIFEST})")


def selected(args) -> list[dict]:
    items = read_json(ITEMS)["items"]
    if args.items:
        keep = set(args.items.split(","))
        items = [it for it in items if it["id"] in keep]
    return items


def out_dir(args) -> Path:
    d = Path(args.out_dir) if args.out_dir else OUT
    if args.items and d.resolve() == OUT.resolve():
        raise SystemExit("--items (smoke) needs --out-dir other than A/")
    return d


def is_formal(d: Path) -> bool:
    return d.resolve() == OUT.resolve()


def k0_gate(formal: bool, num_ctx: int | None) -> None:
    """prereg §2 K0: no Ollama call before K0-1/K0-2 pass; the formal run also needs K0-3 at this num_ctx."""
    if not K0_STATUS.exists():
        raise SystemExit(f"{K0_STATUS} missing: record K0 before any Ollama call")
    k0 = read_json(K0_STATUS)
    need = ("K0_1", "K0_2", "K0_3") if formal else ("K0_1", "K0_2")
    bad = [k for k in need if (k0.get(k) or {}).get("pass") is not True]
    if bad:
        raise SystemExit(f"K0 not passed: {bad} ({K0_STATUS})")
    if formal and k0["K0_3"].get("num_ctx") != num_ctx:
        raise SystemExit(f"--num-ctx {num_ctx} is not the K0_3 smoke num_ctx {k0['K0_3'].get('num_ctx')}")


def options(args, d: Path) -> dict:
    if is_formal(d) and not args.num_ctx:
        raise SystemExit("formal run needs --num-ctx (prereg §1: explicit num_ctx after the smoke)")
    k0_gate(is_formal(d), args.num_ctx)
    return {**cc.OPTIONS, **({"num_ctx": args.num_ctx} if args.num_ctx else {})}


def guard(path: Path, opts: dict, sha: str, tag: str) -> dict:
    """Refuse to resume into outputs made with other options or prompts; returns the run_meta to keep."""
    meta_p = path.parent / f"run_meta_{tag}.json"
    if meta_p.exists():
        old = read_json(meta_p)
        if old["options"] != opts or old["prompts_sha256"] != sha:
            raise SystemExit(f"{meta_p}: options or prompts differ from the earlier run; use a new --out-dir")
        keep = {k: v for k, v in old.items() if k not in ("finished", "n_done", "n_jobs")}
        return {**keep, "resumed": old.get("resumed", []) + [time.strftime("%Y-%m-%dT%H:%M:%S")]}
    if path.exists():
        raise SystemExit(f"{path} exists without {meta_p.name}; use a new --out-dir")
    return {"options": opts, "prompts_sha256": sha, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}


def run(jobs: list[dict], path: Path, opts: dict, meta: dict, tag: str) -> None:
    meta_p = path.parent / f"run_meta_{tag}.json"
    cc.write_json(meta_p, {**meta, "n_jobs": len(jobs)})
    done = cc.run_jobs(jobs, path, options=opts)
    cc.write_json(meta_p, {**meta, "n_jobs": len(jobs), "n_done": len(done),
                           "finished": time.strftime("%Y-%m-%dT%H:%M:%S")})


def seeds(args) -> None:
    from seeds_a import seed_jobs
    check_frozen()
    d = out_dir(args)
    opts, jobs = options(args, d), seed_jobs(selected(args))
    meta = guard(d / GEN_SEED.name, opts, prompts_sha256(jobs), "seeds")
    run(jobs, d / GEN_SEED.name, opts, meta, "seeds")


def seed_texts(d: Path, items: list[dict], opts: dict) -> tuple[dict, list[str]]:
    """Stage-1 contents; a truncated seed call is a format failure (prereg §1), i.e. no seeds."""
    from score_a import truncated
    seed_p = d / "run_meta_seeds.json"
    if not seed_p.exists() or read_json(seed_p)["options"] != opts:
        raise SystemExit(f"{seed_p} missing or its options differ from this arms run")
    out = cc.done_jobs(d / GEN_SEED.name)
    miss = [it["id"] for it in items if f"A|{it['id']}|seed|1" not in out]
    if miss:
        raise SystemExit(f"seed jobs not done for {miss}: rerun seeds first")
    recs = {it["id"]: out[f"A|{it['id']}|seed|1"] for it in items}
    trunc = [i for i, r in recs.items() if truncated(r, opts.get("num_ctx"))]
    return {i: ("" if i in trunc else r.get("content") or "") for i, r in recs.items()}, trunc


def arms(args) -> None:
    from arms_a import build_arms
    from regnal import load_auto, load_ref
    check_frozen()
    d = out_dir(args)
    items, opts = selected(args), options(args, d)
    text, trunc = seed_texts(d, items, opts)
    jobs, meta = build_arms(items, text, load_auto(LAYER_AUTO), load_ref(LAYER_REF))
    for i in trunc:
        meta[i]["seed_truncated"] = True
    run_meta = guard(d / GEN_ARMS.name, opts, prompts_sha256(jobs), "arms")
    cc.write_json(d / ARMS_JOBS.name, jobs)
    cc.write_json(d / ARMS_META.name, meta)
    run(jobs, d / GEN_ARMS.name, opts, run_meta, "arms")


def trunc(args) -> None:
    from score_a import trunc_report
    rep = trunc_report(Path(args.out_dir) if args.out_dir else OUT, args.num_ctx)
    cc.write_json((Path(args.out_dir) if args.out_dir else OUT) / "trunc_report.json", rep)
    print(rep)


def score(args) -> None:
    from score_a import score_all
    doc = score_all(num_ctx=args.num_ctx, d=Path(args.out_dir) if args.out_dir else OUT)
    print("scored", doc["n_records"], "records; missing", len(doc["missing_jobs"]), "; seeds", doc["seeds"])


def analyze(args) -> None:
    from analyze_a import analyze as go
    rep = go(Path(args.out_dir) if args.out_dir else OUT)
    print(rep["verdict"])


def dry_run(_args) -> None:
    from dry_run_a import dry_run as go
    go()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "dry-run", "seeds", "arms", "trunc", "score", "analyze"])
    ap.add_argument("--num-ctx", type=int, default=None)
    ap.add_argument("--items", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    {"prepare": prepare, "dry-run": dry_run, "seeds": seeds, "arms": arms, "trunc": trunc, "score": score,
     "analyze": analyze}[args.cmd](args)


if __name__ == "__main__":
    main()
