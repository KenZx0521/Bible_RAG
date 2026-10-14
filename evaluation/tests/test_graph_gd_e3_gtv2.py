"""GT v2 as a GD experiment question set (experiments/2026-10-14_graph_gd/_gd_gtv2.py).

The loader reads only the frozen repo file (sha256 7280bb42…, the freeze record's pin,
gt_version v2, the frozen slot_universe, 500 ids with the pinned §2 id sha) and keeps the
question text unchanged. The query arms.py would send is checked against what
quick_retrieval_eval.py and the collector send (gt.question of data_loader.load_gt): all
500 identical. Reading questions is not retrieval; nothing here encodes or scores them.
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
_EVAL = _DIR.parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))
from src.data_loader import load_gt  # noqa: E402


def test_the_pins_are_the_freeze_record_and_the_prereg_values():
    freeze = json.loads(gd.GTV2_FREEZE_PATH.read_text(encoding="utf-8"))
    assert (freeze["gt_path"], freeze["sha256"], freeze["slot_universe"]) == (
        gd.GTV2_PATH.name, gd.GTV2_SHA256, gd.GTV2_SLOT_UNIVERSE)
    assert gd.GTV2_SHA256.startswith("7280bb42")            # prereg §2
    assert gd.GTV2_SLOT_UNIVERSE == gd.LAYER_VERSIONS["text"]


def test_gtv2_loads_500_questions_in_file_order_with_the_pinned_id_sha():
    qs = gd.load_question_set("gtv2")
    rows = json.loads(gd.GTV2_PATH.read_text(encoding="utf-8"))["questions"]
    assert qs.name == "gtv2" and len(qs.questions) == gd.GTV2_SIZE == 500
    assert list(qs.ids) == [r["question_id"] for r in rows]
    assert [q.question for q in qs.questions] == [r["question"] for r in rows]
    assert [q.category for q in qs.questions] == [r["question_type"] for r in rows]
    assert all(q.hops == () and q.missing_hops is None for q in qs.questions)
    assert qs.ids_sha256 == gd.GTV2_IDS_SHA256 == gd.ids_sha256(r["question_id"] for r in rows)
    assert qs.sources[str(gd.GTV2_PATH)] == gd.GTV2_SHA256


@pytest.mark.parametrize("version", ["v2", "v1"])
def test_the_query_is_the_string_quick_retrieval_eval_and_the_collector_send(version):
    # both send gt.question of data_loader.load_gt (quick_retrieval_eval._query_one payload
    # "question"; collector.collect_responses -> query_rag(gt.question)); v1 is the default
    # EVAL_GT_VERSION, whose questions GT v2 keeps unchanged
    sent = {g.question_id: g.question for g in load_gt(version).items}
    ours = {q.qid: q.question for q in gd.load_question_set("gtv2").questions}
    assert sent == ours


def test_a_changed_file_or_freeze_record_is_refused(tmp_path):
    data = gd.GTV2_PATH.read_bytes()
    edited = tmp_path / "ground_truth.v2.json"
    edited.write_bytes(data.replace("約翰福音".encode(), "約翰褔音".encode(), 1))
    with pytest.raises(gd.IntegrityError, match="sha256"):
        gd.load_gtv2(edited)
    freeze = json.loads(gd.GTV2_FREEZE_PATH.read_text(encoding="utf-8"))
    bad = tmp_path / "freeze.json"
    bad.write_text(json.dumps({**freeze, "sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(gd.IntegrityError, match="freeze"):
        gd.load_gtv2(gd.GTV2_PATH, bad)


def test_load_question_set_knows_gtv2_and_still_delegates_the_others(monkeypatch):
    seen = []
    monkeypatch.setattr(sys.modules["_gd_sets"], "load_question_set", lambda n: seen.append(n) or n)
    assert gd.load_question_set("new82") == "new82" and seen == ["new82"]
    assert gd.load_question_set("gtv2").name == "gtv2" and seen == ["new82"]
    with pytest.raises(gd.GdError, match="gtv2"):
        gd.load_question_set("gt_v3")


def test_the_gtv2_module_is_hashed_into_every_meta():
    assert gd.EXP_DIR / "_gd_gtv2.py" in gd.MODULE_FILES
    assert "_gd_gtv2.py" in gd.collect_meta()["sha256"]
