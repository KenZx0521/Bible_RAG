"""book_anchor ablation host CLI end to end (experiments/2026-10-15_book_anchor/ba_analyze.py).

Synthetic driver records with real GT v2 question ids go through check --partial, check
(subsets, gen_plan, judge ids / order, freeze; a second check verifies instead of
rewriting), export-ans, export-retr, judge-order and report, with stand-in judge and
retrieval-metric files; a failed invariant stops check before anything is frozen, and a
judge file whose contexts were not the generator blocks is refused (§5 量尺), as is one
whose .src_sha is not the ans it judges now; report re-verifies eval3c's sources.
"""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

_EXP = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_checks as ck  # noqa: E402
import _ba_export as bex  # noqa: E402
import _ba_io as bio  # noqa: E402
import _ba_report as rep  # noqa: E402
import ba_analyze as ba  # noqa: E402
from src.data_loader import load_gt  # noqa: E402

REAL_LOAD_REF = ba.load_ref

GT = load_gt("v2").by_id()
G = "GENERAL_BIBLE_QUESTION_"
Q024, Q096, Q001, Q013 = (f"{G}{n}" for n in ("024", "096", "001", "013"))
QV1, QV2 = "VERSE_LOOKUP_001", "VERSE_LOOKUP_002"
FP = {"embedder": {"tokenizer_sha": "e" * 64}, "reranker": {"tokenizer_sha": "r" * 64}}
BACKEND = {f: "b" * 64 for f in ck.BACKEND_FILES}
EXPSHA = {"ba_driver.py": "1" * 64}
SETTINGS = {**ck.EXPECT_SETTINGS, "default_top_k": 5}
REFUSAL = Path("/mnt/ollama-data/bible_rag_store/reports/eval3c_20261014_analysis/refusal_v2.py")


def res(pid, strategy="hybrid_hybrid", score=0.5, book="mat"):
    return {"id": pid, "kind": "passage", "book_name": f"書{book}", "book_id": book,
            "chapter_num": 1, "title": "標題", "verse_range": "1-5", "content": f"經文 {pid}",
            "source_strategy": strategy, "fused_score": score, "rerank_score": score}


def arm(core, ba=(), pins=(), ba_calls=1, pool_extra=(), route="R5", multi=False):
    results = [res(p, "book_anchor" if p in ba else "hybrid_hybrid") for p in core]
    pool = [{"id": p, "source_strategy": "book_anchor" if p in ba else "hybrid_hybrid",
             "weight": 0.9 if p in ba else 0.65, "rerank_score": 0.5, "book_id": "mat"}
            for p in dict.fromkeys([*core, *pool_extra])]
    return {"results": results, "ids": list(core), "n_core": len(core),
            "ctx_sha": bio.ctx_sha(results, bex.host_blocks),
            "stats": {"route_used": route, "strategy_errors": {}, "use_graph": True,
                      "graph_strategies": ["event_registry"],
                      "fusion_alpha": None if route == "R1" else 0.3,
                      "strategies_used": ["semantic"], "reranked_top_k": len(core)},
            "pool": pool, "pins": list(pins), "ba_calls": ba_calls,
            "signals": {"detected_book_ids": ["isa"], "multi_book": multi}}


def q(qid, ctrl, nopin=None, off=None, skipped=None, forced=False):
    return {"kind": "q", "qid": qid, "question": GT[qid].question, "forced": forced,
            "arms_skipped": skipped, "intent_ok": True, "intent_attempts": 1,
            "arm_attempts": 1, "arms": {"ctrl": ctrl, "nopin": nopin, "off": off}}


D = [f"ps:mat.{i}.1" for i in range(1, 8)]


def records():
    pin = [{"book_gate": False, "pinned": ["ps:isa.6.1", "ps:isa.13.1"], "called": True}]
    rows = [q(Q024, arm(["ps:isa.6.1", "ps:isa.13.1", *D[:3]], ba={"ps:isa.6.1", "ps:isa.13.1"},
                        pins=pin, pool_extra=D[:5]),
              arm(D[:5], pool_extra=["ps:isa.6.1", "ps:isa.13.1"]), arm(D[:5]))]
    c096 = arm(["ps:rev.21.9", *D[:4]], ba={"ps:rev.21.9"}, multi=True,
               pins=[{"book_gate": True, "pinned": ["ps:rev.21.9"], "called": True}])
    rows.append(q(Q096, c096, copy.deepcopy(c096), arm(D[:5], multi=True)))
    c001 = arm([*D[:4], "ps:isa.30.19"], ba={"ps:isa.30.19"})
    rows.append(q(Q001, c001, copy.deepcopy(c001), arm([*D[:4], D[5]])))
    c013 = arm(D[:5], pool_extra=["ps:gen.15.1"])
    c013["pool"][-1]["source_strategy"] = "book_anchor"
    off013 = copy.deepcopy(c013)
    off013["pool"] = off013["pool"][:-1]
    rows.append(q(Q013, c013, copy.deepcopy(c013), off013))
    v1 = arm(["vs:jhn.3.16"], ba_calls=0, route="R1")
    rows.append(q(QV1, v1, copy.deepcopy(v1), copy.deepcopy(v1), forced=True))
    rows.append(q(QV2, arm(D[:5], ba_calls=0), skipped="book_anchor_not_invoked"))
    return rows


def meta(**over):
    return {"kind": "meta", "mode": "retrieve", "build_id": ck.BUILD_ID, "llm_health": True,
            "handshake": {"ok": True}, "encoder_fingerprint": FP, "torch_threads": 24,
            "settings": SETTINGS, "call": ck.EXPECT_CALL, "backend_sha256": BACKEND,
            "exp_sha256": EXPSHA, "env": {"RAG_ENV": "prod"}, **over}


@pytest.fixture
def run(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    rows = records()
    (out / "retrieval.jsonl").write_text(
        "".join(bio.dumps_line(x) for x in [meta(), *rows[:3]]) + bio.dumps_line(meta())
        + "".join(bio.dumps_line(x) for x in rows[3:]), encoding="utf-8")
    (out / "questions.json").write_text(json.dumps(
        [{"question_id": r["qid"], "question": r["question"]} for r in rows]))
    (out / "exp_meta.json").write_text(json.dumps({
        "mode": "run", "image_id": ck.IMAGE_PREFIX + "e48b", "backend_sha256": BACKEND,
        "exp_sha256": EXPSHA, "ollama_digests": {ck.GEN_MODEL: "d", ck.JUDGE_MODEL: "j"},
        "refusal_v2_sha256": ck.REFUSAL_SHA_PREFIX + "x"}))
    run_meta = tmp_path / "run_meta.json"
    run_meta.write_text(json.dumps({"data_build_id": ck.BUILD_ID, "encoder_fingerprint": FP}))
    faith = tmp_path / "faith.json"
    faith.write_text(json.dumps({"samples": [
        {"question_id": qid, "invalid": None, "ragas_faithfulness_strict": 1.0} for qid in GT]}))
    eval3c = {r["qid"]: {"route_used": r["arms"]["ctrl"]["stats"]["route_used"],
                         "sources": [{"id": x["id"], "score": x["fused_score"]}
                                     for x in r["arms"]["ctrl"]["results"]]} for r in rows}
    ref = {"c43": [Q024, Q096, Q001], "ba39": [Q024, Q096, Q001], "pinned20": [Q024, Q096],
           "pinned_single19": [Q024], "first_r1": QV1,
           "routes": {k: v["route_used"] for k, v in eval3c.items()}}
    monkeypatch.setitem(ba.PATHS, "run_meta", run_meta)
    monkeypatch.setitem(ba.PATHS, "faith", faith)
    monkeypatch.setattr(ba, "load_ref", lambda: ref)
    monkeypatch.setattr(ba, "eval3c_raw", lambda: eval3c)
    return out


def gens_for(out):
    plan = json.loads((out / "checks" / "gen_plan.json").read_text())["items"]
    lines = []
    for it in plan:
        answer = "找不到相關的經文內容" if (it["arm"], it["rep"]) == ("off", 2) else "答案" * 40
        lines.append({"kind": "gen", **{k: it[k] for k in ("qid", "arm", "rep", "ctx_sha")},
                      "answer": answer, "ok": True, "attempts": 1, "messages_match": True,
                      "n_llm_calls": 1, "llm_options": {"temperature": 0.1, "max_tokens": 10000}})
    gen_meta = {k: v for k, v in meta(mode="generate").items()
                if k not in ("encoder_fingerprint", "torch_threads", "handshake")}
    (out / "gen.jsonl").write_text("".join(bio.dumps_line(x) for x in [gen_meta, *lines]),
                                   encoding="utf-8")
    return plan


def judge_meta(n, **over):
    return {"context_format": "generator_blocks", "context_sources": {"backend": n},
            "judge_model": ck.JUDGE_MODEL, "gt_version": "v2", "data_build_id": ck.BUILD_ID,
            **over}


def write_judges(out, value=lambda arm, rep, q: 0.6, **meta_over):
    order = json.loads((out / "checks" / "judge_order.json").read_text())
    ids = {a: json.loads((out / "checks" / f"judge_ids_{a}.json").read_text()) for a in ck.ARMS}
    for d in order["coverage"] + ["ctrl_r1"]:
        a, r = d.rsplit("_r", 1)
        for kind, field, names in (("cov", "coverage", [f"{d}.cov.json"] + (
                ["ctrl_r1.cov_rep.json"] if d == "ctrl_r1" else [])),
                ("faith", "ragas_faithfulness_strict", [f"{d}.faith.json"] if d in order["strict"]
                 else [])):
            samples = [{"question_id": x, "invalid": None, field: value(a, int(r), x),
                        "judge": {"verdicts": {"1": "covered"}}} for x in ids[a]]
            for name in names:
                (out / "judge").mkdir(exist_ok=True)
                (out / "judge" / name).write_text(json.dumps(
                    {"meta": judge_meta(len(samples), **meta_over), "samples": samples}))
                (out / "judge" / (name + ".src_sha")).write_text(
                    bio.sha256_file(out / "ans" / d / "raw_responses.json") + "\n")
    for a in ck.ARMS:
        for k in (5, 6):
            (out / "retr" / f"{a}.k{k}.json").write_text(json.dumps({
                "config": {"metric_version": rep.METRIC_VERSION, "metric_k": k, "top_k": 5},
                "meta": {"gt_version": "v2"}, "overall": {"verse_recall_at_k": 0.7},
                "per_question": {x: {"verse_recall_at_k": 0.5, "invalid": False}
                                 for x in json.loads((out / "questions.json").read_text())
                                 for x in [x["question_id"]]}}))


def test_the_host_steps_end_to_end(run, monkeypatch, capsys):
    out = run
    assert ba.main(["check", "--out", str(out), "--partial"]) == 0
    assert ba.main(["check", "--out", str(out)]) == 0
    subs = json.loads((out / "checks" / "subsets.json").read_text())
    assert subs["D_nopin"] == [Q024] and subs["D_off"] == [Q001, Q024, Q096]
    assert subs["C"] == [Q001, Q013, Q024, Q096] and subs["P_m"] == [Q096]
    freeze = (out / "checks" / "freeze.json").read_text()
    assert ba.main(["check", "--out", str(out)]) == 0               # a resume verifies
    assert (out / "checks" / "freeze.json").read_text() == freeze
    plan = gens_for(out)
    assert {a: sum(i["arm"] == a for i in plan) for a in ck.ARMS} == \
        {"ctrl": 18, "nopin": 6, "off": 18}
    assert ba.main(["export-ans", "--out", str(out)]) == 0
    assert sorted(p.name for p in (out / "ans").iterdir()) == sorted(
        f"{a}_r{r}" for a in ck.ARMS for r in range(1, 7))
    assert ba.main(["export-retr", "--out", str(out)]) == 0
    capsys.readouterr()
    assert ba.main(["judge-order", "--out", str(out), "--kind", "strict"]) == 0
    assert len(capsys.readouterr().out.split()) == 9
    write_judges(out, value=lambda a, r, x: 0.4 if a == "off" else 0.6)
    monkeypatch.setattr(rep, "retrieval_descriptives", lambda o, rows, subs: {"stub": True})
    monkeypatch.setitem(ba.PATHS, "refusal", _refusal_copy(out))
    assert ba.main(["report", "--out", str(out)]) == 0
    doc = json.loads((out / "report" / "report.json").read_text())
    assert doc["invariants_ok"] is True and doc["invariants"]["I7"]["ok"] is True
    oc = doc["comparisons"]["off:ctrl"]
    assert oc["cov"]["mean"] == pytest.approx(-0.2) and oc["cov"]["n"] == 3
    assert doc["comparisons"]["nopin:ctrl"]["cov"]["mean"] == pytest.approx(0.0)
    assert doc["comparisons"]["off:nopin"]["population"] == [Q001, Q024, Q096]
    assert doc["comparisons"]["off:ctrl"]["strict500"] == pytest.approx(
        (497 + 3 * 0.4) / 500)
    assert doc["verdicts"]["off:ctrl"]["verdict"] in ("harm", "inconclusive")
    assert doc["prod_action"]["action"] in ("keep", "nopin")
    assert doc["descriptive"]["refusals"]["off:ctrl"]["strict_refusal"]["off"] == 3
    assert doc["descriptive"]["judge_determinism"]["same_fraction"] == 1.0
    assert (out / "report" / "report.md").read_text().startswith("# book_anchor 消融結果與判定")


def test_a_failed_invariant_stops_check_before_freezing(run):
    path = run / "retrieval.jsonl"
    rows = bio.read_jsonl(path)
    rows[-1]["arms"]["ctrl"]["stats"]["strategy_errors"] = {"semantic": "Timeout"}
    path.write_text("".join(bio.dumps_line(r) for r in rows), encoding="utf-8")
    assert ba.main(["check", "--out", str(run)]) == 1
    inv = json.loads((run / "checks" / "invariants.json").read_text())
    assert inv["I4"]["ok"] is False and not (run / "checks" / "freeze.json").exists()
    assert ba.main(["export-retr", "--out", str(run)]) == 2


def test_check_refuses_a_retrieval_that_changed_after_freezing(run):
    assert ba.main(["check", "--out", str(run)]) == 0
    path = run / "retrieval.jsonl"
    rows = bio.read_jsonl(path)
    rows[-1]["arms"]["ctrl"]["ctx_sha"] = "0" * 64       # QV2 is in no frozen file
    path.write_text("".join(bio.dumps_line(r) for r in rows), encoding="utf-8")
    assert ba.main(["check", "--out", str(run)]) == 0
    q024 = next(r for r in rows if r.get("qid") == Q024)
    q024["arms"]["off"]["ctx_sha"] = "0" * 64              # the plan carries it
    path.write_text("".join(bio.dumps_line(r) for r in rows), encoding="utf-8")
    assert ba.main(["check", "--out", str(run)]) == 2


def test_report_refuses_headerless_judge_contexts(run, monkeypatch):
    assert ba.main(["check", "--out", str(run)]) == 0
    gens_for(run)
    assert ba.main(["export-ans", "--out", str(run)]) == 0
    assert ba.main(["export-retr", "--out", str(run)]) == 0
    write_judges(run, context_format="headerless")
    monkeypatch.setattr(rep, "retrieval_descriptives", lambda o, rows, subs: {})
    monkeypatch.setitem(ba.PATHS, "refusal", _refusal_copy(run))
    assert ba.main(["report", "--out", str(run)]) == 2


def test_partial_check_fails_on_i1(run, monkeypatch):
    raw = ba.eval3c_raw()
    raw[Q001] = {**raw[Q001], "sources": raw[Q001]["sources"][::-1]}
    monkeypatch.setattr(ba, "eval3c_raw", lambda: raw)
    assert ba.main(["check", "--out", str(run), "--partial"]) == 1


def test_trim_cuts_the_tail(tmp_path, capsys):
    path = tmp_path / "g.jsonl"
    path.write_bytes(b'{"kind": "gen"}\n{"kind"')
    assert ba.main(["trim", str(path)]) == 0
    assert path.read_bytes() == b'{"kind": "gen"}\n'


def _refusal_copy(out):
    if not REFUSAL.exists():
        pytest.skip("frozen refusal_v2.py not in the store")
    target = out.parent / "refusal_v2.py"
    shutil.copyfile(REFUSAL, target)
    return target


EVAL3C = Path("/mnt/ollama-data/bible_rag_store/reports/eval3c_20261014/full")


def test_retrieval_descriptives_on_eval3c_full(tmp_path):
    """The ledger, gold flags and tail MRR on the store's eval3c full raw (identical arms)."""
    if not (EVAL3C / "raw_responses.json").exists():
        pytest.skip("eval3c full raw not in the store")
    out = tmp_path / "out"
    for a in ck.ARMS:
        (out / "retr" / a).mkdir(parents=True)
        for name in ("raw_responses.json", "run_meta.json"):
            shutil.copyfile(EVAL3C / name, out / "retr" / a / name)
        for k in (5, 6):
            (out / "retr" / f"{a}.k{k}.json").write_text(json.dumps({
                "config": {"metric_version": rep.METRIC_VERSION, "metric_k": k, "top_k": 5},
                "meta": {"gt_version": "v2"}, "overall": {"verse_recall_at_k": 0.7}}))
    raw = {x["question_id"]: x for x in json.loads((EVAL3C / "raw_responses.json").read_text())}
    ids = [s["id"] for s in raw[Q024]["sources"]]
    rows = {Q024: {"arms": {"ctrl": {"n_core": 5, "pins": [
        {"book_gate": False, "pinned": ids[:2], "called": True}]}}}}
    subs = {"P_s": [Q024], "P_m": []}
    doc = rep.retrieval_descriptives(out, rows, subs)
    assert doc["ledger"]["off:ctrl"]["counts"] == {"identical": 500}
    assert doc["ledger"]["off:ctrl"]["gold_out"] == []
    tail = doc["tail_mrr"]["per_question"][0]
    assert tail["qid"] == Q024 and tail["ctrl"] == pytest.approx(0.25)
    assert tail["tail"] > tail["ctrl"]
    assert doc["overall"]["ctrl"]["k5"] == {"verse_recall_at_k": 0.7}


def pipeline(out, monkeypatch, mutate_gens=None):
    """check → gens (optionally changed) → export → judges → report; the report document."""
    assert ba.main(["check", "--out", str(out)]) == 0
    gens_for(out)
    if mutate_gens:
        lines = bio.read_jsonl(out / "gen.jsonl")
        mutate_gens(lines)
        (out / "gen.jsonl").write_text("".join(bio.dumps_line(x) for x in lines),
                                       encoding="utf-8")
    assert ba.main(["export-ans", "--out", str(out)]) == 0
    assert ba.main(["export-retr", "--out", str(out)]) == 0
    write_judges(out)
    monkeypatch.setattr(rep, "retrieval_descriptives", lambda o, rows, subs: {})
    monkeypatch.setitem(ba.PATHS, "refusal", _refusal_copy(out))
    assert ba.main(["report", "--out", str(out)]) == 0
    return json.loads((out / "report" / "report.json").read_text())


def test_a_generate_meta_off_the_prereg_makes_every_verdict_invalid(run, monkeypatch):
    def bad_meta(lines):
        lines[0]["settings"] = {**lines[0]["settings"], "llm_max_tokens": 4096}

    doc = pipeline(run, monkeypatch, bad_meta)
    assert doc["invariants"]["I0_generate"]["ok"] is False
    assert {v["verdict"] for v in doc["verdicts"].values()} == {"invalid"}
    assert doc["prod_action"]["action"] == "rerun"


def test_failed_generations_leave_their_question_out_of_the_pair(run, monkeypatch):
    def fail(lines):
        for g in lines:
            if g["kind"] == "gen" and (g["qid"], g["arm"]) == (Q024, "off") and g["rep"] <= 3:
                g["ok"], g["answer"] = False, "生成回答時發生錯誤：ReadTimeout('')"

    doc = pipeline(run, monkeypatch, fail)
    oc = doc["comparisons"]["off:ctrl"]
    assert oc["cov"]["excluded"] == [Q024] and oc["strict"]["excluded"] == [Q024]
    assert oc["excluded"] == [Q024] and oc["cov"]["n"] == 2
    assert doc["per_question"]["cov"]["off"][Q024] is None
    assert len(doc["invariants"]["I7"]["failed_final"]) == 3


def test_i7_messages_that_differ_from_the_context_stop_export(run):
    assert ba.main(["check", "--out", str(run)]) == 0
    gens_for(run)
    lines = bio.read_jsonl(run / "gen.jsonl")
    lines[1]["messages_match"] = False
    (run / "gen.jsonl").write_text("".join(bio.dumps_line(x) for x in lines), encoding="utf-8")
    assert ba.main(["export-ans", "--out", str(run)]) == 2


def _ready_for_report(out, monkeypatch):
    assert ba.main(["check", "--out", str(out)]) == 0
    gens_for(out)
    assert ba.main(["export-ans", "--out", str(out)]) == 0
    assert ba.main(["export-retr", "--out", str(out)]) == 0
    write_judges(out)
    monkeypatch.setattr(rep, "retrieval_descriptives", lambda o, rows, subs: {})
    monkeypatch.setitem(ba.PATHS, "refusal", _refusal_copy(out))


def test_report_refuses_a_judge_file_made_from_other_answers(run, monkeypatch):
    _ready_for_report(run, monkeypatch)
    lines = bio.read_jsonl(run / "gen.jsonl")         # an I6 regeneration, then export-ans
    g = next(x for x in lines if x["kind"] == "gen" and (x["arm"], x["rep"]) == ("off", 4))
    lines.append({**g, "answer": "補跑後的新答案" * 10})
    (run / "gen.jsonl").write_text("".join(bio.dumps_line(x) for x in lines), encoding="utf-8")
    assert ba.main(["export-ans", "--out", str(run)]) == 0
    assert ba.main(["report", "--out", str(run)]) == 2
    (run / "judge" / "off_r4.cov.json.src_sha").write_text(
        bio.sha256_file(run / "ans" / "off_r4" / "raw_responses.json"))
    assert ba.main(["report", "--out", str(run)]) == 0       # off_r4 judged again
    (run / "judge" / "ctrl_r2.cov.json.src_sha").unlink()
    assert ba.main(["report", "--out", str(run)]) == 2


def test_report_refuses_when_an_eval3c_source_changed(run, monkeypatch, tmp_path):
    _ready_for_report(run, monkeypatch)
    sources = {}
    for key in ("raw", "run_meta", "faith"):
        sources[key] = ba.PATHS[key] if key != "raw" else tmp_path / "raw.json"
    sources["raw"].write_text("[]")
    ref = tmp_path / "eval3c_ref.json"
    ref.write_text(json.dumps({"meta": {f"{k}_sha256": bio.sha256_file(v)
                                        for k, v in sources.items()}}))
    for key, path in sources.items():
        monkeypatch.setitem(ba.PATHS, key, path)
    monkeypatch.setattr(ba, "REF", ref)
    monkeypatch.setattr(ba, "load_ref", REAL_LOAD_REF)
    assert ba.main(["report", "--out", str(run)]) == 0
    faith = json.loads(ba.PATHS["faith"].read_text())
    faith["samples"][0]["ragas_faithfulness_strict"] = 0.0
    ba.PATHS["faith"].write_text(json.dumps(faith))
    assert ba.main(["report", "--out", str(run)]) == 2


def test_report_md_lists_invalid_pairs_next_to_the_action():
    act = {"action": "keep", "label_zh": "維持現行", "rule": 1, "invalid_pairs": ["off:nopin"]}
    cmp = {m: {"mean": None, "ci975": None, "p_holm": 1.0} for m in ("cov", "strict", "vrec5")}
    doc = {"prod_action": act, "invariants": {}, "subsets": {}, "scope": [],
           "comparisons": {n: {**cmp, "population": [], "excluded": []} for n in rep.PAIR_NAMES},
           "verdicts": {n: {"label_zh": "可改"} for n in rep.PAIR_NAMES}}
    md = rep.render_md(doc)
    assert "無效配對：off:nopin" in md
