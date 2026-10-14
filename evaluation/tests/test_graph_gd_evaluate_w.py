"""GD experiment evaluate.py: the §5 W 版 block (--scores-w) and pools without scores.

On hand-built items: GD_W−C_W at @10 and @5 is the compare() of a Table holding only the C
and GD pools under window-max scores (unit W:L, CI and the §10 cut gaps of C_W and GD_W,
no p), the plain report keeps not_computed, and neither touches the hypotheses. report's
W table takes one W file per set (E2: two, and E2 refuses to run without them). A scores
file made with score.py rerank --arms leaves the other arms' pools without scores: report
and accept-b fail with the question, the arm and the passages, and Scores records the
arms of its meta lines (one value per file).
"""

import importlib.util
import json
import subprocess
import sys
from fractions import Fraction as F
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if "gd_evaluate" in sys.modules:
    ev = sys.modules["gd_evaluate"]
else:
    _SPEC_EV = importlib.util.spec_from_file_location("gd_evaluate", _DIR / "evaluate.py")
    ev = importlib.util.module_from_spec(_SPEC_EV)
    sys.modules["gd_evaluate"] = ev
    _SPEC_EV.loader.exec_module(ev)
R, I = ev.R, ev.I  # noqa: E741

FILL = [f"ps:f{i:02d}" for i in range(12)]
BASE = {p: 0.9 - 0.01 * i for i, p in enumerate(FILL)}


def item(qid, gold, set_name="new82"):
    return R.Item(qid, set_name, gd.KIN, (frozenset(gold),), frozenset(), None, F(1, 2))


def tables():
    """Q1..Q4, gold ps:gN. Whole scores: C and GD both miss every gold (0.1). Under W the gold
    rises to 0.95 in GD's pool on Q1, Q2 (Q2 also in C's pool: a tie), and only reaches
    @10, not @5, on Q3 (0.855); Q4 stays out. Q1 and Q4 share gold ps:g1 (one unit)."""
    items = [item("Q1", {"ps:g1"}), item("Q2", {"ps:g2"}), item("Q3", {"ps:g3"}), item("Q4", {"ps:g1", "ps:g4"})]
    pools = {"C": {it.qid: tuple(FILL) + (("ps:g2",) if it.qid == "Q2" else ()) for it in items},
             "GD": {it.qid: tuple(FILL) + tuple(sorted(it.gold[0])) for it in items}}
    whole = {it.qid: {**BASE, **{g: 0.1 for g in it.gold[0]}} for it in items}
    w = {q: dict(s) for q, s in whole.items()}
    w["Q1"]["ps:g1"], w["Q2"]["ps:g2"], w["Q3"]["ps:g3"] = 0.95, 0.95, 0.855
    full = {**pools, **{a: pools["GD"] for a in ("L", "LEXPRF")}}
    return items, R.Table(items, full, whole), R.Table(items, pools, w)


def test_the_w_block_is_gd_w_minus_c_w_with_w_l_and_ci_but_no_p():
    _, table, wt = tables()
    out = R.sensitivity(table, w_table=wt)
    w10, w5 = out["GD-C@10"]["W"], out["GD-C@5"]["W"]
    assert w10["pair"] == "GD_W-C_W@10" and "p" not in w10 and "p" not in w5
    # @10: Q1 +1 (unit with Q4 at 0: v = 1/2), Q2 0 (both find it), Q3 +1 → units 2:0 of 3
    assert (w10["unit_W:L"], w10["n_units"], w10["sum_v"], w10["question_W:L"]) == ("2:0", 3, "3/2", "2:0")
    assert w10["ci95"][0] <= w10["mean_unit_diff"] <= w10["ci95"][1]
    # @5: Q3's 0.855 ranks 6th behind f00..f04 → only Q1 counts
    assert (w5["unit_W:L"], w5["sum_v"]) == ("1:0", "1/2")
    plain = out["GD-C@10"]["question_level"]
    assert plain["question_W:L"] == "0:0"                  # whole scores: no difference at all


def test_without_w_scores_the_block_stays_not_computed_and_nothing_else_moves():
    _, table, wt = tables()
    plain, with_w = R.sensitivity(table), R.sensitivity(table, w_table=wt)
    for k in (10, 5):
        assert set(plain[f"GD-C@{k}"]["W"]) == {"not_computed"}
        assert {x: v for x, v in plain[f"GD-C@{k}"].items() if x != "W"} == \
            {x: v for x, v in with_w[f"GD-C@{k}"].items() if x != "W"}
    assert plain["H3_excl_shortcut"] == with_w["H3_excl_shortcut"]


def test_the_w_block_reports_the_cut_gaps_of_c_w_and_gd_w_and_lists_boundary_questions():
    items, table, wt = tables()
    w10 = R.sensitivity(table, w_table=wt)["GD-C@10"]["W"]
    assert set(w10["cut_gaps"]) == {"C_W@10", "GD_W@10"}
    assert w10["cut_gaps"]["C_W@10"]["boundary_lt_1e-5"] == []
    assert abs(w10["cut_gaps"]["C_W@10"]["min"] - 0.01) < 1e-9          # f09 0.81 vs f10 0.80
    near = {q: dict(s) for q, s in wt.scores.items()}
    near["Q4"]["ps:f10"] = near["Q4"]["ps:f09"] - 5e-6                  # Q4: a 5e-6 cut gap @10
    out = R.sensitivity(table, w_table=R.Table(items, wt.pools, near))
    for k, arm in ((10, "C"), (10, "GD")):
        gaps = out[f"GD-C@{k}"]["W"]["cut_gaps"][f"{arm}_W@{k}"]
        assert gaps["boundary_lt_1e-5"] == ["Q4"] and gaps["min"] < 1e-5
    assert out["GD-C@5"]["W"]["cut_gaps"]["C_W@5"]["boundary_lt_1e-5"] == []
    assert out["GD-C@10"]["W"]["unit_W:L"] == w10["unit_W:L"]           # listed only, no effect


def test_the_e2_report_refuses_to_run_without_w_scores(tmp_path):
    with pytest.raises(gd.GdError, match="needs --scores-w"):
        ev.report("old31+ho", [tmp_path / "a", tmp_path / "b"], [tmp_path / "c", tmp_path / "d"])
    out = tmp_path / "e2.json"
    proc = subprocess.run([sys.executable, "-B", str(_DIR / "evaluate.py"), "report", "--set", "old31+ho",
                           "--lists", "a", "b", "--scores", "c", "d", "--out", str(out)],
                          capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 2 and not out.exists()
    assert proc.stderr.startswith("evaluate.py: GdError:") and proc.stderr.count("\n") == 1


def test_the_w_table_must_hold_the_same_questions_and_only_c_and_gd():
    items, table, wt = tables()
    fewer = R.Table(items[:3], {a: {q: wt.pools[a][q] for q in ("Q1", "Q2", "Q3")} for a in ("C", "GD")},
                    wt.scores)
    with pytest.raises(gd.IntegrityError):
        R.sensitivity(table, w_table=fewer)
    with pytest.raises(gd.IntegrityError):
        R.sensitivity(table, w_table=table)                        # carries L, LEXPRF too


def fake_part(name, qids):
    qs = gd.QuestionSet(name, tuple(gd.Question(q, "?", gd.KIN, (("gen.1.1",),), frozenset()) for q in qids),
                        MappingProxyType({}))
    return ev.Part(qs, SimpleNamespace(), SimpleNamespace())


def test_report_joins_one_w_file_per_set_for_e2(monkeypatch):
    items, table, wt = tables()
    parts = [fake_part("old31", ["Q1", "Q2"]), fake_part("ho", ["Q3", "Q4"])]

    class FakeW:
        def __init__(self, path, qset, lists, scores):
            self.path, self.by_qid = Path(path), {q: wt.scores[q] for q in qset.ids}

    monkeypatch.setattr(ev.I, "WScores", FakeW)
    joined, ws = ev.w_table(parts, items, table, [Path("w_old31.jsonl"), Path("w_ho.jsonl")])
    assert [w.path.name for w in ws] == ["w_old31.jsonl", "w_ho.jsonl"] and joined.arms == ("C", "GD")
    assert R.sensitivity(table, w_table=joined)["GD-C@10"]["W"]["unit_W:L"] == "2:0"
    with pytest.raises(gd.GdError, match="--scores-w needs 2 files"):
        ev.w_table(parts, items, table, [Path("w_old31.jsonl")])


def test_the_cli_takes_one_or_two_w_files():
    base = ["report", "--set", "old31+ho", "--lists", "a", "b", "--scores", "c", "d", "--out", "o.json"]
    assert ev.parse_args(base + ["--scores-w", "w1", "w2"]).scores_w == [Path("w1"), Path("w2")]
    assert ev.parse_args(base).scores_w is None


# ---------------------------------------------------------------- pools without scores (--arms)

def test_acceptance_b_names_the_question_and_arm_of_a_pool_without_scores():
    pools = {a: {"Q1": ("ps:a",), "Q2": ("ps:a", "ps:b")} for a in ev.acc.ACCEPT_ARMS}
    scores = {"Q1": {"ps:a": 0.5}, "Q2": {"ps:a": 0.5, "ps:b": 0.4}}
    ev.acc.check_scored(pools, scores, ["Q1", "Q2"])
    pools["L"] = {**pools["L"], "Q2": ("ps:a", "ps:lx")}
    with pytest.raises(gd.GdError, match=r"Q2 / L: pool passages without a reranker score: \['ps:lx'\]"):
        ev.acc.check_scored(pools, scores, ["Q1", "Q2"])


def test_a_pool_without_scores_fails_with_the_question_arm_and_passages():
    items, _, wt = tables()
    pools = {**wt.pools, "L": {it.qid: tuple(FILL) + ("ps:lx",) for it in items}}
    with pytest.raises(gd.GdError, match=r"Q1 / L: pool passages without a reranker score: \['ps:lx'\]"):
        R.Table(items, pools, wt.scores)


STRICT = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu", "batch": 16, "torch_threads": 12,
          "reranker_fingerprint": gd.expected_fingerprint("reranker")}
SCRIPTS = {name: name[0] * 64 for name in ("score.py", "_score_io.py", "rerank_stdin.py")}


def scores_file(path, *arms_per_meta):
    qs = gd.QuestionSet("new82", (gd.Question("Q", "?", gd.KIN, (("gen.1.1",),), frozenset()),),
                        MappingProxyType({}))
    lines = []
    for arms in arms_per_meta:
        host = {"lists_sha256": "L" * 64, "sha256": SCRIPTS, "set": "new82", "set_ids_sha256": qs.ids_sha256,
                **({} if arms is None else {"arms": arms})}
        lines.append({**STRICT, "host": host})
    lines += [{"type": "r", "sid": "Q", "scores": {"ps:a": 0.5}, "missing": [], "elapsed_s": 1.0},
              {"type": "refcheck", "n_pairs": 32, "max_abs_diff": 0.0, "pass": True, "container_meta": STRICT}]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path, qs


@pytest.mark.parametrize("arms_per_meta, want", [((None,), None), ((["C", "GD"],), ("C", "GD")),
                                                 ((["C", "GD"], ["C", "GD"]), ("C", "GD"))])
def test_scores_record_the_arms_of_their_meta_lines(tmp_path, arms_per_meta, want):
    path, qs = scores_file(tmp_path / "s.jsonl", *arms_per_meta)
    assert I.Scores(path, qs, "L" * 64).arms == want


def test_scores_whose_meta_lines_disagree_on_arms_are_refused(tmp_path):
    path, qs = scores_file(tmp_path / "s.jsonl", ["C", "GD"], None)
    with pytest.raises(gd.IntegrityError, match="different scored arms"):
        I.Scores(path, qs, "L" * 64)
