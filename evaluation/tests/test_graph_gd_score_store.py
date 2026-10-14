"""GD experiment container runner on the store (experiments/2026-10-14_graph_gd/score.py).

Split from test_graph_gd_score.py. With the store mounted, the 32 §10 reference pairs
(read through their pinned sha256) and the archived container meta lines are checked, the
refpairs command runs against a fake container answering the archived scores (passing) or
drifted ones (failing), and the rerank plan of the arms.py lists kept in the store
(new82/lists.json) is the expected pool union. Nothing here starts the container.
"""

import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _GD = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_GD)
    sys.modules["gd_common"] = gd
    _GD.loader.exec_module(gd)
if "graph_gd_score" in sys.modules:
    sc = sys.modules["graph_gd_score"]
else:
    _SPEC = importlib.util.spec_from_file_location("graph_gd_score", _DIR / "score.py")
    sc = importlib.util.module_from_spec(_SPEC)
    sys.modules["graph_gd_score"] = sc    # dataclasses resolve annotations through sys.modules
    _SPEC.loader.exec_module(sc)

needs_store = pytest.mark.skipif(not sc.EV_SCORES.is_file(), reason=f"store not mounted ({gd.STORE})")
STORE_LISTS = gd.OUT_ROOT / "new82" / "lists.json"     # arms.py --set new82 (驗收 A)
NEW82_UNION_PAIRS = 4936                                # Σ |D[0:20] ∪ every arm's extra| over 82 questions


@needs_store
def test_reference_pairs_are_the_first_32_of_ev_by_qid_and_pid():
    ref = sc.reference_pairs()
    assert len(ref) == sc.N_REF_PAIRS == 32
    assert [(q, p) for q, p, _ in ref] == sorted((q, p) for q, p, _ in ref)
    assert ref[0][:2] == ("N_BRL_01", "ps:act.22.6") and ref[-1][:2] == ("N_BRL_03", "ps:gen.13.1")
    assert all(type(s) is float for _, _, s in ref)


@needs_store
def test_reference_pair_items_use_the_new82_question_text_and_sorted_pids():
    items = sc.refpair_items(sc.reference_pairs(), gd.load_new82())
    assert [i["sid"] for i in items] == ["N_BRL_01", "N_BRL_02", "N_BRL_03"]
    assert all(i["pids"] == sorted(i["pids"]) for i in items)
    assert sum(len(i["pids"]) for i in items) == 32


@needs_store
def test_the_archived_container_meta_lines_pass_the_runner_checks():
    for path, kind in ((sc.EV_SCORES, "reranker"), (gd.PN / "encode_out.jsonl", "embedder")):
        metas = [r for r in sc.scan_jsonl(path).records if r.get("type") == "meta"]
        assert metas
        for line in metas:
            gd.verify_container_meta(line, kind)


@needs_store
def test_the_new82_rerank_plan_is_every_questions_pool_union():
    if not STORE_LISTS.is_file():
        pytest.skip(f"{STORE_LISTS} not written yet (arms.py --set new82)")
    name, lists = sc.load_lists(STORE_LISTS, None)
    assert name == "new82" and list(lists) == list(gd.load_new82().ids)
    unions = {q: sc.pool_union(q, entry) for q, entry in lists.items()}
    for q, entry in lists.items():
        arms = list(gd.entry_arms(entry))
        assert sorted(arms) == ["C", "G", "GD", "GD_DEGNORM", "L", "LEXPRF"]
        assert set(unions[q]) == set(entry["D30"][:20]).union(*map(set, (entry[a] for a in arms)))
    sizes = [len(u) for u in unions.values()]
    assert (sum(sizes), min(sizes), max(sizes)) == (NEW82_UNION_PAIRS, 46, 70)


class ArchiveContainer:
    """A fake container answering every pair with its archived EV score (+ shift)."""

    def __init__(self, shift=0.0):
        self.shift = shift
        self.ref = {(q, p): s for q, p, s in sc.reference_pairs()}

    def __call__(self, script, err_path, on_line):
        items = json.loads(base64.b64decode(script.split("\n", 1)[0].split('"')[1]).decode("utf-8"))
        on_line({"type": "meta", "build_id": gd.BUILD_ID,
                 "reranker_fingerprint": gd.expected_fingerprint("reranker"), **gd.RUN_SETTINGS["reranker"]})
        for item in items:
            on_line({"type": "r", "sid": item["sid"], "missing": [], "elapsed_s": 0.1,
                     "scores": {p: min(1.0, self.ref[item["sid"], p] + self.shift) for p in item["pids"]}})


@needs_store
@pytest.mark.parametrize("shift, code", [(0.0, 0), (5e-5, 2)])
def test_refpairs_writes_the_run_and_a_refcheck_that_fails_past_1e_5(tmp_path, monkeypatch, shift, code):
    monkeypatch.setattr(sc, "run_container", ArchiveContainer(shift))
    monkeypatch.setattr(gd, "container_image_id", lambda *a: gd.IMAGE_ID)
    out = tmp_path / "ref.jsonl"
    assert sc.main(["refpairs", "--out", str(out)]) == code
    lines = sc.scan_jsonl(out).records
    assert [r["type"] for r in lines] == ["meta", "r", "r", "r", "refcheck"]
    check = lines[-1]
    assert check["n_pairs"] == 32 and check["pass"] is (code == 0)
    assert check["max_abs_diff"] == pytest.approx(shift, abs=1e-12)
    assert check["source_sha256"] == gd.ARCHIVE_SHA256[gd.EV_SEL_OUT]
