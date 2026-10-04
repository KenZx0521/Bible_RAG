"""D3 non-inferiority gate (KG batch 1 plan §5.1).

Two backends answer the same 500 questions; every same-route question must
retrieve identical passages and context, route mismatches are re-asked on
both sides (at most two rounds), and what is still routed differently must
stay within the residual r0 measured by the W0 AA run.
"""

import copy
import json
import sys
from collections import Counter

import pytest

import d3_gate as gate

CORE = [f"a:{i}:0" for i in range(5)]
OTHER = ["x:1:0"] + CORE[1:]
PROD = "http://localhost:8000"
STG = "http://localhost:8001"
ARMS = (gate.Arm("prod", PROD, "d3_prod_w1"), gate.Arm("stg", STG, "d3_stg_w1"))


def _entry(ids=CORE, route="R4", invalid=False, strategies=("event_registry",)):
    return {
        "sources": list(ids), "route": route, "invalid": invalid,
        "source_detail": [{"id": i, "context_sha256": f"sha-{i}"} for i in ids],
        "context_sha": "ctx-" + "|".join(ids),
        "graph_strategies": list(strategies),
    }


def _run(per_question, **config):
    applied = Counter(",".join(e["graph_strategies"]) for e in per_question.values())
    return {
        "config": {"top_k": 5, "metric_k": 6, "metric_version": "v1", "include_context": True,
                   "use_graph": True, "fusion_alpha": None, "graph_strategies_requested": None,
                   "graph_strategies_applied": dict(applied), "ids_file": None, **config},
        "n": len(per_question),
        "n_invalid": sum(e["invalid"] for e in per_question.values()),
        "per_question": per_question,
    }


class FakeRunner:
    """Answers each backend from a script of full runs, one per call, sliced to the asked ids."""

    def __init__(self, script):
        self.script = {url: list(runs) for url, runs in script.items()}
        self.calls = []

    def __call__(self, url, label, ids):
        self.calls.append((url, label, None if ids is None else list(ids)))
        run = self.script[url].pop(0)
        if ids is None:
            return run
        return {**run, "config": {**run["config"], "ids_file": "ids.txt"},
                "per_question": {q: run["per_question"][q] for q in ids}}


def _agreeing_pair():
    run = _run({"Q1": _entry(), "Q2": _entry()})
    return run, copy.deepcopy(run)


# --- merge: re-asked answers patch the original run --------------------------

def test_merge_rerun_replaces_only_reasked_entries_without_mutating():
    base = _run({"Q1": _entry(), "Q2": _entry(route="R3")})
    rerun = _run({"Q2": _entry(OTHER, route="R4", invalid=True,
                               strategies=("graph_event",))})
    before = copy.deepcopy(base)

    merged = gate.merge_rerun(base, rerun, ["Q2"])

    assert base == before
    assert merged["per_question"]["Q1"] == base["per_question"]["Q1"]
    assert merged["per_question"]["Q2"]["sources"] == OTHER
    assert merged["config"]["graph_strategies_applied"] == {"event_registry": 1, "graph_event": 1}
    assert merged["n_invalid"] == 1
    assert merged["config"]["reasked"] == [["Q2"]]


@pytest.mark.parametrize("rerun_ids, asked, match", [
    (["Q1"], ["Q2"], "Q1"),                            # answered something else
    (["Q2", "Q3"], ["Q2"], "Q3"),                      # answered more than asked
])
def test_merge_rerun_refuses_reruns_that_answered_other_questions(rerun_ids, asked, match):
    base = _run({"Q1": _entry(), "Q2": _entry()})
    rerun = _run({q: _entry() for q in rerun_ids})

    with pytest.raises(ValueError, match=match):
        gate.merge_rerun(base, rerun, asked)


# Every setting a re-ask must share with the run it patches, each with a value
# that differs from _run's. Listed literally: dropping a key from
# gate._MERGE_KEYS must make its case fail.
DIFFERENT_SETTINGS = {
    "top_k": 6, "metric_k": 5, "metric_version": "v2", "include_context": False,
    "use_graph": False, "fusion_alpha": 0.3, "graph_strategies_requested": ["graph_event"],
}


@pytest.mark.parametrize("key, value", DIFFERENT_SETTINGS.items())
def test_merge_rerun_refuses_reruns_with_different_settings(key, value):
    base = _run({"Q1": _entry(), "Q2": _entry()})
    rerun = _run({"Q2": _entry()}, **{key: value})

    with pytest.raises(ValueError, match=key):
        gate.merge_rerun(base, rerun, ["Q2"])


def test_every_merge_key_has_a_refusal_case():
    assert set(DIFFERENT_SETTINGS) == set(gate._MERGE_KEYS)


def test_merge_rerun_refuses_ids_the_original_run_never_asked():
    with pytest.raises(ValueError, match="Q9"):
        gate.merge_rerun(_run({"Q1": _entry()}), _run({"Q9": _entry()}), ["Q9"])


# --- live mode: re-asking route mismatches ------------------------------------

def test_gate_without_route_mismatch_runs_each_backend_once():
    control, treat = _agreeing_pair()
    runner = FakeRunner({PROD: [control], STG: [treat]})

    report = gate.run_live(runner, *ARMS, residual_max=0)

    assert report["passed"] is True
    assert runner.calls == [(PROD, "d3_prod_w1", None), (STG, "d3_stg_w1", None)]
    assert report["rounds"] == []


def test_gate_reasks_route_mismatches_and_passes_once_they_agree():
    runner = FakeRunner({
        PROD: [_run({"Q1": _entry(), "Q2": _entry(route="R3")}),
               _run({"Q1": _entry(), "Q2": _entry(route="R4")})],
        STG: [_run({"Q1": _entry(), "Q2": _entry(OTHER, route="R4")}),
              _run({"Q1": _entry(), "Q2": _entry(route="R4")})],
    })

    report = gate.run_live(runner, *ARMS, residual_max=0)

    assert runner.calls[2:] == [(PROD, "d3_prod_w1_retry1", ["Q2"]),
                                (STG, "d3_stg_w1_retry1", ["Q2"])]
    assert report["rounds"][0]["asked"] == ["Q2"]
    assert report["rounds"][0]["still_route_mismatch"] == []
    assert report["route_residual"] == []
    assert report["identity"]["identical"] == 2
    assert report["passed"] is True


def _always_split(rounds):
    """Q2 is routed R3 on prod and R4 on staging in every round."""
    return FakeRunner({
        PROD: [_run({"Q1": _entry(), "Q2": _entry(route="R3")})] * rounds,
        STG: [_run({"Q1": _entry(), "Q2": _entry(OTHER, route="R4")})] * rounds,
    })


@pytest.mark.parametrize("r0, passed", [(1, True), (0, False)])
def test_gate_stops_after_two_rounds_and_judges_residual_against_r0(r0, passed):
    runner = _always_split(rounds=3)

    report = gate.run_live(runner, *ARMS, residual_max=r0)

    assert [label for _, label, _ in runner.calls] == [
        "d3_prod_w1", "d3_stg_w1", "d3_prod_w1_retry1", "d3_stg_w1_retry1",
        "d3_prod_w1_retry2", "d3_stg_w1_retry2",
    ]
    assert report["route_residual"] == ["Q2"]
    assert report["criteria"]["route_residual_within_r0"] is passed
    assert report["passed"] is passed


def test_reasked_question_that_agrees_on_route_must_be_identical():
    runner = FakeRunner({
        PROD: [_run({"Q1": _entry(), "Q2": _entry(route="R3")}),
               _run({"Q1": _entry(), "Q2": _entry(route="R4")})],
        STG: [_run({"Q1": _entry(), "Q2": _entry(route="R4")}),
              _run({"Q1": _entry(), "Q2": _entry(OTHER, route="R4")})],
    })

    report = gate.run_live(runner, *ARMS, residual_max=5)

    assert report["route_residual"] == []
    assert set(report["identity"]["mismatches"]) == {"Q2"}
    assert report["criteria"]["same_route_identical"] is False
    assert report["passed"] is False


def test_gate_fails_on_invalid_questions():
    control = _run({"Q1": _entry(), "Q2": _entry([], invalid=True)})
    runner = FakeRunner({PROD: [control], STG: [_run({"Q1": _entry(), "Q2": _entry()})]})

    report = gate.run_live(runner, *ARMS, residual_max=0)

    assert report["criteria"]["no_invalid"] is False
    assert report["passed"] is False


def test_gate_fails_when_applied_strategies_differ():
    runner = FakeRunner({
        PROD: [_run({"Q1": _entry()})],
        STG: [_run({"Q1": _entry(strategies=("graph_event",))})],
    })

    report = gate.run_live(runner, *ARMS, residual_max=0)

    assert report["criteria"]["graph_strategies_identical"] is False
    assert report["passed"] is False


def test_calibration_records_r0_without_judging_it():
    report = gate.run_live(_always_split(rounds=3), *ARMS, residual_max=None)

    assert report["criteria"]["route_residual_within_r0"] is None
    assert report["r0_measured"] == 1
    assert report["passed"] is True


# --- file mode: compare two saved runs ----------------------------------------

def test_file_mode_compares_without_reasking():
    control = _run({"Q1": _entry(), "Q2": _entry(route="R3")})
    treat = _run({"Q1": _entry(), "Q2": _entry(OTHER, route="R4")})

    report = gate.run_files(control, treat, residual_max=0)

    assert report["rounds"] == []
    assert report["route_residual"] == ["Q2"]
    assert report["passed"] is False


def test_file_mode_fails_on_unpaired_questions():
    """Q3 vs Q4: run-level strategy counts agree, so only the pairing can tell."""
    control = _run({"Q1": _entry(), "Q3": _entry()})
    treat = _run({"Q1": _entry(), "Q4": _entry()})

    report = gate.run_files(control, treat, residual_max=0)

    assert report["identity"]["unpaired"] == {"control_only": ["Q3"], "treatment_only": ["Q4"]}
    assert report["criteria"]["graph_strategies_identical"] is True
    assert report["criteria"]["all_paired"] is False
    assert report["passed"] is False


def _write(path, run):
    path.write_text(json.dumps(run), encoding="utf-8")
    return str(path)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", *args])
    return gate.main()


def test_main_file_mode_writes_report_and_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    control, treat = _agreeing_pair()
    a, b = _write(tmp_path / "a.json", control), _write(tmp_path / "b.json", treat)
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "w0", "--control-file", a,
                                      "--treatment-file", b, "--route-residual-max", "0"])

    assert gate.main() == 0

    report = json.loads((tmp_path / "d3_w0.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["mode"] == "files"
    assert report["inputs"] == {"control": a, "treatment": b}
    assert "PASS" in capsys.readouterr().out


def test_main_exits_1_when_the_gate_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    a = _write(tmp_path / "a.json", _run({"Q1": _entry()}))
    b = _write(tmp_path / "b.json", _run({"Q1": _entry(OTHER)}))
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "w1", "--control-file", a,
                                      "--treatment-file", b, "--route-residual-max", "0"])

    assert gate.main() == 1
    assert json.loads((tmp_path / "d3_w1.json").read_text(encoding="utf-8"))["passed"] is False


def test_main_exits_1_on_legacy_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    legacy = _run({"Q1": _entry()}, include_context=False)
    a, b = _write(tmp_path / "a.json", legacy), _write(tmp_path / "b.json", legacy)
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "old", "--control-file", a,
                                      "--treatment-file", b, "--calibrate"])

    assert gate.main() == 1
    assert "--include-context" in capsys.readouterr().err
    assert not (tmp_path / "d3_old.json").exists()


def test_main_requires_r0_or_calibration(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "w1", "--control-file", "a",
                                      "--treatment-file", "b"])

    with pytest.raises(SystemExit) as exc:
        gate.main()
    assert exc.value.code == 2


def test_main_file_mode_refuses_to_overwrite_a_report_unless_asked(tmp_path, monkeypatch,
                                                                    capsys):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    control, treat = _agreeing_pair()
    args = ["--label", "w1", "--control-file", _write(tmp_path / "a.json", control),
            "--treatment-file", _write(tmp_path / "b.json", treat), "--route-residual-max", "0"]
    (tmp_path / "d3_w1.json").write_text("{}", encoding="utf-8")

    assert _main(monkeypatch, *args) == 1
    assert "d3_w1.json" in capsys.readouterr().err
    assert (tmp_path / "d3_w1.json").read_text(encoding="utf-8") == "{}"

    assert _main(monkeypatch, *args, "--overwrite") == 0
    assert _load(tmp_path / "d3_w1.json")["passed"] is True


@pytest.mark.parametrize("overwrite", [(), ("--overwrite",)])
@pytest.mark.parametrize("side", ["control", "treatment"])
def test_main_file_mode_never_writes_the_report_over_an_input(tmp_path, monkeypatch, capsys,
                                                              side, overwrite):
    """--label prod_s1 names the report d3_prod_s1.json: the raw control run of gate s1."""
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    files = {"control": "a.json", "treatment": "b.json", side: "d3_prod_s1.json"}
    for name, run in zip(files.values(), _agreeing_pair()):
        _write(tmp_path / name, run)
    before = (tmp_path / "d3_prod_s1.json").read_text(encoding="utf-8")

    # Relative input paths: only resolving them shows they are the report path.
    assert _main(monkeypatch, "--label", "prod_s1", "--control-file", files["control"],
                 "--treatment-file", files["treatment"], "--route-residual-max", "0",
                 *overwrite) == 1

    assert f"--{side}-file" in capsys.readouterr().err
    assert (tmp_path / "d3_prod_s1.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("earlier", [
    "d3_stg_w1.json", "d3_prod_w1_retry1.json", "d3_stg_w1_retry2.json",
    "d3_prod_w1_merged.json", "d3_stg_w1_merged.json", "d3_w1.json",
])
def test_main_live_mode_refuses_to_overwrite_earlier_outputs(tmp_path, monkeypatch, capsys,
                                                             earlier):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    (tmp_path / earlier).write_text("{}", encoding="utf-8")

    def must_not_run(*_):
        raise AssertionError("queried a backend despite existing outputs")

    monkeypatch.setattr(gate, "subprocess_runner", must_not_run)
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "w1", "--control-url", PROD,
                                      "--treatment-url", STG, "--route-residual-max", "0"])

    assert gate.main() == 1
    assert earlier in capsys.readouterr().err
    assert (tmp_path / earlier).read_text(encoding="utf-8") == "{}"


def test_file_mode_on_the_saved_merged_runs_reproduces_the_live_verdict(tmp_path, monkeypatch):
    """The raw arm files keep the first answers; only the merged runs match the gate."""
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    raw_prod = _run({"Q1": _entry(), "Q2": _entry(route="R3")})
    raw_stg = _run({"Q1": _entry(), "Q2": _entry(OTHER, route="R4")})
    agreed = _run({"Q1": _entry(), "Q2": _entry(route="R4")})
    monkeypatch.setattr(gate, "subprocess_runner",
                        FakeRunner({PROD: [raw_prod, agreed], STG: [raw_stg, agreed]}))

    assert _main(monkeypatch, "--label", "w1", "--control-url", PROD, "--treatment-url", STG,
                 "--route-residual-max", "0") == 0

    live = _load(tmp_path / "d3_w1.json")
    merged = {"control": str(tmp_path / "d3_prod_w1_merged.json"),
              "treatment": str(tmp_path / "d3_stg_w1_merged.json")}
    assert live["merged_runs"] == merged
    assert _load(tmp_path / "d3_prod_w1_merged.json")["config"]["reasked"] == [["Q2"]]

    assert _main(monkeypatch, "--label", "w1_files", "--control-file", merged["control"],
                 "--treatment-file", merged["treatment"], "--route-residual-max", "0") == 0

    files = _load(tmp_path / "d3_w1_files.json")
    for key in ("passed", "criteria", "route_residual", "identity"):
        assert files[key] == live[key], key
    assert gate.run_files(raw_prod, raw_stg, residual_max=0)["passed"] is False


def test_main_live_mode_uses_plan_arm_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    control, treat = _agreeing_pair()
    runner = FakeRunner({PROD: [control], STG: [treat]})
    monkeypatch.setattr(gate, "subprocess_runner", runner)
    monkeypatch.setattr(sys, "argv", ["d3_gate.py", "--label", "w1", "--control-url", PROD,
                                      "--treatment-url", STG, "--route-residual-max", "0"])

    assert gate.main() == 0

    assert [label for _, label, _ in runner.calls] == ["d3_prod_w1", "d3_stg_w1"]
    report = json.loads((tmp_path / "d3_w1.json").read_text(encoding="utf-8"))
    assert report["mode"] == "live"
    assert report["inputs"]["control"] == {"name": "prod", "url": PROD, "label": "d3_prod_w1"}


# --- subprocess runner: quick_retrieval_eval with the D3 parameters ------------

def test_quick_eval_command_uses_the_d3_parameters(tmp_path):
    cmd = gate.quick_eval_command("d3_stg_w1", tmp_path / "ids.txt")

    assert cmd[1].endswith("quick_retrieval_eval.py")
    assert cmd[2:] == ["--top-k", "5", "--metric-k", "6", "--include-context",
                       "--label", "d3_stg_w1", "--ids-file", str(tmp_path / "ids.txt")]
    assert "--ids-file" not in gate.quick_eval_command("d3_stg_w1")


def test_subprocess_runner_points_quick_eval_at_the_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_OUT_DIR", tmp_path)
    seen = {}

    def fake_run(cmd, env, cwd, check):
        seen.update(url=env["BACKEND_URL"], check=check,
                    ids=open(cmd[cmd.index("--ids-file") + 1], encoding="utf-8").read().split())
        label = cmd[cmd.index("--label") + 1]
        (tmp_path / f"{label}.json").write_text(json.dumps(_run({"Q2": _entry()})),
                                                encoding="utf-8")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    run = gate.subprocess_runner(STG, "d3_stg_w1_retry1", ["Q2", "Q7"])

    assert seen == {"url": STG, "check": True, "ids": ["Q2", "Q7"]}
    assert set(run["per_question"]) == {"Q2"}
