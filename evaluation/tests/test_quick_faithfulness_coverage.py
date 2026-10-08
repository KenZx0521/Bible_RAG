"""quick_faithfulness_eval --ids-file / --coverage: a G-ANS checkpoint's subset, coverage added alongside.

The faithfulness judge and the coverage judge's LLM call are stubbed; no LLM is reached.
"""

import json
import sys

import pytest

import quick_faithfulness_eval as qfe
from src.data_loader import load_gt
from src.metrics import coverage_eval
from src.models import MetricResult

GT = load_gt("v2").by_id()

COVERED = json.dumps({"verdicts": [{"index": i, "verdict": "covered"} for i in range(1, 9)]})


SOURCE = {"id": "jhn:3:16", "book": "約翰福音", "strategy": "hybrid"}


def _item(qid, answer="a", errors=None, sources=()):
    return {"question_id": qid, "question": "q", "rag_answer": answer,
            "contexts": ["c"] if answer else [], "context_source": "backend" if answer else "",
            "sources": list(sources), "strategy_errors": errors or {}}


def _checkpoint(directory, items=None):
    """Default: two answered questions and one infrastructure failure (request error, no answer)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_responses.json").write_text(json.dumps(items or [
        _item("VERSE_LOOKUP_001"), _item("VERSE_LOOKUP_002"),
        _item("VERSE_LOOKUP_003", answer="", errors={"request": "ConnectTimeout()"})]))
    (directory / "run_meta.json").write_text(json.dumps(
        {"data_build_id": "legacy-20261004", "encoder_fingerprint": None}))
    return directory


def _stub_judges(monkeypatch, failing=()):
    """zh + strict faithfulness 1.0 for every answered sample; coverage judge answers
    'covered' or fails."""
    prompts = {}

    def faith(samples):
        return {s.question_id: [MetricResult(name=name, value=1.0, category="llm_judge")
                                for name in ("ragas_faithfulness", "ragas_faithfulness_strict")]
                for s in samples if s.rag_answer}, {}

    async def judge(prompt, **kwargs):
        qid = next(q for q, item in GT.items() if f"【問題】\n{item.question}\n" in prompt)
        prompts[qid] = prompt
        if qid in failing:
            raise RuntimeError("judge down")
        return COVERED

    monkeypatch.setattr(qfe, "_judge", faith)
    monkeypatch.setattr(coverage_eval, "judge_completion", judge)
    return prompts


def _main(monkeypatch, tmp_path, *argv, items=None):
    out = tmp_path / f"out{len(list(tmp_path.glob('out*.json')))}.json"
    run = _checkpoint(tmp_path / "run", items)
    monkeypatch.setattr(sys, "argv", ["quick_faithfulness_eval.py", "--no-rebuild", "--gt", "v2",
                                      "--results-dir", str(run),
                                      "--out", str(out), *map(str, argv)])
    qfe.main()
    return json.loads(out.read_text(encoding="utf-8"))


def _without_coverage(report):
    meta = {k: v for k, v in report["meta"].items()
            if k not in ("timestamp", "coverage_enabled", "n_coverage_scored")}
    overall = {k: v for k, v in report["overall"].items() if k != "coverage"}
    rows = [{k: v for k, v in r.items() if k != "coverage"} for r in report["samples"]]
    return {**report, "meta": meta, "overall": overall, "samples": rows}


def test_coverage_is_added_per_row_and_overall_leaving_every_other_field(monkeypatch, tmp_path):
    _stub_judges(monkeypatch)

    plain = _main(monkeypatch, tmp_path)
    covered = _main(monkeypatch, tmp_path, "--coverage")

    assert "coverage" not in plain["overall"] and "coverage" not in plain["samples"][0]
    assert "coverage_enabled" not in plain["meta"]
    assert _without_coverage(covered) == _without_coverage(plain)
    assert [r["coverage"] for r in covered["samples"]] == [1.0, 1.0, None]
    assert covered["overall"]["coverage"] == 1.0
    assert covered["meta"]["coverage_enabled"] is True
    assert covered["meta"]["n_coverage_scored"] == 2


def test_coverage_judges_the_gt_v2_answer_points(monkeypatch, tmp_path):
    prompts = _stub_judges(monkeypatch)

    _main(monkeypatch, tmp_path, "--coverage", "--ids", "VERSE_LOOKUP_001")

    assert "上帝愛世人" in prompts["VERSE_LOOKUP_001"]     # v2 wording
    assert "神愛世人" not in prompts["VERSE_LOOKUP_001"]   # v1 wording


def test_a_failed_coverage_judge_is_null_and_left_out_of_the_mean(monkeypatch, tmp_path):
    _stub_judges(monkeypatch, failing=("VERSE_LOOKUP_002",))

    out = _main(monkeypatch, tmp_path, "--coverage")

    assert [r["coverage"] for r in out["samples"]] == [1.0, None, None]
    assert out["overall"]["coverage"] == 1.0 and out["meta"]["n_coverage_scored"] == 1


def test_generation_and_infra_failures_are_invalid_rows_out_of_every_mean(monkeypatch, tmp_path):
    """prereg G-ANS n_invalid (生成失敗): the backend's generation-error answers (HTTP 200,
    sources kept) and a failed auxiliary lane get no faithfulness and no coverage, so the
    gate counts them and strict / coverage means cover the same samples."""
    _stub_judges(monkeypatch)
    items = [_item("VERSE_LOOKUP_001", sources=[SOURCE]),
             _item("VERSE_LOOKUP_002", answer="生成回答時發生錯誤：ReadTimeout('')", sources=[SOURCE]),
             _item("VERSE_LOOKUP_003", errors={"event_registry": "ConnectError()"}, sources=[SOURCE]),
             _item("VERSE_LOOKUP_004", answer="生成回答時發生錯誤。", sources=[SOURCE])]

    out = _main(monkeypatch, tmp_path, "--coverage", items=items)

    rows = out["samples"]
    assert [r["invalid"] for r in rows] == [None, "generation", "infra", "generation"]
    for field in ("ragas_faithfulness", "ragas_faithfulness_strict", "coverage"):
        assert [r[field] for r in rows] == [1.0, None, None, None], field
    assert out["meta"]["invalid_samples"] == {"VERSE_LOOKUP_002": "generation",
                                              "VERSE_LOOKUP_003": "infra",
                                              "VERSE_LOOKUP_004": "generation"}
    assert out["meta"]["n_scored"] == out["meta"]["n_coverage_scored"] == 1


@pytest.mark.parametrize("content", ['["VERSE_LOOKUP_002"]', "VERSE_LOOKUP_002\n"],
                         ids=["json_list", "one_per_line"])
def test_ids_file_selects_the_samples(monkeypatch, tmp_path, content):
    _stub_judges(monkeypatch)
    ids = tmp_path / "ids.txt"
    ids.write_text(content, encoding="utf-8")

    out = _main(monkeypatch, tmp_path, "--ids-file", ids)

    assert [r["question_id"] for r in out["samples"]] == ["VERSE_LOOKUP_002"]


@pytest.mark.parametrize("content, extra", [
    ("VERSE_LOOKUP_001\nNOPE_001\n", []),
    ("", []),
    ("VERSE_LOOKUP_001\n", ["--ids", "VERSE_LOOKUP_001"]),
], ids=["unknown_id", "empty_file", "with_ids"])
def test_bad_ids_files_exit_non_zero(monkeypatch, tmp_path, content, extra):
    _stub_judges(monkeypatch)
    ids = tmp_path / "ids.txt"
    ids.write_text(content, encoding="utf-8")

    with pytest.raises(SystemExit) as exited:
        _main(monkeypatch, tmp_path, "--ids-file", ids, *extra)
    assert exited.value.code != 0
