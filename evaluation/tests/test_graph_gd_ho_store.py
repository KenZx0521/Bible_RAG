"""GD experiment HO loader and §7 mechanical checks (experiments/2026-10-14_graph_gd/_gd_sets.py).

Split from test_graph_gd_common.py. With the store mounted, HO items built on verses
outside the NEW82 ∪ OLD31 gold must load (categories from the id prefix, the frozen
sha256, the [SHORTCUT] flag from change_log), and each broken item must be refused.
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

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# ---------------------------------------------------------------- store: HO checks (§7)

def _free_verses(n):
    """n whole-verse keys, each in its own passage outside the NEW82 ∪ OLD31 gold."""
    used = {p for s in (gd.load_new82(), gd.load_old31()) for q in s.questions
            for gold in gd.question_gold(q) for p in gold}
    vi, out = gd.load_verse_index(), {}
    for key in gd.load_verse_units().order:
        pid = vi.passage_of[key]
        if "-" not in key and not vi.split_of[key] and pid not in used and pid not in out:
            out[pid] = key
            if len(out) == n:
                return list(out.values())
    raise AssertionError("not enough free passages")


def ho_item(qid, hops, core, category=None):
    cat = category or {"H_KIN_": "KIN", "H_DIS_": "DIS", "H_TO_": "TO", "H_MH_": "SUC"}[
        next(p for p in gd.HO_CATEGORY if qid.startswith(p))]
    item = {f: "" for f in gd.HO_FIELDS}
    return {**item, "id": qid, "category": cat, "question": f"{qid}?", "hop_slots": hops,
            "core": core, "n_hops": len(hops), "hops": []}


@needs_store
def test_a_well_formed_ho_set_loads_with_categories_from_the_id_prefix(tmp_path):
    v = _free_verses(4)
    path = tmp_path / "heldout_ho.json"
    path.write_text(json.dumps({"questions": [ho_item("H_KIN_01", [[v[0]], [v[1]]], "a"),
                                              ho_item("H_MH_01", [[v[2]], [v[3]]], "a")]}))
    s = gd.load_ho(path, expected_sha256=gd.file_sha256(path))
    assert [(q.category, q.core, q.missing_hops, q.shortcut) for q in s.questions] == [
        (gd.KIN, "a", None, False), (gd.MH, "a", None, False)]
    with pytest.raises(gd.IntegrityError):
        gd.load_ho(path, expected_sha256="0" * 64)


@needs_store
def test_ho_mechanical_checks_reject_each_broken_item():
    v = _free_verses(7)
    new82_key = gd.load_new82().questions[0].hops[0][0]
    ok = [[v[0]], [v[1]]]
    cases = {
        "half verse": [ho_item("H_TO_01", [[v[0] + "b"], [v[1]]], "c")],
        "bad prefix": [ho_item("H_XX_01", ok, "c", category="KIN")],
        "NULL category": [ho_item("H_KIN_01", ok, "c", category="NULL")],
        "one hop": [ho_item("H_KIN_01", [[v[0]]], "c")],
        "six hops": [ho_item("H_KIN_01", [[x] for x in v[:6]], "c")],
        "range key": [ho_item("H_KIN_01", [[f"{v[0]}-{v[1]}"], [v[2]]], "c")],
        "hops share gold": [ho_item("H_KIN_01", [[v[0]], [v[0]]], "c")],
        "overlaps NEW82": [ho_item("H_KIN_01", [[new82_key], [v[1]]], "c")],
        "two HO share gold": [ho_item("H_KIN_01", ok, "c"),
                              ho_item("H_DIS_01", [[v[0]], [v[2]]], "d")],
        "core used thrice": [ho_item(f"H_TO_0{i}", [[v[2 * i]], [v[2 * i + 1]]], "c")
                             for i in range(3)],
        "missing core": [{k: x for k, x in ho_item("H_KIN_01", ok, "c").items() if k != "core"}],
        "blank question": [{**ho_item("H_KIN_01", ok, "c"), "question": " "}],
        "duplicate id": [ho_item("H_KIN_01", ok, "c"), ho_item("H_KIN_01", [[v[2]], [v[3]]], "d")],
        "change_log not a string": [{**ho_item("H_KIN_01", ok, "c"), "change_log": ["[SHORTCUT]"]}],
    }
    for name, items in cases.items():
        with pytest.raises(gd.GdError):
            gd.check_ho_items(items)
            pytest.fail(name)


@needs_store
def test_ho_change_log_marks_shortcut_questions():
    v = _free_verses(4)
    items = [{**ho_item("H_KIN_01", [[v[0]], [v[1]]], "a"), "change_log": "1) 改寫 [SHORTCUT] 單段可取回"},
             {**ho_item("H_TO_01", [[v[2]], [v[3]]], "b"), "change_log": "1) 措辭"}]
    assert [q.shortcut for q in gd.check_ho_items(items)] == [True, False]
