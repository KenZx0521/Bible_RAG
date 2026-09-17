"""
Checkpoint context resolution and run provenance for the judge context format.
"""

from src.evaluator import _resolve_checkpoint_contexts, context_format_summary
from src.models import EvalSample, GroundTruthItem


def _sample(source: str, contexts=("[1] b\nx",)) -> EvalSample:
    gt = GroundTruthItem(question_id="Q", question="q", question_type="VERSE_LOOKUP", book_name="b")
    return EvalSample(question_id="Q", question="q", question_type="VERSE_LOOKUP",
                      ground_truth=gt, context_source=source, contexts=list(contexts))


def test_resolve_prefers_generator_blocks():
    item = {"question_id": "Q", "contexts": ["old"], "context_source": "backend"}
    assert _resolve_checkpoint_contexts(item, ["[1] b\nnew"], None) == (["[1] b\nnew"], "backend")


def test_resolve_zero_source_new_format_keeps_tag():
    item = {"question_id": "Q", "contexts": [], "context_source": "rebuilt", "sources": []}
    assert _resolve_checkpoint_contexts(item, [], None) == ([], "rebuilt")


def test_resolve_uses_rebuilt_when_complete():
    item = {"question_id": "Q", "contexts": ["p1", "p2"]}
    assert _resolve_checkpoint_contexts(item, None, ["[1] b\np1", "[2] b\np2"]) == (
        ["[1] b\np1", "[2] b\np2"], "rebuilt")


def test_resolve_keeps_stored_text_when_rebuild_is_short_or_empty():
    item = {"question_id": "Q", "contexts": ["p1", "p2"]}
    assert _resolve_checkpoint_contexts(item, None, ["[1] b\np1"]) == (["p1", "p2"], "legacy_headerless")
    assert _resolve_checkpoint_contexts(item, None, []) == (["p1", "p2"], "legacy_headerless")


def test_resolve_legacy_without_rebuild():
    item = {"question_id": "Q", "contexts": ["p1"]}
    assert _resolve_checkpoint_contexts(item, None, None) == (["p1"], "legacy_headerless")


def test_context_format_summary():
    assert context_format_summary([_sample("backend"), _sample("rebuilt")]) == {
        "context_format": "generator_blocks", "context_sources": {"backend": 1, "rebuilt": 1},
        "unjudged_samples": 0}
    assert context_format_summary([_sample("")])["context_format"] == "headerless"
    assert context_format_summary([_sample("backend"), _sample("legacy_headerless")])["context_format"] == "mixed"


def test_context_format_summary_ignores_samples_the_judge_never_sees():
    # API-failure samples (no contexts, no tag) must not flip a generator-block run to "mixed"
    out = context_format_summary([_sample("backend"), _sample("", contexts=())])
    assert out == {"context_format": "generator_blocks", "context_sources": {"backend": 1}, "unjudged_samples": 1}
    assert context_format_summary([])["context_format"] == "none"


def test_dedupe_by_question_id_keeps_first_and_reports_dropped():
    from src.evaluator import dedupe_by_question_id
    kept, dropped = dedupe_by_question_id([{"question_id": "A", "v": 1}, {"question_id": "B"}, {"question_id": "A", "v": 2}])
    assert [i["question_id"] for i in kept] == ["A", "B"] and kept[0]["v"] == 1
    assert dropped == ["A"]
