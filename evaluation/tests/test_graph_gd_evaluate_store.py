"""GD experiment metrics on the store (experiments/2026-10-14_graph_gd/evaluate.py).

Split from test_graph_gd_evaluate.py. With the store mounted, the archived NEW82 lists
and scores (converted to the arms.py / score.py formats in tmp_path, read unpinned) must
reproduce the prereg and review numbers, acceptance B must pass against itself and flag
perturbed runs (a drift above 1e-5 is an infrastructure failure, never a boundary), and
OLD31's gold-only units are checked. The arms.py output kept in the store
(new82/lists.json) joined with the archived scores must give the same report, its D5≈
must reproduce the stored missing hops, and it must pass acceptance B: the arms → score
format → evaluate chain.
"""

import importlib.util
import json
import sys
from collections import defaultdict
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
if "gd_evaluate" in sys.modules:
    ev = sys.modules["gd_evaluate"]
else:
    _SPEC_EV = importlib.util.spec_from_file_location("gd_evaluate", _DIR / "evaluate.py")
    ev = importlib.util.module_from_spec(_SPEC_EV)
    sys.modules["gd_evaluate"] = ev      # dataclasses resolve annotations through sys.modules
    _SPEC_EV.loader.exec_module(ev)
st, M, acc = ev.st, ev.M, ev.acc

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file()
    or not gd.EV.is_dir(), reason=f"store not mounted ({gd.STORE})")

RERANK_META = {"type": "meta", "build_id": gd.BUILD_ID,
               "reranker_fingerprint": dict(gd.FINGERPRINTS["reranker"]), "device": "cpu"}
STORE_LISTS = gd.OUT_ROOT / "new82" / "lists.json"     # arms.py --set new82 (驗收 A)


def write_lists(path, rows):
    path.write_text(json.dumps({"meta": {}, "lists": rows}), encoding="utf-8")
    return path


def write_scores(path, *lines):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def row(qid, scores, missing=()):
    return {"type": "r", "sid": qid, "scores": scores, "missing": list(missing), "elapsed_s": 1.0}


# ---------------------------------------------------------------- store: archived NEW82 run

def archived_inputs():
    """EV/AT prf_lists → arms.py lists; reproduce_sel merged() scores → score.py jsonl."""
    docs = {n: json.loads(gd.read_pinned(p, sha)) for n, (p, sha) in acc.LIST_SOURCES.items()}
    le, la = docs["ev"], docs["at"]
    lists = {q: {"D30": le[q]["d20"] + le[q]["ctrl_extra"], "C": le[q]["ctrl_extra"],
                 "GD": le[q]["PPR_DENSEONLY"], "G": le[q]["PPR_BIP"], "L": le[q]["BM25_Q"],
                 "LEXPRF": la[q]["LEXPRF"]} for q in le}
    merged = defaultdict(dict)
    for _, path, sha in acc.SCORE_SOURCES:
        for line in gd.read_pinned(path, sha).decode("utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("type") == "r":
                merged[rec["sid"].split("|")[0]].update(rec["scores"])
    return lists, dict(merged)


def write_inputs(tmp_path, lists, merged, name="run"):
    lp = write_lists(tmp_path / f"{name}_lists.json", lists)
    sp = write_scores(tmp_path / f"{name}_scores.jsonl", RERANK_META,
                      *(row(q, merged[q]) for q in sorted(merged)))
    return lp, sp


@pytest.fixture(scope="module")
def archived(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gd_eval")
    lists, merged = archived_inputs()
    lp, sp = write_inputs(tmp, lists, merged)
    ref = tmp / "ref.json"
    ref.write_text(json.dumps(acc.build_reference()), encoding="utf-8")
    return {"dir": tmp, "lists": lists, "merged": merged, "lp": lp, "sp": sp, "ref": ref}


@needs_store
def test_archived_new82_reproduces_the_prereg_descriptive_numbers(archived):
    rep = ev.report("new82", archived["lp"], archived["sp"], pinned=False)
    arms = ("C", "GD", "G", "L", "LEXPRF")
    got = {k: ([rep["metrics"][k][a]["all_hops_hit"] for a in arms],
               [rep["metrics"][k][a]["missing_hops_hit"] for a in arms]) for k in ("@10", "@5")}
    assert got == {"@10": ([137, 151, 146, 143, 141], [17, 31, 26, 24, 21]),
                   "@5": ([119, 126, 124, 120, 122], [7, 14, 13, 10, 12])}
    assert (rep["units"]["n_units"], rep["units"]["max_unit"], rep["units"]["density_low"]) == (40, 12, 47)
    assert rep["arms_absent"] == ["GD_DEGNORM"] and rep["exploratory"]


@needs_store
def test_archived_new82_reproduces_the_review_cluster_sign_flips(archived):
    h = ev.report("new82", archived["lp"], archived["sp"], pinned=False)["hypotheses"]
    parts = h["H3"]["parts"]
    got = [(h["H1"]["unit_W:L"], h["H1"]["p_exact"]), (h["H2"]["unit_W:L"], round(h["H2"]["p"], 4)),
           (parts["GD-LEXPRF@10"]["unit_W:L"], round(parts["GD-LEXPRF@10"]["p"], 4)),
           (parts["GD-L@10"]["unit_W:L"], round(parts["GD-L@10"]["p"], 4))]
    assert got == [("11:0", "1/1024"), ("8:2", 0.2695), ("10:1", 0.0254), ("10:2", 0.0239)]
    assert (h["H1"]["pass"], h["H2"]["pass"], h["H3"]["pass"]) == (True, False, False)


@needs_store
def test_archived_new82_question_level_gd_minus_c(archived):
    qset = gd.load_new82()
    _, table = ev.merge([ev.load_part("new82", archived["lp"], archived["sp"], pinned=False)])
    got = []
    for k in (10, 5):
        d = [table.cov("GD", k)[q] - table.cov("C", k)[q] for q in sorted(qset.ids)]
        got.append((sum(v > 0 for v in d), sum(v < 0 for v in d), round(float(st.sign_flip(d).p), 4)))
    assert got == [(14, 0, 0.0001), (10, 3, 0.0425)]


@needs_store
def test_accept_b_passes_against_its_own_reference(archived):
    doc, code = acc.accept_b(archived["lp"], archived["sp"], archived["ref"], pinned=False)
    assert code == 0 and doc["passed"] and doc["drift"]["max_abs"] == 0.0
    assert doc["topk_sets"] == {"compared": 820, "equal": 820, "boundary": [], "failed": []}
    assert doc["summary"]["new_equals_prereg"] and not doc["pool_mismatches"]


def cut_pair(lists, merged, qid, arm, k):
    pool = lists[qid]["D30"][:20] + lists[qid][arm]
    ranked = sorted(pool, key=lambda p: (-merged[qid][p], p))
    return ranked[k - 1], ranked[k]


@needs_store
def test_a_swap_at_the_tightest_archived_cut_already_drifts_past_1e_5(archived, tmp_path):
    """The archived cut gaps are ≥ 2.35e-5 (§3 數值出口), so flipping any cut moves a score by more
    than §10's 1e-5: that is an infrastructure failure, not a boundary question."""
    ref = json.loads(archived["ref"].read_text(encoding="utf-8"))
    assert ref["min_cut_gap"] > acc.DRIFT_MAX
    lists, merged = archived["lists"], {q: dict(s) for q, s in archived["merged"].items()}
    a, b = cut_pair(lists, merged, "N_KIN_01", "GD", 5)
    merged["N_KIN_01"][a], merged["N_KIN_01"][b] = merged["N_KIN_01"][b], merged["N_KIN_01"][a]
    doc, code = acc.accept_b(*write_inputs(tmp_path, lists, merged), archived["ref"], pinned=False)
    assert code == 1 and not doc["drift"]["ok"] and doc["topk_sets"]["boundary"] == []
    assert {"qid": "N_KIN_01", "arm": "GD", "k": 5} in [
        {key: r[key] for key in ("qid", "arm", "k")} for r in doc["topk_sets"]["failed"]]


@needs_store
def test_accept_b_fails_on_a_changed_pool_or_a_wide_gap_mismatch(archived, tmp_path):
    lists = {q: dict(v) for q, v in archived["lists"].items()}
    merged = {q: dict(s) for q, s in archived["merged"].items()}
    lists["N_KIN_01"]["GD"] = ["ps:zzz.1.1"] + lists["N_KIN_01"]["GD"][1:]
    merged["N_KIN_01"]["ps:zzz.1.1"] = 5.0                        # unscored in the reference: no drift
    doc, code = acc.accept_b(*write_inputs(tmp_path, lists, merged), archived["ref"], pinned=False)
    assert code == 1 and not doc["passed"]
    assert doc["pool_mismatches"] == [{"qid": "N_KIN_01", "arm": "GD"}]
    assert {(r["arm"], r["k"]) for r in doc["topk_sets"]["failed"]} == {("GD", 5), ("GD", 10)}


@needs_store
def test_accept_b_fails_without_boundary_questions_once_the_drift_passes_1e_5(archived, tmp_path):
    """review case: one wildly wrong pair must not widen the boundary limit until all passes."""
    lists, merged = archived["lists"], {q: dict(s) for q, s in archived["merged"].items()}
    a, b = cut_pair(lists, merged, "N_KIN_01", "GD", 5)
    merged["N_KIN_01"]["ps:num.16.1"] = 0.0
    merged["N_KIN_01"][b] = 0.999
    doc, code = acc.accept_b(*write_inputs(tmp_path, lists, merged), archived["ref"], pinned=False)
    assert code == 1 and not doc["passed"]
    assert not doc["drift"]["ok"] and doc["drift"]["max_abs"] > 0.5 and doc["drift"]["limit"] == 0.0
    assert "infrastructure_failure" in doc["drift"] and doc["topk_sets"]["boundary"] == []
    assert doc["topk_sets"]["failed"]


@needs_store
def test_accept_b_refuses_a_reference_that_is_not_the_pinned_archive(archived, tmp_path):
    ref = json.loads(archived["ref"].read_text(encoding="utf-8"))
    ref["questions"]["N_KIN_01"]["scores"]["ps:num.16.1"] += 1e-3
    bad = tmp_path / "ref.json"
    bad.write_text(json.dumps(ref), encoding="utf-8")
    with pytest.raises(gd.IntegrityError):
        acc.accept_b(archived["lp"], archived["sp"], bad, pinned=False)


@needs_store
def test_stored_reference_is_the_one_build_reference_gives(archived):
    if not acc.REF_PATH.is_file():
        pytest.skip(f"{acc.REF_PATH} not built yet")
    stored = json.loads(acc.REF_PATH.read_text(encoding="utf-8"))
    built = json.loads(archived["ref"].read_text(encoding="utf-8"))
    stored.pop("meta", None)
    assert stored == built


@needs_store
def test_old31_units_come_from_gold_only():
    out = ev.units("old31")
    assert (out["n_units"], out["max_unit"], out["n_questions"]) == (20, 9, 31)
    assert len(out["shares_gold_with_new82"]) == 16


@needs_store
def test_report_refuses_old31_before_appendix_a(archived):
    if gd.appendix_has_content("A"):
        pytest.skip("appendix A is filled")
    with pytest.raises(gd.ConfirmationLockedError):
        ev.report("old31", archived["lp"], archived["sp"], pinned=False)


# ---------------------------------------------------------------- arms → score format → evaluate

@needs_store
def test_store_lists_with_the_archived_scores_pass_accept_b_and_give_the_archived_report(
        archived, tmp_path):
    if not STORE_LISTS.is_file():
        pytest.skip(f"{STORE_LISTS} not written yet (arms.py --set new82)")
    stored = json.loads(STORE_LISTS.read_text(encoding="utf-8"))["lists"]
    assert all("GD_DEGNORM" in v for v in stored.values())
    # the archive never scored GD_DEGNORM's extra (455 pairs), so that optional arm is left out
    lists = {q: {a: v for a, v in by_arm.items() if a != "GD_DEGNORM"} for q, by_arm in stored.items()}
    lp, sp = write_inputs(tmp_path, lists, archived["merged"], name="store")
    doc, code = acc.accept_b(lp, sp, archived["ref"], pinned=False)
    assert code == 0 and doc["passed"] and not doc["pool_mismatches"]
    assert doc["topk_sets"] == {"compared": 820, "equal": 820, "boundary": [], "failed": []}
    assert doc["drift"]["max_abs"] == 0.0 and doc["summary"]["new_equals_prereg"]
    new = ev.report("new82", lp, sp, pinned=False)
    old = ev.report("new82", archived["lp"], archived["sp"], pinned=False)
    assert new["missing_hops"].pop("new82_d5approx_check") == {
        "d5approx_hops": 102, "d5approx_questions": 63, "equal_to_stored": 82, "of": 82}
    assert old["missing_hops"].pop("new82_d5approx_check") is None      # archived lists lack R20
    new.pop("meta"), old.pop("meta")
    assert new == old
