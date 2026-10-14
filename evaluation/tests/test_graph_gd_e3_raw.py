"""GD experiment §8 E3 raw files and scoring runs (e3_raw.py, _e3_build.py, _e3_run.py).

Unit tests on synthetic inputs: the raw format (collector item keys, /query passage source
keys, what quick_retrieval_eval's samples_from_raw rebuilds from it), §3 top-k, the raw
validator, run_meta.json, no overwriting, moving the quick_retrieval_eval output out of a
results directory, the output checks (metric_version 4d0826bb8d14), and the guard: build
always, run / gates whenever they would write under e3/. Nothing here retrieves, scores or
encodes anything, and no test points the guard elsewhere.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
import _e3_build as B  # noqa: E402
import _e3_run as R  # noqa: E402
import e3_raw  # noqa: E402
from src.models import GroundTruthItem  # noqa: E402

COLLECTOR_KEYS = {"question_id", "question", "rag_answer", "contexts", "context_source", "sources",
                  "route_used", "strategies_used", "strategy_errors", "use_graph", "graph_strategies"}
ROWS = {p: B.SourceRow(p, "創世記", 1, f"t{p}", f"{i + 1}", f"gen.1.{i + 1}", f"gen.1.{i + 1}")
        for i, p in enumerate(["ps:a", "ps:b", "ps:c", "ps:d"])}
QS = gd.QuestionSet("gtv2", (gd.Question("Q1", "問一", "T", (), None),
                             gd.Question("Q2", "問二", "T", (), None)), {})
SCORES = {"Q1": {"ps:a": 0.2, "ps:b": 0.9, "ps:c": 0.9, "ps:d": 0.1},
          "Q2": {"ps:a": 0.5, "ps:b": 0.4, "ps:c": 0.3, "ps:d": 0.6}}
POOLS = {"Q1": ["ps:a", "ps:b", "ps:c", "ps:d"], "Q2": ["ps:d", "ps:c", "ps:b", "ps:a"]}
appendix_pending = pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")


def items(k=2, arm="GD"):
    return B.arm_items(QS, POOLS, SCORES, arm, k, ROWS)


# ---------------------------------------------------------------- raw format

def test_a_source_has_the_query_passage_fields_and_an_item_the_collector_keys():
    src = B.passage_source(ROWS["ps:b"], 0.9, "GD")
    assert tuple(src) == B.SOURCE_KEYS
    assert src == {"id": "ps:b", "book": "創世記", "chapter": 1, "title": "tps:b", "verse_range": "2",
                   "score": 0.9, "strategy": "OFFLINE_GD", "kind": "passage", "start_key": "gen.1.2",
                   "end_key": "gen.1.2"}
    item = B.raw_item("Q1", "問一", [src], "GD")
    assert set(item) == COLLECTOR_KEYS and item["route_used"] == "OFFLINE"
    assert item["strategies_used"] == ["OFFLINE_GD"] and item["strategy_errors"] == {}


def test_top_k_sorts_by_minus_score_then_pid_and_needs_every_score():
    assert B.top_k(POOLS["Q1"], SCORES["Q1"], 3) == ("ps:b", "ps:c", "ps:a")
    with pytest.raises(gd.IntegrityError, match="分數缺漏"):
        B.top_k(["ps:a", "ps:x"], SCORES["Q1"], 1)
    with pytest.raises(gd.IntegrityError, match="k=5"):
        B.top_k(POOLS["Q1"], SCORES["Q1"], 5)


def test_arm_items_follow_the_set_order_with_exactly_k_sources():
    got = items(k=2)
    assert [i["question_id"] for i in got] == ["Q1", "Q2"]
    assert [[s["id"] for s in i["sources"]] for i in got] == [["ps:b", "ps:c"], ["ps:d", "ps:a"]]
    assert got[1]["sources"][0]["score"] == 0.6
    B.check_raw(got, QS, 2, "GD")


def test_quick_retrieval_eval_reads_the_raw_back_unchanged(tmp_path):
    raw = tmp_path / B.RAW_NAME
    raw.write_text(json.dumps(items(k=2), ensure_ascii=False), encoding="utf-8")
    gts = {q.qid: GroundTruthItem(question_id=q.qid, question=q.question, question_type="T",
                                  book_name="創世記") for q in QS.questions}
    samples = e3_raw.G.qre.samples_from_raw(raw, gts)
    assert [s.route_used for s in samples] == ["OFFLINE", "OFFLINE"]
    first = samples[0].sources[0]
    assert (first.id, first.book, first.chapter, first.start_key, first.end_key, first.kind) == (
        "ps:b", "創世記", 1, "gen.1.2", "gen.1.2", "passage")


def _corrupt(how):
    doc = items(k=2)
    src = doc[0]["sources"][0]
    if how == "order":
        doc.reverse()
    elif how == "k":
        doc[0]["sources"].pop()
    elif how == "route":
        doc[1]["route_used"] = "R2"
    elif how == "error":
        doc[0]["strategy_errors"] = {"x": "boom"}
    elif how == "dup":
        doc[0]["sources"][1] = dict(src)
    elif how == "key":
        src["extra"] = 1
    elif how == "kind":
        src["kind"] = "chunk"
    elif how == "strategy":
        src["strategy"] = "OFFLINE_C"
    elif how == "question":
        doc[0]["question"] = "別的題目"
    elif how == "no_end_key":
        src["end_key"] = None
    return doc


@pytest.mark.parametrize("how", ["order", "k", "route", "error", "dup", "key", "kind", "strategy",
                                 "question", "no_end_key"])
def test_check_raw_rejects_every_break_of_the_format(how):
    with pytest.raises(gd.IntegrityError):
        B.check_raw(_corrupt(how), QS, 2, "GD")


def test_run_meta_is_the_build_and_the_health_shaped_encoder_fingerprint():
    doc = B.run_meta_doc()
    assert doc["data_build_id"] == "b20261008_e05d3e55"
    assert set(doc["encoder_fingerprint"]) == {"embedder", "reranker"}
    for kind, fp in doc["encoder_fingerprint"].items():
        gd.verify_fingerprint(kind, fp)


def test_raw_dirs_are_written_once_and_read_back_only_with_the_pinned_run_meta(tmp_path):
    shas = B.write_raw_dir(tmp_path / "r", items())
    got, meta, read_shas = B.read_raw(tmp_path / "r")
    assert got == items() and meta == B.run_meta_doc() and read_shas == shas
    with pytest.raises(gd.GdError, match="not overwritten"):
        B.write_raw_dir(tmp_path / "r", items())
    (tmp_path / "r" / B.RUN_META_NAME).write_text(json.dumps({"data_build_id": "b20261008_6daa4f31"}))
    with pytest.raises(gd.IntegrityError):
        B.read_raw(tmp_path / "r")


# ---------------------------------------------------------------- moving the output out of results_quick

def test_the_output_moves_out_and_the_results_directory_lists_as_before(tmp_path):
    rq = tmp_path / "rq"
    rq.mkdir()
    (rq / "old.json").write_text("{}")
    before = R.listing(rq)
    (rq / "lab.json").write_text('{"x": 1}')
    target = R.take_output("lab", tmp_path / "dest", before, rq)
    assert target == tmp_path / "dest" / R.QUICK_NAME and json.loads(target.read_text()) == {"x": 1}
    assert R.listing(rq) == before == (True, ("old.json",))


def test_a_results_directory_the_run_created_is_removed_again(tmp_path):
    rq = tmp_path / "rq"
    before = R.listing(rq)
    rq.mkdir()
    (rq / "lab.json").write_text("{}")
    R.take_output("lab", tmp_path / "dest", before, rq)
    assert not rq.exists() and before == (False, ())


def test_any_other_new_file_in_results_quick_stops_the_run(tmp_path):
    rq = tmp_path / "rq"
    rq.mkdir()
    before = R.listing(rq)
    (rq / "lab.json").write_text("{}")
    (rq / "stray.json").write_text("{}")
    with pytest.raises(gd.IntegrityError, match="stray.json"):
        R.take_output("lab", tmp_path / "dest", before, rq)
    assert R.listing(rq) == (True, ("stray.json",))                     # this run's output left
    assert (tmp_path / "dest" / R.FAILED_DIR / "lab.json").is_file()      # kept, not accepted
    assert not (tmp_path / "dest" / R.QUICK_NAME).exists()


def quick_doc(raw_items, k, raw_path, metric_version=R.METRIC_VERSION):
    return {"meta": {"data_build_id": gd.BUILD_ID, "gt_version": "v2", "gt_sha": gd.GTV2_SHA256,
                     "encoder_fingerprint": B.run_meta_doc()["encoder_fingerprint"]},
            "config": {"from_raw": str(raw_path), "top_k": k, "metric_k": k,
                       "metric_version": metric_version},
            "n": len(raw_items), "n_invalid": 0, "overall": {},
            "per_question": {i["question_id"]: {"sources": [s["id"] for s in i["sources"]]}
                             for i in raw_items}}


def test_the_output_must_score_these_raw_items_with_metric_version_4d0826bb8d14(tmp_path):
    raw, path = items(k=2), tmp_path / B.RAW_NAME
    R.verify_quick(quick_doc(raw, 2, path), raw, 2, path, B.run_meta_doc())
    with pytest.raises(gd.IntegrityError, match="metric_version"):
        R.verify_quick(quick_doc(raw, 2, path, "000000000000"), raw, 2, path, B.run_meta_doc())
    with pytest.raises(gd.IntegrityError, match="config"):
        R.verify_quick(quick_doc(raw, 2, path), raw, 3, path, B.run_meta_doc())
    bad = quick_doc(raw, 2, path)
    bad["per_question"]["Q1"]["sources"].reverse()
    with pytest.raises(gd.IntegrityError, match="Q1"):
        R.verify_quick(bad, raw, 2, path, B.run_meta_doc())


def test_the_metric_version_requirement_is_the_prereg_value():
    assert R.METRIC_VERSION == "4d0826bb8d14"
    R.require_metric_version("4d0826bb8d14", "x")
    with pytest.raises(gd.IntegrityError):
        R.require_metric_version("4d0826bb8d15", "x")


# ---------------------------------------------------------------- guard and official outputs

def test_only_paths_under_e3_are_official():
    assert e3_raw.is_official(e3_raw.E3_DIR / "C_k5") and e3_raw.is_official(e3_raw.GATES_OUT)
    assert not e3_raw.is_official(_DIR / "accept") and not e3_raw.is_official(Path("/tmp/x"))


def test_unpinned_inputs_never_reach_the_official_outputs(capsys):
    assert e3_raw.main(["gates", "--c5", "a", "--gd5", "b", "--allow-unpinned"]) == 2
    assert "--allow-unpinned never writes" in capsys.readouterr().err


@appendix_pending
@pytest.mark.parametrize("argv", [
    ["build", "--lists", "@L", "--scores", "@S", "--k", "5", "--arm", "GD", "--out", "@OUT"],
    ["run", "--raw", "@RAW", "--k", "5", "--arm", "C"],
    ["gates", "--c5", "@C5", "--gd5", "@GD5"],
])
def test_build_and_official_run_and_gates_are_locked_until_appendix_a(argv, tmp_path, capsys):
    argv = [str(tmp_path / a[1:]) if a.startswith("@") else a for a in argv]
    assert e3_raw.main(argv) == 2
    err = capsys.readouterr().err
    assert "ConfirmationLockedError" in err and "gtv2" in err and len(err.strip().splitlines()) == 1
    assert list(tmp_path.iterdir()) == []


def gtv2_raw(k=2, arm="GD"):
    """A raw for every GT v2 question (its own text) with synthetic sources: format only."""
    qset = gd.load_question_set(gd.GTV2)
    rows = list(ROWS.values())
    return qset, [B.raw_item(q.qid, q.question, [B.passage_source(r, 0.5, arm) for r in rows[:k]], arm)
                  for q in qset.questions]


def test_a_raw_dir_without_its_build_record_needs_allow_unpinned(tmp_path):
    qset, raw = gtv2_raw()
    B.check_raw(raw, qset, 2, "GD")
    B.write_raw_dir(tmp_path / "raw", raw)
    with pytest.raises(gd.GdError, match="--allow-unpinned"):
        e3_raw.run(tmp_path / "raw", 2, "GD", tmp_path / "dest", allow_unpinned=False)
    assert not (tmp_path / "dest").exists()


def test_a_build_record_must_name_these_raw_files_arm_and_k(tmp_path):
    qset, raw = gtv2_raw()
    shas = B.write_raw_dir(tmp_path / "raw", raw)
    record = {"set": "gtv2", "ids_sha256": qset.ids_sha256, "arm": "GD", "k": 2, "raw_sha256": shas,
              "lists_sha256": "L", "scores_sha256": "S"}
    B.write_json(tmp_path / "raw" / B.BUILD_NAME, record)
    built = e3_raw._build_record(tmp_path / "raw", shas, "GD", 2, qset)
    assert (built["lists_sha256"], built["scores_sha256"]) == ("L", "S")
    for arm, k, sha in (("C", 2, shas), ("GD", 5, shas), ("GD", 2, {**shas, B.RAW_NAME: "0" * 64})):
        with pytest.raises(gd.IntegrityError):
            e3_raw._build_record(tmp_path / "raw", sha, arm, k, qset)


class FakeScores:
    def __init__(self, *arms):
        self.path = Path("S.jsonl")
        self.metas = tuple({"host": {"arms": a} if a is not None else {}} for a in arms)


@pytest.mark.parametrize("arms, arm, want", [((None,), "GD", None), ((["C", "GD"],) * 2, "GD", ["C", "GD"])])
def test_the_scored_arms_are_recorded_and_must_hold_the_built_arm(arms, arm, want):
    assert e3_raw._scores_arms(FakeScores(*arms), arm) == want


@pytest.mark.parametrize("arms", [(["C"],), (["C", "GD"], None)])
def test_scores_without_the_arm_or_with_mixed_arms_are_refused(arms):
    with pytest.raises(gd.GdError):
        e3_raw._scores_arms(FakeScores(*arms), "GD")


# ---------------------------------------------------------------- which runs the gates accept

def fake_run(arm, k, meta_sha="M", lists="L", scores="S", pinned=True):
    build = {"lists_sha256": lists, "scores_sha256": scores} if pinned else None
    return R.Run(Path(f"/x/{arm}{k}"), arm, k, pinned, build, Path("/raw"),
                 {B.RAW_NAME: "r", B.RUN_META_NAME: meta_sha}, {})


def test_pinned_gates_take_c_and_gd_runs_of_one_lists_and_scores_file():
    e3_raw._check_runs({5: (fake_run("C", 5), fake_run("GD", 5)),
                        10: (fake_run("C", 10), fake_run("GD", 10))}, pinned=True)


@pytest.mark.parametrize("pair, error", [
    ((fake_run("GD", 5), fake_run("C", 5)), gd.IntegrityError),             # swapped arms
    ((fake_run("C", 5), fake_run("GD", 10)), gd.IntegrityError),            # another k
    ((fake_run("C", 5), fake_run("GD", 5, meta_sha="N")), gd.IntegrityError),  # another build
    ((fake_run("C", 5), fake_run("GD", 5, scores="T")), gd.IntegrityError),    # other scores
    ((fake_run("C", 5), fake_run("GD", 5, pinned=False)), gd.GdError),         # synthetic raw
])
def test_the_gates_refuse_runs_that_do_not_pair(pair, error):
    with pytest.raises(error):
        e3_raw._check_runs({5: pair}, pinned=True)


def test_unpinned_gates_still_need_the_pairing_but_not_the_build_record():
    e3_raw._check_runs({5: (fake_run("C", 5, pinned=False), fake_run("GD", 5, pinned=False))}, pinned=False)
    with pytest.raises(gd.IntegrityError):
        e3_raw._check_runs({5: (fake_run("C", 5, pinned=False), fake_run("C", 5, pinned=False))}, pinned=False)
