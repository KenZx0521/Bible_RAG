"""GD experiment §8 E3 against the store and the real quick_retrieval_eval.py (synthetic raw only).

* run_meta.json equals the one the R2 collector archived from /health (store
  reports/r2eval/gans_R2/run_meta.json), and every passage source of that R2 raw file has
  exactly the fields the struct / text layers give (_e3_build.load_source_rows).
* The pipeline end to end on synthetic raw dirs built from each GT v2 question's own gold
  passages (no arms, no scores, no dense, no reranker, no encoding; nothing passes the
  guard): identical C and GD pass all three gates (Δ 0, W+L 0, gold_out 0); a GD that drops
  the gold of 12 questions fails gate 3; metric_version is 4d0826bb8d14, every output lands
  in the given destination and results_quick lists exactly as before.
* §10: every module e3_raw.py loads from the experiment directory or evaluation/ is in its
  meta (SOURCE_FILES + gd_common.MODULE_FILES), checked in a fresh interpreter.
"""

import importlib.util
import json
import shutil
import subprocess
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

R2_RUN = gd.STORE / "reports" / "r2eval" / "gans_R2"
CONTRACT_INDEX = gd.STORE / "contracts" / gd.BUILD_ID / "verse_index.json"
needs_store = pytest.mark.skipif(not (R2_RUN / "run_meta.json").is_file() or not CONTRACT_INDEX.is_file(),
                                 reason=f"store not mounted ({gd.STORE})")
N_LOST = 12


@needs_store
def test_run_meta_is_what_the_r2_collector_recorded_from_health():
    assert B.run_meta_doc() == json.loads((R2_RUN / "run_meta.json").read_text(encoding="utf-8"))


@needs_store
def test_layer_source_rows_equal_the_passage_sources_the_r2_backend_returned():
    rows = B.load_source_rows()
    assert len(rows) == gd.N_PASSAGES
    seen = 0
    for item in json.loads((R2_RUN / "raw_responses.json").read_text(encoding="utf-8")):
        for src in item["sources"]:
            if src["kind"] != "passage":
                continue
            ours = B.passage_source(rows[src["id"]], src["score"], "C")
            keys = ("id", "book", "chapter", "title", "verse_range", "kind", "start_key", "end_key")
            assert {k: ours[k] for k in keys} == {k: src[k] for k in keys}
            seen += 1
    assert seen > 500


# ---------------------------------------------------------------- end to end on synthetic raw dirs

def synthetic_dirs(root: Path, k: int, lost: int) -> dict[str, Path]:
    """C and GD raw dirs of each question's own gold passages padded with fixed non-gold
    ones; GD drops the gold of the first `lost` questions (sorted qid)."""
    qset = gd.load_question_set(gd.GTV2)
    gt = {q["question_id"]: q for q in json.loads(gd.GTV2_PATH.read_text(encoding="utf-8"))["questions"]}
    owners: dict[str, set[str]] = {}
    for s in json.loads(CONTRACT_INDEX.read_text(encoding="utf-8"))["slots"]:
        if s["passage_id"]:
            owners[s["slot_key"]] = {s["passage_id"], *s["split_passage_ids"]}
    rows = B.load_source_rows()
    gold = {q: sorted(set().union(*(owners.get(s, set()) for s in gt[q]["gold_slots"]))) for q in qset.ids}
    dropped = set(sorted(q for q in qset.ids if gold[q])[:lost])

    def pick(qid: str, drop: bool) -> list[str]:
        own = [] if drop else gold[qid][:k]
        return own + [p for p in sorted(rows) if p not in gold[qid]][:k - len(own)]

    dirs = {}
    for name, arm, drop in (("C", "C", set()), ("GD", "GD", set()), ("GDlost", "GD", dropped)):
        raw = [B.raw_item(q.qid, q.question, [B.passage_source(rows[p], 0.5, arm)
                                              for p in pick(q.qid, q.qid in drop)], arm)
               for q in qset.questions]
        B.write_raw_dir(root / name, raw)
        dirs[name] = root / name
    return dirs


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("e3")
    before = R.listing()
    dirs = synthetic_dirs(root / "raw", 5, N_LOST)
    for name, path in dirs.items():
        e3_raw.run(path, 5, "C" if name == "C" else "GD", root / "out" / name, allow_unpinned=True)
    return root, before


@needs_store
def test_runs_land_in_their_destination_with_metric_version_and_results_quick_unchanged(runs):
    root, before = runs
    assert R.listing() == before
    for name in ("C", "GD", "GDlost"):
        rec = json.loads((root / "out" / name / R.RECORD_NAME).read_text(encoding="utf-8"))
        assert rec["metric_version"] == "4d0826bb8d14" and rec["results_quick_unchanged"] is True
        assert rec["pinned"] is False and rec["summary"]["n"] == 500
        assert Path(rec["quick_eval"]) == root / "out" / name / R.QUICK_NAME
        assert not (R.RESULTS_QUICK / f"{rec['label']}.json").exists()


@needs_store
def test_identical_arms_pass_and_dropping_gold_fails_gate_3(runs):
    root, _ = runs
    out = root / "out"
    same, code = e3_raw.gates({5: (out / "C", out / "GD")}, root / "same.json", allow_unpinned=True)
    k5 = same["k5"]
    assert code == 0 and same["passed"]
    assert k5["vrec"]["ci95"] == [0.0, 0.0] and k5["vrec"]["mean_diff"] == 0.0
    assert (k5["mrr"]["wins"], k5["mrr"]["losses"], k5["mrr"]["no_discordant"]) == (0, 0, True)
    assert (k5["slot"]["gold_out"], k5["slot"]["gained"]) == (0, 0)
    lost, code = e3_raw.gates({5: (out / "C", out / "GDlost")}, root / "lost.json", allow_unpinned=True)
    assert code == 1 and not lost["passed"]
    assert lost["k5"]["slot"]["gold_out"] == N_LOST and lost["k5"]["slot"]["pass"] is False


@needs_store
def test_official_gates_refuse_unpinned_runs(runs):
    root, _ = runs
    out = root / "out"
    with pytest.raises(gd.GdError, match="e3_build.json|locked"):
        e3_raw.gates({5: (out / "C", out / "GD")}, root / "pinned.json", allow_unpinned=False)


@needs_store
def test_a_run_whose_output_changed_after_the_run_is_refused(runs, tmp_path):
    root, _ = runs
    copy = tmp_path / "C"
    shutil.copytree(root / "out" / "C", copy)
    R.load_run(copy, gd.load_question_set(gd.GTV2))
    doc = json.loads((copy / R.QUICK_NAME).read_text(encoding="utf-8"))
    doc["per_question"]["VERSE_LOOKUP_001"]["mrr"] = 0.0
    (copy / R.QUICK_NAME).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(gd.IntegrityError, match="sha256"):
        R.load_run(copy, gd.load_question_set(gd.GTV2))


# ---------------------------------------------------------------- §10 meta coverage

PROBE = """
import json, sys
from pathlib import Path
sys.argv = ["probe"]
exp = Path({exp!r})
sys.path.insert(0, str(exp))
import gd_common as gd
import e3_raw as mod
declared = {{str(Path(p).resolve()) for p in [*mod.SOURCE_FILES.values(), *gd.MODULE_FILES]}}
ev = exp.parents[1]
mine = lambda p: p.parent in (exp, ev) or p.is_relative_to(ev / "src")
loaded = sorted(str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                if getattr(m, "__file__", None) and mine(Path(m.__file__).resolve()))
print(json.dumps({{"missing": sorted(set(loaded) - declared), "n": len(loaded)}}))
"""


def test_every_module_e3_raw_loads_is_hashed_into_its_meta():
    proc = subprocess.run([sys.executable, "-B", "-c", PROBE.format(exp=str(_DIR))],
                          capture_output=True, text=True, cwd=_DIR, check=True)
    out = json.loads(proc.stdout)
    assert out["missing"] == [] and out["n"] >= 20
