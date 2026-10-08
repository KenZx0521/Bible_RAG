"""run_eval --collect-only --ids-file / --results-dir / --overwrite (R1 G-ANS collection).

The backend is answered in-process (/health and POST /query); no LLM is reached.
"""

import json
import sys

import pytest

import run_eval
from src import collector, evaluator
from src.config import settings
from src.data_loader import load_gt
from src.metrics import coverage_eval

BUILD = "b20261008_0000abcd"
FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}}
SUBSET = ["EVENT_QUESTION_041", "VERSE_LOOKUP_001"]   # GT order is the reverse
BLOCK = "[約翰福音 3:16]\n16. 上帝愛世人"


@pytest.fixture(autouse=True)
def _results_dir_back_to_modes():
    yield
    settings.set_results_dir(None)


class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _client_class(posted: list):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            posted.append(json)
            return _Response({"answer": "a", "retrieval_stats": {"route_used": "R1"},
                              "sources": [{"id": "jhn:3:16", "book": "約翰福音", "chapter": 3,
                                           "verse_range": "16", "context": BLOCK}]})
    return _Client


def _fake_backend(monkeypatch):
    """Answer /health and /query in-process; record requests and any judge call."""
    import src.provenance

    seen = {"posted": [], "health": 0, "judged": []}

    def health(url):
        seen["health"] += 1
        return {"build_id": BUILD, "encoder": FINGERPRINT}

    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def no_sleep(*args, **kwargs):
        pass

    async def judge(*args, **kwargs):
        seen["judged"].append(args)
        return ""

    monkeypatch.setattr(collector.httpx, "AsyncClient", _client_class(seen["posted"]))
    monkeypatch.setattr(src.provenance, "fetch_health", health)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(coverage_eval, "judge_completion", judge)
    monkeypatch.setattr(evaluator, "run_evaluation", lambda *a, **k: seen["judged"].append(a))
    monkeypatch.setattr(run_eval, "_setup_logging", lambda: None)
    return seen


def _ids_file(tmp_path, ids=SUBSET):
    path = tmp_path / "gans_ids.txt"
    path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return path


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run_eval.py", *map(str, argv)])
    run_eval.main()


def _collect_args(tmp_path, out, contracts, *extra):
    return ("--collect-only", "--gt", "v2", "--contracts-dir", contracts,
            "--ids-file", _ids_file(tmp_path), "--results-dir", out, *extra)


def test_collects_only_the_subset_into_the_results_dir_with_context_blocks(
        monkeypatch, tmp_path, write_contracts):
    seen = _fake_backend(monkeypatch)
    out = tmp_path / "gans_R"

    _run(monkeypatch, *_collect_args(tmp_path, out, write_contracts(tmp_path / "contracts")))

    gt = load_gt("v2").by_id()
    raw = json.loads((out / "raw_responses.json").read_text(encoding="utf-8"))
    assert [r["question_id"] for r in raw] == ["VERSE_LOOKUP_001", "EVENT_QUESTION_041"]
    assert [p["question"] for p in seen["posted"]] == [gt[r["question_id"]].question for r in raw]
    assert all(p["include_context"] is True for p in seen["posted"])
    assert all(r["contexts"] == [BLOCK] and r["context_source"] == "backend" for r in raw)
    assert json.loads((out / "run_meta.json").read_text()) == {
        "data_build_id": BUILD, "encoder_fingerprint": FINGERPRINT}
    assert seen["judged"] == []      # collect-only reaches no LLM judge


def test_an_existing_checkpoint_is_kept_without_overwrite(monkeypatch, tmp_path, write_contracts):
    seen = _fake_backend(monkeypatch)
    out = tmp_path / "gans_R"
    out.mkdir()
    (out / "raw_responses.json").write_text('[{"question_id": "OLD", "graph_strategies": null}]')

    with pytest.raises(SystemExit, match="--overwrite"):
        _run(monkeypatch, *_collect_args(tmp_path, out, write_contracts(tmp_path / "contracts")))

    assert json.loads((out / "raw_responses.json").read_text())[0]["question_id"] == "OLD"
    assert seen["health"] == 0 and seen["posted"] == []


def test_overwrite_replaces_the_checkpoint(monkeypatch, tmp_path, write_contracts):
    _fake_backend(monkeypatch)
    out = tmp_path / "gans_R"
    out.mkdir()
    (out / "raw_responses.json").write_text('[{"question_id": "OLD", "graph_strategies": null}]')

    _run(monkeypatch, *_collect_args(tmp_path, out, write_contracts(tmp_path / "contracts"),
                                     "--overwrite"))

    raw = json.loads((out / "raw_responses.json").read_text())
    assert {r["question_id"] for r in raw} == set(SUBSET)


def test_unknown_ids_are_refused_before_anything_is_asked_or_written(
        monkeypatch, tmp_path, write_contracts):
    seen = _fake_backend(monkeypatch)
    out = tmp_path / "gans_R"
    contracts = write_contracts(tmp_path / "contracts")
    ids = _ids_file(tmp_path, ["VERSE_LOOKUP_001", "NOPE_001"])

    with pytest.raises(SystemExit, match="NOPE_001"):
        _run(monkeypatch, "--collect-only", "--gt", "v2", "--contracts-dir", contracts,
             "--ids-file", ids, "--results-dir", out)

    assert seen["posted"] == [] and not out.exists()


def test_a_relative_results_dir_resolves_under_evaluation(monkeypatch, tmp_path, write_contracts):
    _fake_backend(monkeypatch)
    monkeypatch.setattr(run_eval, "EVAL_ROOT", tmp_path)

    _run(monkeypatch, *_collect_args(tmp_path, "rel/gans_A1", write_contracts(tmp_path / "c")))

    assert (tmp_path / "rel" / "gans_A1" / "raw_responses.json").exists()
    assert settings.results_dir == tmp_path / "rel" / "gans_A1"


@pytest.mark.parametrize("argv", [
    ["--collect-only", "--overwrite"],
    ["--eval-only", "--ids-file", "IDS"],
    ["--visualize-only", "--ids-file", "IDS"],
    ["--collect-only", "--ids-file", "EMPTY"],
], ids=["overwrite_without_results_dir", "ids_with_eval_only", "ids_with_visualize_only",
        "empty_ids_file"])
def test_flag_combinations_that_do_not_add_up_are_usage_errors(monkeypatch, tmp_path, argv):
    (tmp_path / "empty.txt").write_text("\n")
    paths = {"IDS": str(_ids_file(tmp_path)), "EMPTY": str(tmp_path / "empty.txt")}
    monkeypatch.setattr(sys, "argv", ["run_eval.py", *(paths.get(a, a) for a in argv)])

    with pytest.raises(SystemExit) as exited:
        run_eval._parse_args()
    assert exited.value.code == 2
