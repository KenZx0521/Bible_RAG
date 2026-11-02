"""run_eval's arms: no flag = the main architecture; --no-graph and --semantic are its ablations."""
import sys

import pytest

import quick_retrieval_eval
import run_eval
from src import run_record as rr
from src.config import _EVAL_ROOT, Settings


def _parse(monkeypatch, *flags):
    monkeypatch.setattr(sys, "argv", ["run_eval.py", *flags])
    return run_eval._parse_args()


def test_no_flag_asks_for_the_main_architecture_explicitly(monkeypatch):
    assert _parse(monkeypatch).use_graph is True


def test_no_graph_turns_the_graph_side_off(monkeypatch):
    assert _parse(monkeypatch, "--no-graph").use_graph is False


def test_removed_graph_flag_is_refused_not_read_as_graph_strategies(monkeypatch):
    """argparse would otherwise expand --graph to --graph-strategies with no value: every
    graph strategy silently off."""
    with pytest.raises(SystemExit) as refused:
        _parse(monkeypatch, "--graph")
    assert refused.value.code == 2


def test_graph_strategies_still_needs_its_full_name(monkeypatch):
    args = _parse(monkeypatch, "--graph-strategies", "event_registry", "--results-dir", "variant")
    assert args.graph_strategies == ["event_registry"]


@pytest.mark.parametrize("flags", [("--ids-file", "smoke.txt"), ("--graph-strategies",),
                                   ("--graph-strategies", "event_registry")])
def test_a_subset_or_variant_must_name_its_own_directory(monkeypatch, tmp_path, flags):
    """Without one it would replace the arm's full run in results/, and be labelled main."""
    (tmp_path / "smoke.txt").write_text("VERSE_LOOKUP_001\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as refused:
        _parse(monkeypatch, "--collect-only", *flags)
    assert refused.value.code == 2


def test_quick_retrieval_eval_refuses_the_same_abbreviation(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["quick_retrieval_eval.py", "--graph"])
    with pytest.raises(SystemExit) as refused:
        quick_retrieval_eval._parse_args()
    assert refused.value.code == 2


@pytest.mark.parametrize("flags, label", [
    ((), "main"), (("--no-graph",), "no-graph"), (("--semantic",), "semantic-only"),
    (("--eval-only",), "as collected"), (("--visualize-only",), "as collected"),
    (("--eval-only", "--results-dir", "results_semantic"), "as collected")])
def test_the_banner_names_the_arm_only_when_it_collects_one(monkeypatch, flags, label):
    assert run_eval._arm_label(_parse(monkeypatch, *flags)).startswith(label)


def test_semantic_cannot_be_combined_with_no_graph(monkeypatch):
    with pytest.raises(SystemExit) as refused:
        _parse(monkeypatch, "--semantic", "--no-graph")
    assert refused.value.code == 2


@pytest.mark.parametrize("use_graph, semantic, sent", [
    (True, False, True), (False, False, False), (True, True, None)])
def test_request_use_graph_by_arm(use_graph, semantic, sent):
    """The semantic arm's request stays without use_graph, as it always was."""
    args = type("Args", (), {"use_graph": use_graph, "semantic": semantic})
    assert run_eval._request_use_graph(args) is sent


@pytest.mark.parametrize("use_graph, semantic, directory", [
    (True, False, "results"), (None, False, "results"),
    (False, False, "results_no_graph"), (True, True, "results_semantic")])
def test_each_arm_writes_to_its_own_directory(use_graph, semantic, directory):
    config = Settings()
    config.set_graph_mode(use_graph)
    config.set_semantic_mode(semantic)
    assert config.results_dir == _EVAL_ROOT / directory


def test_main_arm_is_labelled_main():
    assert rr.collection_mode(True, False) == "main"
