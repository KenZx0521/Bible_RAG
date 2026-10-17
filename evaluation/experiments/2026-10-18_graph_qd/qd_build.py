"""Step 1 of plan.md: the DEEP and QD-family arms on NEW82 (resumable).

usage (host python: /home/kenzx0521/Bible_RAG/evaluation/.venv/bin/python -B qd_build.py …):
  oracle   reads the questions file's `bridge` field (gold-informed; its own process) and
           freezes OUT/oracle_names.json: the GD linker's names of `bridge` minus the question
           names, first 5 in link order
  run      NO gold: names (QD+G, QD+N) -> every decomposition (4 arms × 3 reps × 82) -> encode
           the distinct sub-queries -> rerank DEEP and sub-query pools -> freeze OUT/lanes.json,
           lanes_meta.json and lanes.sha256 (a re-run with every stage done must give the same
           bytes; it never overwrites different content)

Order of the decompositions: rep → question (new82_ids order) → arm (QD, QD+G, QD+N,
QD+ORACLE). All decompositions run before any rerank so the decomposer stays loaded and the
reranker never shares the CPU with it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import qd_common as Q
import qd_stage as S

OUT = Q.OUT
STAGES = OUT / "stages"
LOGS = OUT / "logs"
PS_LOG = LOGS / "ollama_ps.log"
ORACLE = OUT / "oracle_names.json"
NAMES = OUT / "names.json"
LANES, META, SHAFILE = OUT / "lanes.json", OUT / "lanes_meta.json", OUT / "lanes.sha256"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sid_of(qid: str, subquery: str) -> str:
    return f"{qid}|s:{Q.sha256_text(subquery)[:16]}"


# ------------------------------------------------------------------ ORACLE names (reads `bridge`)

def oracle() -> int:
    raw = json.loads(Q.gd.read_pinned(Q.H.QUESTIONS_FILE, Q.gd.FILE_SHA256[Q.gd.NEW82_FILE]))
    rows = {r["id"]: r for r in raw["questions"]}
    inp = Q.load_step1_inputs()
    kg0 = Q.load_kg0_occurrences()
    names, linked = {}, {}
    for qid, question in inp.questions.items():
        qn = inp.ctx.question_names(question)
        linked[qid] = list(inp.ctx.question_names(rows[qid]["bridge"]))
        excl = Q.context_exclusions(inp.ctx.graph, inp.c5[qid], qn)
        names[qid] = list(Q.eligible_names(linked[qid], kg0, excl))
    doc = {"meta": {"created_utc": now_utc(), "rule": "GD linker names of `bridge` (in the graph), "
                    "kept only if QD+G / QD+N could output them (is_eligible with the question and "
                    "C5 names excluded), first 5 in link order",
                    "questions_file_sha256": Q.gd.file_sha256(Q.H.QUESTIONS_FILE),
                    "n_empty": sum(not v for v in names.values())},
           "names": names, "linked_before_filter": linked}
    Q.write_frozen(ORACLE, Q.dumps(doc))
    S.log(f"oracle names: {len(names)} questions, {doc['meta']['n_empty']} empty -> {ORACLE}")
    return 0


# ------------------------------------------------------------------ names of QD+G / QD+N

def build_names(inp: Q.Step1Inputs, kg0: dict[str, int], oracle_names: dict) -> dict:
    g = inp.ctx.graph
    out = {}
    for qid, question in inp.questions.items():
        qn = inp.ctx.question_names(question)
        excl = Q.context_exclusions(g, inp.c5[qid], qn)
        out[qid] = {"question_names": list(qn),
                    "QD+G": list(Q.graph_names(g, inp.c5[qid], kg0, excl)),
                    "QD+N": list(Q.dense_names(g, inp.d30[qid], inp.c5[qid], kg0, excl)),
                    "QD+ORACLE": list(oracle_names[qid])}
    return out


def question_vectors(qids: list[str]) -> dict:
    path = Q.gd.PN / "encode_out.jsonl"
    Q.gd.read_pinned(path, Q.gd.ARCHIVE_SHA256[path])
    vecs, _ = Q.gd_arms.load_query_vectors(path, qids)
    return vecs


# ------------------------------------------------------------------ run

ITERQ_SCRIPT_SHA256 = "3173e994ab50e7c178fc62792fe4cdc97d0908106b9839431ce2ce97dd59aff8"


def preflight() -> dict:
    Q.gd.expect("iterq iter_in_container.py sha256", Q.gd.file_sha256(Q.H.ITERQ_SCRIPT), ITERQ_SCRIPT_SHA256)
    return {"gd_files": Q.check_gd_files(), "image_id": Q.gd.container_image_id(),
            "ollama_digest": S.check_ollama()}


def decompose_all(inp: Q.Step1Inputs, names: dict) -> dict[str, dict]:
    base = inp.prompt["user_template"]
    items = []
    for rep in range(1, Q.N_REPS + 1):
        for qid, question in inp.questions.items():
            for arm in Q.LLM_ARMS:
                if arm in Q.NAMED_ARMS and not names[qid][arm]:
                    continue        # same prompt as QD: the arm reuses QD's decomposition
                arm_names = names[qid][arm] if arm in Q.NAMED_ARMS else []
                items.append({"key": f"{qid}|{arm}|r{rep}", "question": question,
                              "pids": list(inp.c5[qid]),
                              "user_template": Q.user_template_for(base, arm_names)})
    S.log_ps(PS_LOG, "decompose start")
    S.log(f"warm-up {Q.OLLAMA_MODEL}: {S.warm_up():.0f}s")
    stage = S.Stage(STAGES, "dec", "decompose")
    dec = stage.ensure(items, prompt=inp.prompt, before_chunk=S.check_ollama)
    S.log_ps(PS_LOG, "decompose end")
    for it in items:
        rec = dec[it["key"]]
        Q.gd.expect(f"{it['key']} template", rec["template_sha256"], Q.sha256_text(it["user_template"]))
        Q.gd.expect(f"{it['key']} context", rec["context_pids"], it["pids"])
        qd = dec[it["key"].rsplit("|", 2)[0] + f"|QD|{it['key'].rsplit('|', 1)[1]}"]
        Q.gd.expect(f"{it['key']} context blocks = QD's", rec["context_sha256"], qd["context_sha256"])
        if rec is not qd and rec["user_sha256"] == qd["user_sha256"]:
            raise Q.QdError(f"{it['key']}: the names line did not reach the prompt")
    return dec


def dec_of(dec: dict, qid: str, arm: str, rep: int) -> tuple[dict, bool]:
    """The arm's decomposition, or QD's when the arm had no names (identical prompt)."""
    key = f"{qid}|{arm}|r{rep}"
    return (dec[key], False) if key in dec else (dec[f"{qid}|QD|r{rep}"], True)


def run() -> int:
    t0 = time.time()
    LOGS.mkdir(parents=True, exist_ok=True)
    pre = preflight()
    if not ORACLE.exists():
        raise Q.QdError(f"{ORACLE} missing: run `qd_build.py oracle` first (its own process)")
    oracle_doc = json.loads(ORACLE.read_text(encoding="utf-8"))
    inp = Q.load_step1_inputs()
    kg0 = Q.load_kg0_occurrences()
    names = build_names(inp, kg0, oracle_doc["names"])
    sha_names = Q.write_frozen(NAMES, Q.dumps(names))
    qids = list(inp.questions)

    vecs = question_vectors(qids)
    q_rank = {q: inp.ctx.dense.ranking(vecs[q]) for q in qids}
    for q in qids:
        Q.gd.expect(f"{q} D30 from the archived question vector", tuple(q_rank[q][:30]), inp.d30[q])

    dec = decompose_all(inp, names)

    subs = {}                                   # sid -> (qid, subquery)
    for key, rec in dec.items():
        qid = key.split("|")[0]
        subs.setdefault(sid_of(qid, rec["subquery"]), (qid, rec["subquery"]))
    enc = S.Stage(STAGES, "enc", "encode").ensure(
        [{"sid": sid, "query": sq} for sid, (_, sq) in sorted(subs.items())])
    pools = {sid: Q.pool_of(inp.ctx.dense.ranking(Q.H.decode_vec(enc[sid]["vec_b64"], sid)),
                            inp.c5[qid])
             for sid, (qid, _) in subs.items()}
    deep = {q: Q.deep_pool(q_rank[q], inp.c5[q]) for q in qids}

    rr_items = [{"key": f"{q}|DEEP", "query": inp.questions[q], "pids": sorted(deep[q])} for q in qids]
    rr_items += [{"key": sid, "query": sq, "pids": sorted(pools[sid])}
                 for sid, (_, sq) in sorted(subs.items())]
    S.log(f"rerank: {len(rr_items)} items, {sum(len(i['pids']) for i in rr_items)} pairs")
    rr = S.Stage(STAGES, "rr", "rerank").ensure(rr_items, before_chunk=Q.gd.container_image_id)
    Q.H.assert_no_gold_loaded()

    lanes = build_lanes(inp, dec, rr, pools, deep)
    sha_lanes = Q.write_frozen(LANES, Q.dumps(lanes))
    if META.exists():          # written by an earlier run that stopped before the sha file
        Q.gd.expect("lanes_meta lanes sha", json.loads(META.read_text(encoding="utf-8"))["sha256"]["lanes.json"], sha_lanes)
    else:
        Q.write_frozen(META, Q.dumps(build_meta(inp, pre, sha_names, sha_lanes, dec, rr_items, time.time() - t0)))
    sha_meta = Q.gd.file_sha256(META)
    Q.write_frozen(SHAFILE, f"{sha_lanes}  lanes.json\n{sha_names}  names.json\n{sha_meta}  lanes_meta.json\n")
    S.log(f"done: {LANES} ({sha_lanes[:12]}) in {time.time() - t0:.0f}s")
    return 0


def appended(pool, scores) -> dict:
    ranked = sorted(pool, key=lambda p: (-scores[p], p))
    gap = scores[ranked[0]] - scores[ranked[1]] if len(ranked) > 1 else None
    return {"pid": ranked[0], "score": scores[ranked[0]], "gap_to_second": gap,
            "pool_size": len(pool), "top3": [[p, scores[p]] for p in ranked[:3]]}


def build_lanes(inp, dec, rr, pools, deep) -> dict:
    lanes = {}
    for qid in inp.questions:
        entry = {"C5": list(inp.c5[qid]), "DEEP": appended(deep[qid], rr[f"{qid}|DEEP"]["scores"])}
        for arm in Q.LLM_ARMS:
            reps = []
            for rep in range(1, Q.N_REPS + 1):
                d, reused = dec_of(dec, qid, arm, rep)
                sid = sid_of(qid, d["subquery"])
                reps.append({"rep": rep, "subquery": d["subquery"], "fallback": d["fallback"],
                             "attempts": len(d["attempts"]), "sid": sid, "reused_qd": reused,
                             **appended(pools[sid], rr[sid]["scores"])})
            entry[arm] = reps
        lanes[qid] = entry
    return lanes


def build_meta(inp, pre, sha_names, sha_lanes, dec, rr_items, elapsed) -> dict:
    files = {"plan.md": Q.HERE / "plan.md", "qd_common.py": Q.HERE / "qd_common.py",
             "qd_stage.py": Q.HERE / "qd_stage.py", "qd_build.py": Q.HERE / "qd_build.py",
             "qd_container.py": S.CONTAINER_SCRIPT, "new82_ans/it_host.py": Q.NEW82_ANS / "it_host.py",
             "iterq/iter_in_container.py": Q.H.ITERQ_SCRIPT,
             "iterq/decomposer_prompt.txt": Q.H.PROMPT_FILE,
             "graph_gd new82/lists.json": Q.H.LISTS_FILE, "graph_gd new82/scores.jsonl": Q.H.SCORES_FILE,
             "oracle_names.json": ORACLE}
    fb = {a: sum(dec_of(dec, q, a, r)[0]["fallback"] for q in inp.questions
                  for r in range(1, Q.N_REPS + 1)) for a in Q.LLM_ARMS}
    return {"created_utc": now_utc(), "elapsed_s": round(elapsed), "set": "new82",
            "n_questions": len(inp.questions), "arms": list(Q.ARMS), "reps": Q.N_REPS,
            "preflight": pre, "build_id": Q.gd.BUILD_ID,
            "decomposer": {"model": Q.OLLAMA_MODEL, "digest": Q.OLLAMA_DIGEST, "llm": Q.LLM_LABEL,
                           "max_tokens": Q.LLM_MAX_TOKENS, "temperature": 0.0,
                           "prompt_file_sha256": Q.PROMPT_SHA256,
                           "names_template_sha256": Q.sha256_text(Q.names_template(inp.prompt["user_template"]))},
            "params": {"n_c5": Q.N_C5, "n_pool": Q.N_POOL, "n_deep": Q.N_DEEP, "n_names": Q.N_NAMES,
                       "hub_occ": Q.HUB_OCC, "min_name_len": Q.MIN_NAME_LEN,
                       "ppr_alpha": Q.gd_arms.PPR_ALPHA, "ppr_iters": Q.gd_arms.PPR_ITERS,
                       "select": "first of pool by (−score, pid)"},
            "fallbacks": fb, "n_decompositions": len(dec),
            "n_distinct_subqueries": len(rr_items) - len(inp.questions),
            "rerank_pairs": sum(len(i["pids"]) for i in rr_items),
            "sha256": {**{k: Q.gd.file_sha256(v) for k, v in files.items()},
                       "names.json": sha_names, "lanes.json": sha_lanes},
            "stages": {p.stem: Q.gd.file_sha256(p) for p in sorted(STAGES.glob("*.jsonl"))},
            "gold_isolation": "QD+G / QD+N names come only from question texts, GD lists/scores "
                              "(C5, D30), store layers and kg0; oracle_names.json (gold-derived, "
                              "its own process) enters only QD+ORACLE; gd_common question-set "
                              "loaders never called (asserted)"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("oracle", "run"))
    a = ap.parse_args(argv)
    try:
        return oracle() if a.cmd == "oracle" else run()
    except (Q.QdError, Q.gd.GdError) as exc:
        S.log(f"FAILED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
