"""What a collection's graph side did: per question (raw, CSV) and in total (run_meta, console)."""
import asyncio
import csv
import json

import pytest

from src import collector, evaluator, graph_usage
from src.models import AggregatedReport, EvalReport, EvalSample, GroundTruthItem

WALK = {"op": "gen_card", "hops": 2, "nodes": ["a", "b", "c"],
        "edges": [["a", "son", "b"], ["b", "son", "c"]], "injected": "prompt", "passages": []}
LOOKUP = {"op": "event_registry", "hops": 1, "nodes": ["ev1"], "edges": [["ev1", "anchor", "ps:x"]],
          "injected": "context", "passages": ["ps:x"]}
IDLE = {"op": "event_registry", "hops": 0, "nodes": ["ev1"], "edges": [], "injected": "none", "passages": []}


def test_a_reported_trace_is_taken_as_it_is():
    assert graph_usage.ops_of({"graph_trace": [WALK], "sources": [], "aux_card": None}) == [WALK]


def test_an_empty_reported_trace_stays_empty():
    assert graph_usage.ops_of({"graph_trace": [], "sources": [{"strategy": "event_registry"}]}) == []


def test_an_old_checkpoint_is_read_back_from_its_sources_and_card():
    record = {"event_registry_events": ["ev1"],
              "sources": [{"id": "ps:a", "strategy": "semantic"}, {"id": "ps:x", "strategy": "event_registry"}],
              "aux_card": {"kind": "gen", "kings": ["a", "c"]}}

    assert graph_usage.ops_of(record) == [
        {"op": "event_registry", "hops": 1, "nodes": ["ev1"], "edges": [], "injected": "context",
         "passages": ["ps:x"]},
        {"op": "gen_card", "hops": None, "nodes": ["a", "c"], "edges": [], "injected": "prompt", "passages": []}]


def test_a_failed_request_has_no_operations():
    assert graph_usage.ops_of({"graph_trace": None, "sources": [], "aux_card": None}) == []


def test_only_a_walk_of_two_hops_that_reached_the_answer_counts():
    assert graph_usage.is_walk(WALK)
    assert not graph_usage.is_walk(LOOKUP)
    assert not graph_usage.is_walk({**WALK, "injected": "none"})
    assert not graph_usage.is_walk({**WALK, "hops": None})


def test_summarize_counts_questions_not_operations():
    records = [{"graph_trace": [WALK, LOOKUP]}, {"graph_trace": [LOOKUP]}, {"graph_trace": [IDLE]},
               {"graph_trace": []},
               {"graph_trace": None, "sources": [], "aux_card": {"kind": "regnal", "kings": ["k"]}}]

    usage = graph_usage.summarize(records)

    assert usage == {
        "n_questions": 5, "n_failed": 0, "n_trace_reported": 4, "n_with_op": 4, "n_injected": 3, "n_walk": 1,
        "n_hops_unknown": 1, "n_nodes": 7, "n_edges": 4, "n_cypher": 0, "skipped": {},
        "by_op": {"event_registry": {"n_questions": 3, "n_injected": 2, "max_hops": 1},
                  "gen_card": {"n_questions": 1, "n_injected": 1, "max_hops": 2},
                  "regnal_card": {"n_questions": 1, "n_injected": 1, "max_hops": None}}}


GRAPH_WALK = {"op": "graph_walk", "hops": 4, "nodes": ["nm:x", "ps:a"], "edges": [], "injected": "context",
              "passages": ["ps:a"], "seeds": ["ps:a"], "names": ["甲"], "walked": ["ps:a"], "n_cypher": 2, "ms": 3.0,
              "skip_reason": None}
KIN_CARD = {"op": "kin_card", "hops": 3, "nodes": ["e1", "e2"], "edges": [["e1", "PARENT_OF", "e2", "gen.1.1"]],
            "injected": "prompt", "passages": ["ps:gen.1.1"], "seeds": [], "names": ["甲", "乙"], "walked": [],
            "n_cypher": 3, "ms": 2.0, "skip_reason": None}
SKIPPED_WALK = {"op": "graph_walk", "hops": 0, "nodes": [], "edges": [], "injected": "none", "passages": [],
                "seeds": [], "names": [], "walked": [], "n_cypher": 0, "ms": 0.0, "skip_reason": "unavailable"}
NO_EDGE = {**KIN_CARD, "hops": 0, "nodes": [], "edges": [], "injected": "none", "passages": [], "names": [],
           "skip_reason": "no_edge"}


def test_a_graph_walk_and_a_kinship_card_count_as_walks():
    assert graph_usage.is_walk(GRAPH_WALK) and graph_usage.is_walk(KIN_CARD)
    assert not graph_usage.is_walk(SKIPPED_WALK) and not graph_usage.is_walk(NO_EDGE)


def test_summarize_counts_the_new_operations_their_cypher_and_why_they_gave_nothing():
    usage = graph_usage.summarize([{"graph_trace": [GRAPH_WALK, KIN_CARD]}, {"graph_trace": [SKIPPED_WALK, NO_EDGE]}])

    assert (usage["n_walk"], usage["n_injected"], usage["n_with_op"], usage["n_cypher"]) == (1, 1, 2, 8)
    assert usage["skipped"] == {"graph_walk": {"unavailable": 1}, "kin_card": {"no_edge": 1}}
    assert usage["by_op"]["graph_walk"] == {"n_questions": 2, "n_injected": 1, "max_hops": 4}
    assert usage["by_op"]["kin_card"] == {"n_questions": 2, "n_injected": 1, "max_hops": 3}


def test_the_report_says_why_an_operation_gave_nothing():
    usage = graph_usage.summarize([{"graph_trace": [SKIPPED_WALK]}, {"graph_trace": [SKIPPED_WALK]}])
    lines = graph_usage.report_lines(usage, "main")
    assert any("graph_walk" in line and "unavailable" in line and "2" in line for line in lines)


def test_a_main_arm_whose_neo4j_was_down_is_warned_that_nothing_walked():
    usage = graph_usage.summarize([{"graph_trace": [SKIPPED_WALK]}])
    assert any("沒有任何題走到圖譜走訪" in line for line in graph_usage.report_lines(usage, "main"))


def test_an_old_checkpoints_kinship_card_is_read_back():
    ops = graph_usage.ops_of({"graph_trace": None, "sources": [], "aux_card": {"kind": "kin", "kings": ["e1"]}})
    assert [(op["op"], op["hops"], op["injected"]) for op in ops] == [("kin_card", None, "prompt")]


def test_the_main_arm_is_warned_when_nothing_walked():
    usage = graph_usage.summarize([{"graph_trace": [LOOKUP]}])
    assert any("沒有任何題走到圖譜走訪" in line for line in graph_usage.report_lines(usage, "main"))


def test_a_walk_silences_the_warning_and_is_counted():
    lines = graph_usage.report_lines(graph_usage.summarize([{"graph_trace": [WALK]}]), "main")
    assert not any("沒有任何題" in line for line in lines)
    assert any("1/1" in line for line in lines)


@pytest.mark.parametrize("mode", ["no_graph", "semantic"])
def test_an_ablation_arm_is_not_warned(mode):
    lines = graph_usage.report_lines(graph_usage.summarize([{"graph_trace": []}]), mode)
    assert not any("沒有任何題" in line for line in lines)


def test_the_report_says_when_the_backend_did_not_report():
    usage = graph_usage.summarize([{"graph_trace": None, "sources": [], "aux_card": None}])
    assert any("0/1" in line and "回報" in line for line in graph_usage.report_lines(usage, "main"))


def test_a_failed_request_is_not_called_read_back():
    records = [{"graph_trace": []}, {"graph_trace": None, "strategy_errors": {"request": "ReadTimeout"}}]

    usage = graph_usage.summarize(records)
    lines = graph_usage.report_lines(usage, "main")

    assert (usage["n_failed"], usage["n_trace_reported"]) == (1, 1)
    assert not any("推得" in line for line in lines)
    assert "0/1" in lines[0] and any("1 題" in line and "失敗" in line for line in lines)


def test_all_failed_says_so_and_does_not_blame_the_graph():
    usage = graph_usage.summarize([{"graph_trace": None, "strategy_errors": {"request": "x"}}] * 3)
    lines = graph_usage.report_lines(usage, "main")
    assert len(lines) == 1 and "3 題" in lines[0] and "失敗" in lines[0]


def test_a_card_whose_answer_failed_did_not_reach_an_answer():
    """The generator answers HTTP 200 with its error text; the card did reach the prompt."""
    usage = graph_usage.summarize([{"graph_trace": [WALK], "rag_answer": "生成回答時發生錯誤：vllm down"}])
    assert (usage["n_failed"], usage["n_walk"], usage["n_injected"], usage["n_with_op"]) == (1, 0, 0, 0)
    assert usage["by_op"] == {}


# --- the collector ----------------------------------------------------------------------------

GT = GroundTruthItem(question_id="Q1", question="q", question_type="X", book_name="約翰福音", reference_answer="a")


def _collect(monkeypatch, tmp_path, body, use_graph=True):
    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def query(*args, **kwargs):
        return body

    async def no_sleep(*args, **kwargs):
        pass

    printed = []
    monkeypatch.setattr(collector, "query_rag", query)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(type(collector.settings), "results_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(collector.console, "print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    samples, _ = asyncio.run(collector.collect_responses([GT], use_graph=use_graph))
    return samples, json.loads((tmp_path / "raw_responses.json").read_text(encoding="utf-8")), printed


def _body(trace):
    body = {"answer": "a", "sources": [], "retrieval_stats": {"route_used": "R4"},
            "intent": {"type": "event"}}
    return body if trace == "absent" else {**body, "graph_trace": trace}


def test_each_record_keeps_the_trace_and_the_sample_too(monkeypatch, tmp_path):
    samples, raw, _ = _collect(monkeypatch, tmp_path, _body([WALK]))
    assert raw[0]["graph_trace"] == [WALK]
    assert samples[0].graph_trace == [WALK]


def test_a_backend_that_does_not_report_leaves_it_null(monkeypatch, tmp_path):
    samples, raw, _ = _collect(monkeypatch, tmp_path, _body("absent"))
    assert raw[0]["graph_trace"] is None and samples[0].graph_trace is None


def test_the_collection_prints_its_graph_usage(monkeypatch, tmp_path):
    _, _, printed = _collect(monkeypatch, tmp_path, _body([]))
    assert any("沒有任何題走到圖譜走訪" in line for line in printed)


def test_run_meta_records_the_usage():
    from src import run_record as rr
    record = {"collection": {"mode": "main"}}
    done = rr.finish_record(record, n_collected=1, n_request_failures=0,
                            graph_usage=graph_usage.summarize([{"graph_trace": [WALK]}]))
    assert done["collection"]["graph_usage"]["n_walk"] == 1


# --- the checkpoint and the CSV ---------------------------------------------------------------

def test_the_checkpoint_gives_the_trace_back(monkeypatch, tmp_path):
    (tmp_path / "raw_responses.json").write_text(json.dumps([
        {"question_id": "VERSE_LOOKUP_001", "question": "q", "rag_answer": "a", "contexts": ["c"],
         "context_source": "backend", "sources": [], "graph_trace": [WALK]},
        {"question_id": "VERSE_LOOKUP_002", "question": "q", "rag_answer": "a", "contexts": ["c"],
         "context_source": "backend", "sources": []}]))
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))
    items = {q: GroundTruthItem(question_id=q, question="q", question_type="X", book_name="約翰福音")
             for q in ("VERSE_LOOKUP_001", "VERSE_LOOKUP_002")}

    samples = evaluator.load_samples_from_checkpoint(gt=type("GT", (), {"by_id": lambda self: items})())

    assert [s.graph_trace for s in samples] == [[WALK], None]


@pytest.mark.parametrize("trace, ops, hops", [
    ([WALK, LOOKUP], "gen_card|event_registry", "2"), ([], "", "0"), (None, "", "")])
def test_csv_appends_the_graph_columns_last(monkeypatch, tmp_path, trace, ops, hops):
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))
    report = AggregatedReport(samples=[EvalReport(question_id="Q1", question_type="X", graph_trace=trace)])

    path = evaluator.export_csv(report)

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0][-2:] == ["graph_ops", "graph_max_hops"]
    assert rows[1][-2:] == [ops, hops]


def test_eval_sample_defaults_to_unreported():
    assert EvalSample(question_id="Q", question="q", question_type="X", rag_answer="a", contexts=[],
                      sources=[], ground_truth=GT).graph_trace is None


def _usage_skipping(n_skipped: int, n: int = 100) -> dict:
    return {"n_questions": n, "n_failed": 0, "n_walk": n - n_skipped, "n_injected": n - n_skipped,
            "n_with_op": n, "n_nodes": 0, "n_edges": 0, "by_op": {}, "n_trace_reported": n, "n_hops_unknown": 0,
            "skipped": {"graph_walk": {"timeout": n_skipped}} if n_skipped else {}}


def test_the_main_arm_is_warned_when_the_graph_was_off_for_many_questions():
    lines = graph_usage.report_lines(_usage_skipping(6), "main")
    assert any("graph_walk 有 6/100 題沒跑成" in line for line in lines)


def test_a_few_skips_are_listed_but_do_not_warn():
    lines = graph_usage.report_lines(_usage_skipping(5), "main")
    assert not any("沒跑成" in line for line in lines)
    assert any("graph_walk 沒有結果：timeout 5 題" in line for line in lines)


def test_a_control_arm_is_not_warned_about_skips():
    assert not any("沒跑成" in line for line in graph_usage.report_lines(_usage_skipping(50), "no_graph"))
