"""Step 2 of plan.md §5: QD on the GT v2 multi-anchor questions (not a graph arm; resumable).

usage (host python: /home/kenzx0521/Bible_RAG/evaluation/.venv/bin/python -B qd_step2.py …):
  ids      reads GT v2 refs (its own process) and freezes S2/ids.json: the len(refs) > 1
           questions in GT order (adj4.py), ids sha256 4db37b555238…
  run      NO gold: C5 = eval3c nokg sources[:5] and contexts[:5] as they are; question and
           sub-query vectors from the container; DEEP@6 = D(question)[0:50] ∖ P(C5) and QD@6 =
           first 20 of D(s) ∖ P(C5) (3 reps), each scored by the reranker with its own query;
           freezes S2/lanes2.json
  score    raw dirs (C5 sources + the appended passage) -> quick_retrieval_eval --from-raw
           --gt v2 --top-k 6 --metric-k 6 for C5, DEEP, QD_r1..r3
  analyze  plan.md §5 verdict: QD − DEEP anchor@6 per question (QD = mean of its reps),
           mean ≥ +0.03 and bootstrap 95% CI lower bound > 0 -> S2/report2.json / .md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import qd_common as Q
import qd_stage as S

gd = Q.gd
E3 = Q._import_pinned("_e3_build", Q.GD_DIR, None)

EVAL_DIR = Q.HERE.parents[1]
PY = EVAL_DIR / ".venv" / "bin" / "python"
S2 = Q.OUT / "step2"
STAGES2, RAWS, QUICK = S2 / "stages", S2 / "raw", S2 / "quick"
IDS, LANES2 = S2 / "ids.json", S2 / "lanes2.json"
REPORT2_JSON, REPORT2_MD = S2 / "report2.json", S2 / "report2.md"
NOKG = Q.STORE / "reports" / "eval3c_20261014" / "nokg"
NOKG_RAW_SHA256 = "781167d70b8712a76d18c8768a4fd09c7666733cb16b467b576bee40b2d0870f"
IDS_SHA256_PREFIX = "4db37b555238"
GT_V2_SHA256 = "7280bb42af869ee18d34230b296f302132eb82dbf5203391e07882fd3691b2f1"
METRIC_VERSION = "4d0826bb8d14"
K = 6
GATE_MEAN = Fraction(3, 100)
FALLBACK_MAX = Fraction(5, 100)
REFPAIRS = ("refpairs_mid.jsonl", "refpairs_after.jsonl")   # around step 2 (plan.md §4 K)
N_BOOT, SEED = 10000, 20261014
ARMS2 = ("C5", "DEEP", *(f"QD_r{r}" for r in range(1, Q.N_REPS + 1)))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ ids (reads GT v2 refs)

def cmd_ids() -> int:
    if str(EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(EVAL_DIR))
    from src.gt_v2 import load_ground_truth_v2
    S2.mkdir(parents=True, exist_ok=True)
    gt = load_ground_truth_v2()
    gd.expect("GT v2 sha256", gt.sha256, GT_V2_SHA256)
    ids = [it.question_id for it in gt.items if len(it.refs) > 1]
    sha = hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()
    gd.expect("multi-anchor ids", (len(ids), sha[:12]), (204, IDS_SHA256_PREFIX))
    Q.write_frozen(IDS, Q.dumps({"ids": ids, "sha256_sorted": sha, "gt_sha256": gt.sha256,
                                 "rule": "GT v2 len(refs) > 1 (eval3c adj4.py)"}))
    S.log(f"ids: {len(ids)} -> {IDS}")
    return 0


# ------------------------------------------------------------------ C5 and its passages

def load_c5() -> tuple[list[str], dict[str, dict]]:
    ids = json.loads(IDS.read_text(encoding="utf-8"))["ids"]
    raw = json.loads(gd.read_pinned(NOKG / "raw_responses.json", NOKG_RAW_SHA256))
    by = {r["question_id"]: r for r in raw}
    out = {}
    for qid in ids:
        r = by[qid]
        if len(r["sources"]) != len(r["contexts"]):
            raise Q.QdError(f"{qid}: sources and contexts differ in length")
        out[qid] = {"question": r["question"], "sources": r["sources"][:Q.N_C5],
                    "blocks": r["contexts"][:Q.N_C5], "route": r.get("route_used")}
    return ids, out


def passage_mapper():
    vindex, units = gd.load_verse_index(), gd.load_verse_units()
    chunks = {c["chunk_id"]: c["passage_id"] for c in
              gd._gd_store._jsonl(gd._gd_store._layer_bytes(gd.LAYERS_ROOT, "struct", "chunks.jsonl"))}

    def passages(source_id: str) -> frozenset[str]:
        kind, _, body = source_id.partition(":")
        if kind == "ps":
            return frozenset({source_id})
        if kind == "ck":
            return frozenset({chunks[source_id]})
        if kind == "vs":
            return vindex.passages_of(body)
        if kind == "vr":
            a, _, b = body.partition("~")
            i, j = units.index[a], units.index[b]
            return frozenset().union(*(vindex.passages_of(u) for u in units.order[i:j + 1]))
        raise Q.QdError(f"unknown source id kind: {source_id}")
    return passages


# ------------------------------------------------------------------ run (no gold)

def sid_of(qid: str, subquery: str) -> str:
    return f"{qid}|s:{Q.sha256_text(subquery)[:16]}"


def cmd_run() -> int:
    t0 = time.time()
    pre = {"ollama_digest": S.check_ollama(), "gd_files": Q.check_gd_files(),
           "image_id": Q.gd.container_image_id()}
    ids, c5 = load_c5()
    to_p = passage_mapper()
    pc5 = {q: frozenset().union(*(to_p(s["id"]) for s in c5[q]["sources"])) for q in ids}
    prompt = Q.H.load_prompt()
    ctx = Q.gd_arms.load_context()

    enc_q = S.Stage(STAGES2, "enc_q", "encode").ensure(
        [{"sid": q, "query": c5[q]["question"]} for q in ids])
    items = [{"key": f"{q}|QD|r{rep}", "question": c5[q]["question"], "blocks": c5[q]["blocks"],
              "user_template": prompt["user_template"]}
             for rep in range(1, Q.N_REPS + 1) for q in ids]
    S.log(f"warm-up {Q.OLLAMA_MODEL}: {S.warm_up():.0f}s")
    dec = S.Stage(STAGES2, "dec", "decompose").ensure(items, prompt=prompt, before_chunk=S.check_ollama)
    S.log_ps(Q.OUT / "logs" / "ollama_ps.log", "step2 decompose end")
    for it in items:
        gd.expect(f"{it['key']} template", dec[it["key"]]["template_sha256"],
                  Q.sha256_text(it["user_template"]))
        gd.expect(f"{it['key']} context", dec[it["key"]]["context_sha256"],
                  Q.sha256_text("\n\n".join(it["blocks"])))
    subs = {}
    for key, rec in dec.items():
        qid = key.split("|")[0]
        subs.setdefault(sid_of(qid, rec["subquery"]), (qid, rec["subquery"]))
    enc = S.Stage(STAGES2, "enc", "encode").ensure(
        [{"sid": sid, "query": sq} for sid, (_, sq) in sorted(subs.items())])
    deep = {q: tuple(p for p in ctx.dense.ranking(Q.H.decode_vec(enc_q[q]["vec_b64"], q))[:Q.N_DEEP]
                     if p not in pc5[q]) for q in ids}
    pools = {sid: Q.pool_of(ctx.dense.ranking(Q.H.decode_vec(enc[sid]["vec_b64"], sid)), pc5[qid])
             for sid, (qid, _) in subs.items()}
    rr_items = [{"key": f"{q}|DEEP", "query": c5[q]["question"], "pids": sorted(deep[q])} for q in ids]
    rr_items += [{"key": sid, "query": sq, "pids": sorted(pools[sid])} for sid, (_, sq) in sorted(subs.items())]
    S.log(f"rerank: {len(rr_items)} items, {sum(len(i['pids']) for i in rr_items)} pairs")
    rr = S.Stage(STAGES2, "rr", "rerank").ensure(rr_items, before_chunk=Q.gd.container_image_id)
    lanes = {}
    for q in ids:
        entry = {"c5_ids": [s["id"] for s in c5[q]["sources"]], "pc5": sorted(pc5[q]),
                 "DEEP": pick_doc(deep[q], rr[f"{q}|DEEP"]["scores"])}
        entry["QD"] = []
        for rep in range(1, Q.N_REPS + 1):
            d = dec[f"{q}|QD|r{rep}"]
            sid = sid_of(q, d["subquery"])
            entry["QD"].append({"rep": rep, "subquery": d["subquery"], "fallback": d["fallback"],
                                "sid": sid, **pick_doc(pools[sid], rr[sid]["scores"])})
        lanes[q] = entry
    Q.H.assert_no_gold_loaded()
    sha = Q.write_frozen(LANES2, Q.dumps(lanes))
    files = {n: Q.HERE / n for n in ("plan.md", "qd_common.py", "qd_stage.py", "qd_container.py", "qd_step2.py")}
    meta = {"created_utc": now_utc(), "elapsed_s": round(time.time() - t0), "preflight": pre,
            "build_id": gd.BUILD_ID, "n": len(ids), "reps": Q.N_REPS,
            "n_distinct_subqueries": len(subs), "rerank_pairs": sum(len(i["pids"]) for i in rr_items),
            "fallbacks": sum(dec[it["key"]]["fallback"] for it in items),
            "sha256": {**{k: gd.file_sha256(v) for k, v in files.items()},
                       "ids.json": gd.file_sha256(IDS), "nokg raw": NOKG_RAW_SHA256, "lanes2.json": sha},
            "stages": {p.stem: gd.file_sha256(p) for p in sorted(STAGES2.glob("*.jsonl"))}}
    Q.write_frozen(S2 / "lanes2_meta.json", Q.dumps(meta))
    S.log(f"lanes2 -> {LANES2} ({sha[:12]})")
    return 0


def pick_doc(pool, scores) -> dict:
    p = Q.pick(pool, scores)
    return {"pid": p, "score": scores[p], "pool_size": len(pool)}


# ------------------------------------------------------------------ score

def cmd_score() -> int:
    ids, c5 = load_c5()
    lanes = json.loads(LANES2.read_text(encoding="utf-8"))
    rows = E3.load_source_rows()
    QUICK.mkdir(parents=True, exist_ok=True)
    for arm in ARMS2:
        out_dir = RAWS / arm
        if (out_dir / E3.RAW_NAME).exists() != (out_dir / E3.RUN_META_NAME).exists():
            raise Q.QdError(f"{out_dir}: half-written raw dir (remove it and re-run score)")
        if not (out_dir / E3.RAW_NAME).exists():
            items = []
            for q in ids:
                sources = list(c5[q]["sources"])
                if arm == "DEEP":
                    a = lanes[q]["DEEP"]
                    sources.append(E3.passage_source(rows[a["pid"]], a["score"], "DEEP"))
                elif arm.startswith("QD_r"):
                    a = lanes[q]["QD"][int(arm[4:]) - 1]
                    sources.append(E3.passage_source(rows[a["pid"]], a["score"], "QD"))
                items.append(E3.raw_item(q, c5[q]["question"], sources, arm))
            out_dir.mkdir(parents=True, exist_ok=True)
            E3.write_raw_dir(out_dir, items)
        label = QUICK / arm
        if not Path(f"{label}.json").exists():
            cmd = [str(PY), "-B", "quick_retrieval_eval.py", "--from-raw", str(out_dir / E3.RAW_NAME),
                   "--gt", "v2", "--top-k", str(K), "--metric-k", str(K), "--label", str(label)]
            S.log(" ".join(cmd))
            subprocess.run(cmd, cwd=EVAL_DIR, check=True)
        doc = json.loads(Path(f"{label}.json").read_text(encoding="utf-8"))
        gd.expect(f"{arm} quick config", (doc["config"]["metric_version"], doc["config"]["top_k"],
                                          doc["config"]["metric_k"], doc["config"]["from_raw"]),
                  (METRIC_VERSION, K, K, str(out_dir / E3.RAW_NAME)))
        gd.expect(f"{arm} quick meta", (doc["meta"]["gt_sha"], doc["meta"]["data_build_id"], doc["n_invalid"]),
                  (GT_V2_SHA256, gd.BUILD_ID, 0))
        gd.expect(f"{arm} quick questions", sorted(doc["per_question"]), sorted(ids))
    return 0


# ------------------------------------------------------------------ analyze

def per_question(arm: str) -> dict[str, dict]:
    doc = json.loads(Path(f"{QUICK / arm}.json").read_text(encoding="utf-8"))
    return doc["per_question"]


def exact(x) -> Fraction:
    """A quick_eval ratio (hits / anchors, ≤ a few dozen) as its exact fraction."""
    return Fraction(x).limit_denominator(10_000)


def refpairs_ok() -> dict:
    out = {}
    for name in REFPAIRS:
        path = Q.OUT / "logs" / name
        recs = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()] \
            if path.exists() else []
        chk = [r for r in recs if r.get("type") == "refcheck"]
        out[name] = {"max_abs_diff": chk[-1]["max_abs_diff"], "pass": chk[-1]["pass"]} if chk else None
    return out


def cmd_analyze() -> int:
    if str(EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(EVAL_DIR))
    from src.ab_stats import bootstrap_ci
    ids, c5 = load_c5()
    lanes = json.loads(LANES2.read_text(encoding="utf-8"))
    pq = {a: per_question(a) for a in ARMS2}
    for a in ARMS2:
        gd.expect(f"{a} question ids", sorted(pq[a]), sorted(ids))

    def metric(name: str) -> dict[str, dict[str, Fraction]]:
        out = {"C5": {}, "DEEP": {}, "QD": {}}
        for q in ids:
            out["C5"][q] = exact(pq["C5"][q][name])
            out["DEEP"][q] = exact(pq["DEEP"][q][name])
            out["QD"][q] = sum((exact(pq[f"QD_r{r}"][q][name]) for r in range(1, Q.N_REPS + 1)),
                               Fraction(0)) / Q.N_REPS
        return out

    def pair(m, x, y, qids) -> dict:
        d = [m[x][q] - m[y][q] for q in qids]
        lo, hi = bootstrap_ci([float(v) for v in d], n_boot=N_BOOT, seed=SEED)
        mean = sum(d, Fraction(0)) / len(d)
        return {"n": len(d), "mean": float(mean), "mean_exact": str(mean), "ci95": [lo, hi],
                "W:L": f"{sum(v > 0 for v in d)}:{sum(v < 0 for v in d)}"}

    anc, vrec = metric("anchor_coverage_at_k"), metric("verse_recall_at_k")
    explicit = [q for q in ids if c5[q]["route"] in ("R1", "R2")]
    primary = pair(anc, "QD", "DEEP", ids)
    n_dec = len(ids) * Q.N_REPS
    fallbacks = sum(r["fallback"] for e in lanes.values() for r in e["QD"])
    refs = refpairs_ok()
    void = Fraction(fallbacks, n_dec) > FALLBACK_MAX or not all(v and v["pass"] for v in refs.values())
    passed = (not void and Fraction(primary["mean_exact"]) >= GATE_MEAN and primary["ci95"][0] > 0)
    reading = ("K 規則作廢：fallback 或 refpairs 不合格，只准重跑一次" if void else
               "可談步驟 3（答案層非劣性，要 Kay）" if passed else "多錨 QD 線停止")
    doc = {"meta": {"created_utc": now_utc(), "n": len(ids), "k": K, "metric_version": METRIC_VERSION,
                    "plan_sha256": gd.file_sha256(Q.HERE / "plan.md"),
                    "qd_step2_sha256": gd.file_sha256(Path(__file__)),
                    "lanes2_sha256": gd.file_sha256(LANES2)},
           "means": {m: {a: float(sum(v.values(), Fraction(0)) / len(v)) for a, v in d.items()}
                     for m, d in (("anchor@6", anc), ("vrec@6", vrec))},
           "primary_QD−DEEP_anchor@6": primary,
           "K": {"fallbacks": fallbacks, "n": n_dec, "refpairs": refs, "void": void},
           "verdict": {"pass": passed, "reading": reading},
           "descriptive": {"DEEP−C5 anchor": pair(anc, "DEEP", "C5", ids),
                           "QD−C5 anchor": pair(anc, "QD", "C5", ids),
                           "QD−DEEP vrec@6": pair(vrec, "QD", "DEEP", ids),
                           "QD−DEEP anchor R1/R2": pair(anc, "QD", "DEEP", explicit) if explicit else None}}
    REPORT2_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    p = primary
    md = (f"# 步驟 2：多錨 QD（GT v2 {len(ids)} 題）\n\n"
          f"- QD@6−DEEP@6 anchor：{p['mean']:+.4f} [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}]，題 W:L {p['W:L']}"
          f" → {'過' if passed else '未過'}（門檻 ≥+0.03 且 CI 下界 >0）：{reading}\n"
          f"- 平均 anchor@6：{json.dumps(doc['means']['anchor@6'], ensure_ascii=False)}\n"
          f"- K：fallback {fallbacks}／{n_dec}，refpairs {json.dumps(refs, ensure_ascii=False)}\n")
    REPORT2_MD.write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("ids", "run", "score", "analyze"))
    a = ap.parse_args(argv)
    try:
        return {"ids": cmd_ids, "run": cmd_run, "score": cmd_score, "analyze": cmd_analyze}[a.cmd]()
    except (Q.QdError, gd.GdError) as exc:
        S.log(f"FAILED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
