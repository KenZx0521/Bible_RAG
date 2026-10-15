"""book_anchor ablation export (experiments/2026-10-15_book_anchor/_ba_export.py).

prereg §5 量尺, §6 I6/I7, §9 3.4/3.6, §10 test_ba_export: retr/ and ans/ directories read back
through quick_retrieval_eval.samples_from_raw, provenance.read_run_meta and
evaluator.load_samples_from_checkpoint; their context_format is generator_blocks; a failed
answer is written as it is and validity.answer_failure calls it "generation"; a contexts
sha that does not match raises.
"""

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXP = _REPO / "evaluation" / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_export as bex  # noqa: E402
import _ba_io as bio  # noqa: E402
import quick_retrieval_eval as qre  # noqa: E402
from src.data_loader import load_gt  # noqa: E402
from src.evaluator import context_format_summary, load_samples_from_checkpoint  # noqa: E402
from src.provenance import read_run_meta  # noqa: E402
from src.validity import answer_failure  # noqa: E402

BUILD_ID = "b20261008_e05d3e55"
FP = {"embedder": {"tokenizer_sha": "e" * 64, "probe_ids_sha": "f" * 64, "unk_count": 3,
                   "pair_template_ok": True},
      "reranker": {"tokenizer_sha": "a" * 64, "probe_ids_sha": "b" * 64, "unk_count": 2,
                   "pair_template_ok": True}}
META = {"kind": "meta", "mode": "retrieve", "build_id": BUILD_ID, "encoder_fingerprint": FP}
GT = load_gt("v2")
Q1, Q2 = "VERSE_LOOKUP_001", "GENERAL_BIBLE_QUESTION_024"


def result(pid, book="約翰福音", chapter=3, strategy="hybrid_hybrid", fused=0.7, rr=0.5, **kw):
    return {"id": pid, "kind": "passage", "book_name": book, "chapter_num": chapter,
            "title": "標題", "verse_range": "16-21", "content": f"內容 {pid}",
            "source_strategy": strategy, "fused_score": fused, "rerank_score": rr,
            "start_key": pid[3:], "end_key": pid[3:], "passage_id": pid, "book_id": "jhn", **kw}


def arm_out(results, route="R5"):
    return {"results": results, "ctx_sha": bio.ctx_sha(results, bex.host_blocks),
            "ids": [r["id"] for r in results], "n_core": len(results),
            "stats": {"route_used": route, "strategies_used": ["semantic", "book_anchor"],
                      "strategy_errors": {}, "use_graph": True,
                      "graph_strategies": ["event_registry"], "reranked_top_k": len(results)}}


def q_row(qid, ctrl, nopin=None, off=None, skipped=None):
    return {"kind": "q", "qid": qid, "question": GT.by_id()[qid].question, "arms_skipped": skipped,
            "arms": {"ctrl": ctrl, "nopin": nopin, "off": off}}


def retrieval():
    ctrl1 = arm_out([result("ps:jhn.3.16"), result("ps:jhn.3.1", fused=None, rr=0.4),
                     result("ps:exo.40.34", book="出埃及記", chapter=40,
                            strategy="event_registry", fused=None, rr=None)])
    ctrl2 = arm_out([result("ps:isa.6.1", book="以賽亞書", chapter=6, strategy="book_anchor")])
    off2 = arm_out([result("ps:mrk.1.1", book="馬可福音", chapter=1)])
    rows = {Q1: q_row(Q1, ctrl1, skipped="book_anchor_not_invoked"),
            Q2: q_row(Q2, ctrl2, nopin=off2, off=off2)}
    return [META], rows


def test_source_fields_follow_routers_query_source():
    r = result("ps:jhn.3.16", fused=None, rr=0.25)
    assert bex.source_dict(r) == {
        "id": "ps:jhn.3.16", "book": "約翰福音", "chapter": 3, "title": "標題",
        "verse_range": "16-21", "score": 0.25, "strategy": "hybrid_hybrid", "kind": "passage",
        "start_key": "jhn.3.16", "end_key": "jhn.3.16"}
    assert bex.source_dict(result("ps:a", fused=0.8))["score"] == 0.8


def test_retr_export_reads_back_through_quick_retrieval_eval(tmp_path):
    metas, rows = retrieval()
    written = bex.export_retr(metas, rows, tmp_path / "retr")
    assert sorted(written) == ["ctrl", "nopin", "off"]
    by_arm = {}
    for arm in ("ctrl", "nopin", "off"):
        samples = qre.samples_from_raw(tmp_path / "retr" / arm / "raw_responses.json", GT.by_id())
        by_arm[arm] = {s.question_id: [src.id for src in s.sources] for s in samples}
        prov = read_run_meta(tmp_path / "retr" / arm)
        assert prov.data_build_id == BUILD_ID and dict(prov.encoder_fingerprint) == FP
    assert by_arm["ctrl"][Q1] == ["ps:jhn.3.16", "ps:jhn.3.1", "ps:exo.40.34"]
    assert by_arm["nopin"][Q1] == by_arm["off"][Q1] == by_arm["ctrl"][Q1]   # skipped → ctrl
    assert by_arm["off"][Q2] == ["ps:mrk.1.1"] and by_arm["ctrl"][Q2] == ["ps:isa.6.1"]


def plan_item(qid, arm, rep, rows):
    return {"qid": qid, "arm": arm, "rep": rep, "ctx_sha": rows[qid]["arms"][arm]["ctx_sha"]}


def gen(qid, arm, rep, rows, answer="上帝愛世人。", ok=True):
    return {"kind": "gen", "qid": qid, "arm": arm, "rep": rep, "answer": answer, "ok": ok,
            "ctx_sha": rows[qid]["arms"][arm]["ctx_sha"]}


def test_ans_export_reads_back_with_generator_blocks_and_a_failed_answer(tmp_path):
    metas, rows = retrieval()
    plan = [plan_item(Q1, "ctrl", 1, rows), plan_item(Q2, "ctrl", 1, rows),
            plan_item(Q2, "off", 1, rows)]
    failed = "生成回答時發生錯誤：ReadTimeout('')"
    gens = [gen(Q1, "ctrl", 1, rows), gen(Q2, "ctrl", 1, rows, answer=failed, ok=False),
            gen(Q2, "off", 1, rows)]
    dirs = bex.export_ans(metas, rows, gens, plan, tmp_path / "ans")
    assert sorted(dirs) == ["ctrl_r1", "off_r1"]
    raw = tmp_path / "ans" / "ctrl_r1" / "raw_responses.json"
    samples = load_samples_from_checkpoint(raw_path=raw, gt=GT)
    by_id = {s.question_id: s for s in samples}
    assert context_format_summary(samples)["context_format"] == "generator_blocks"
    assert context_format_summary(samples)["context_sources"] == {"backend": 2}
    assert by_id[Q1].contexts == bex.host_blocks(rows[Q1]["arms"]["ctrl"]["results"])
    assert by_id[Q1].contexts[0].startswith("[1] 約翰福音 第3章 - 標題 (16-21節)\n")
    assert by_id[Q2].rag_answer == failed and answer_failure(by_id[Q2]) == "generation"
    assert answer_failure(by_id[Q1]) is None
    assert read_run_meta(raw.parent).data_build_id == BUILD_ID
    items = {x["question_id"]: x for x in json.loads(raw.read_text(encoding="utf-8"))}
    assert items[Q1]["ba"] == {"arm": "ctrl", "rep": 1, "ctx_sha": rows[Q1]["arms"]["ctrl"]["ctx_sha"]}


def test_the_latest_gen_record_of_a_key_is_exported(tmp_path):
    metas, rows = retrieval()
    plan = [plan_item(Q1, "ctrl", 1, rows)]
    gens = [gen(Q1, "ctrl", 1, rows, answer="生成回答時發生錯誤。", ok=False),
            gen(Q1, "ctrl", 1, rows, answer="補跑的答案")]
    bex.export_ans(metas, rows, gens, plan, tmp_path / "ans")
    items = json.loads((tmp_path / "ans" / "ctrl_r1" / "raw_responses.json").read_text())
    assert items[0]["rag_answer"] == "補跑的答案"


def test_contexts_whose_sha_differs_raise(tmp_path):
    metas, rows = retrieval()
    rows[Q2]["arms"]["off"]["results"][0]["content"] = "改過的內容"
    with pytest.raises(bex.ExportError, match="ctx_sha"):
        bex.export_retr(metas, rows, tmp_path / "retr")


def test_a_gen_hash_or_plan_hash_that_differs_raises(tmp_path):
    metas, rows = retrieval()
    plan = [plan_item(Q1, "ctrl", 1, rows)]
    bad = {**gen(Q1, "ctrl", 1, rows), "ctx_sha": "0" * 64}
    with pytest.raises(bex.ExportError, match="ctx_sha"):
        bex.export_ans(metas, rows, [bad], plan, tmp_path / "ans")
    with pytest.raises(bex.ExportError, match="ctx_sha"):
        bex.export_ans(metas, rows, [gen(Q1, "ctrl", 1, rows)],
                       [{**plan[0], "ctx_sha": "1" * 64}], tmp_path / "ans2")


def test_a_plan_item_without_a_gen_record_raises(tmp_path):
    metas, rows = retrieval()
    with pytest.raises(bex.ExportError, match="no gen record"):
        bex.export_ans(metas, rows, [], [plan_item(Q1, "ctrl", 1, rows)], tmp_path / "ans")


def test_run_meta_needs_one_build_and_fingerprint():
    assert bex.run_meta([META, {**META, "mode": "generate"}]) == {
        "data_build_id": BUILD_ID, "encoder_fingerprint": FP}
    with pytest.raises(bex.ExportError):
        bex.run_meta([META, {**META, "build_id": "b20261008_00000000"}])
    with pytest.raises(bex.ExportError):
        bex.run_meta([{"kind": "meta", "mode": "generate", "build_id": BUILD_ID}])
