"""R1 freeze (experiments/2026-10-08_r1/prereg.md).

The damaged slice and the G-ANS subset derive mechanically from the text
layer's diff report and GT v2, byte-identically on every run; ``--check``
catches any drift, and src.r1_frozen.load_frozen reads back only the pinned freeze.
Tests that re-derive read the real store and skip when it is not mounted.
"""

import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gt_v2 import load_ground_truth_v2
from src.r1_frozen import FrozenR1Error, load_frozen

_SCRIPT = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-08_r1" / "freeze_r1.py"
_SPEC = importlib.util.spec_from_file_location("freeze_r1", _SCRIPT)
fr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fr)

needs_store = pytest.mark.skipif(
    not fr.DIFF_TSV.is_file(), reason=f"text layer store not mounted ({fr.DIFF_TSV} missing)")

G02_QIDS = ["EVENT_QUESTION_041", "EVENT_QUESTION_094", "GENERAL_BIBLE_QUESTION_092",
            "PERSON_QUESTION_018", "TOPIC_QUESTION_049", "TOPIC_QUESTION_057",
            "TOPIC_QUESTION_084", "TOPIC_QUESTION_095", "TOPIC_QUESTION_096"]


@pytest.fixture(scope="module")
def frozen():
    return fr.derive()


@pytest.fixture(scope="module")
def gt_items():
    return {q.question_id: q for q in load_ground_truth_v2().items}


# ---------------------------------------------------------------- real derivation


@needs_store
def test_damaged_sub_slices_have_the_prereg_counts(frozen):
    subs = frozen["damaged_slice"]["sub_slices"]
    assert (subs["G01"]["n_containers"], subs["G01"]["n_questions"]) == (335, 56)
    assert (subs["G15"]["n_containers"], subs["G15"]["n_slots"], subs["G15"]["n_questions"]) \
        == (18, 18, 11)
    assert (subs["G02"]["n_containers"], subs["G02"]["n_slots"]) == (20, 20)
    assert subs["G02"]["question_ids"] == G02_QIDS
    union = frozen["damaged_slice"]["union"]["question_ids"]
    assert len(union) == 64
    assert set(union) == set().union(*(s["question_ids"] for s in subs.values()))


@needs_store
def test_g01_merged_units_count_each_of_their_verses(frozen):
    g01 = frozen["damaged_slice"]["sub_slices"]["G01"]
    merged = [c for c in g01["containers"] if "-" in c]
    assert merged == ["act.1.24-25", "jos.3.10-11", "psa.76.8-9"]
    assert g01["n_slots"] == 335 + len(merged)
    assert {"act.1.24", "act.1.25", "psa.76.8", "psa.76.9"} <= set(g01["slots"])


@needs_store
def test_gans_subset_takes_8_legacy_and_32_expanded_per_question_type(frozen, gt_items):
    subset = frozen["gans_subset"]["question_ids"]
    assert len(subset) == len(set(subset)) == 200
    assert set(subset) <= set(gt_items)
    strata = Counter((gt_items[q].question_type, gt_items[q].family == "legacy_head")
                     for q in subset)
    types = {q.question_type for q in gt_items.values()}
    assert strata == {**{(t, True): 8 for t in types}, **{(t, False): 32 for t in types}}
    for counts in frozen["gans_subset"]["strata"].values():
        assert (counts["legacy_head"]["n_selected"], counts["expanded"]["n_selected"]) == (8, 32)


@needs_store
def test_gans_subset_takes_the_smallest_digests_of_each_stratum(frozen, gt_items):
    chosen = set(frozen["gans_subset"]["question_ids"])
    pools: dict = {}
    for q in gt_items.values():
        pools.setdefault((q.question_type, q.family == "legacy_head"), []).append(q.question_id)
    for pool in pools.values():
        picked = [q for q in pool if q in chosen]
        worst_picked = max(fr.gans_rank(q) for q in picked)
        assert all(fr.gans_rank(q) > worst_picked for q in pool if q not in chosen)


@needs_store
def test_derivation_is_byte_identical_across_runs(frozen):
    assert fr.render(frozen) == fr.render(fr.derive())


@needs_store
def test_check_passes_on_the_written_freeze(capsys):
    assert fr.main(["--check"]) == 0
    assert "matches" in capsys.readouterr().out


@needs_store
def test_writing_reproduces_the_frozen_file_and_check_catches_drift(tmp_path):
    out = tmp_path / "frozen_r1.json"
    assert fr.main(["--out", str(out)]) == 0
    assert out.read_bytes() == fr.OUT.read_bytes()
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["gans_subset"]["question_ids"].pop()
    out.write_bytes(fr.render(doc))
    assert fr.main(["--check", "--out", str(out)]) == 1
    assert fr.main(["--check", "--out", str(tmp_path / "absent.json")]) == 1


def test_writing_refuses_to_replace_a_different_freeze_without_force(tmp_path, monkeypatch,
                                                                      capsys):
    monkeypatch.setattr(fr, "derive", lambda *_: json.loads(fr.OUT.read_text(encoding="utf-8")))
    out = tmp_path / "frozen_r1.json"
    out.write_bytes(fr.OUT.read_bytes())
    assert fr.main(["--out", str(out)]) == 0  # the same bytes: nothing is replaced
    doc = json.loads(fr.OUT.read_text(encoding="utf-8"))
    doc["gans_subset"]["salt"] = "edited"
    out.write_bytes(fr.render(doc))
    old = fr.sha256_of(out)
    assert fr.main(["--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert old in err and fr.sha256_of(fr.OUT) in err and "--force" in err
    assert fr.sha256_of(out) == old
    assert fr.main(["--out", str(out), "--force"]) == 0
    assert out.read_bytes() == fr.OUT.read_bytes()


def test_refuses_a_gt_that_is_not_the_frozen_bytes(tmp_path, capsys):
    gt = tmp_path / "ground_truth.v2.json"
    gt.write_bytes(fr.GT_V2_PATH.read_bytes() + b"\n")
    out = tmp_path / "frozen_r1.json"
    assert fr.main(["--gt", str(gt), "--out", str(out)]) == 2
    assert "not the frozen" in capsys.readouterr().err
    assert not out.exists()


# ---------------------------------------------------------------- pieces


def test_slots_of_expands_merged_units_and_keeps_slots():
    assert fr.slots_of("gen.24.29-30") == ["gen.24.29", "gen.24.30"]
    assert fr.slots_of("mat.18.11") == ["mat.18.11"]
    for bad in ("gen.24", "gen.24.x"):
        with pytest.raises(fr.FreezeError):
            fr.slots_of(bad)


def test_read_diff_rejects_a_foreign_header_or_a_short_row(tmp_path):
    tsv = tmp_path / "diff.tsv"
    tsv.write_text("container\tkind\n")
    with pytest.raises(fr.FreezeError, match="header"):
        fr.read_diff(tsv)
    tsv.write_text("\t".join(fr.TSV_COLUMNS) + "\ngen.1.1\tunit\n")
    with pytest.raises(fr.FreezeError, match=":2: 2 cells"):
        fr.read_diff(tsv)


def test_text_layer_refuses_unlisted_bytes_or_another_layer(tmp_path):
    tsv = tmp_path / "diff_vs_bible_md.tsv"
    tsv.write_text("\t".join(fr.TSV_COLUMNS) + "\n")
    manifest = {"layer_version": "text@aaaaaaaaaaaa", "files": {tsv.name: fr.sha256_of(tsv)}}
    (tmp_path / "layer_manifest.json").write_text(json.dumps(manifest))
    assert fr.text_layer(tsv, "text@aaaaaaaaaaaa")["layer_version"] == "text@aaaaaaaaaaaa"
    with pytest.raises(fr.FreezeError, match="slot_universe"):
        fr.text_layer(tsv, "text@bbbbbbbbbbbb")
    tsv.write_text("edited\n")
    with pytest.raises(fr.FreezeError, match="layer manifest lists"):
        fr.text_layer(tsv, "text@aaaaaaaaaaaa")


def test_gans_subset_refuses_a_stratum_smaller_than_its_quota():
    items = [SimpleNamespace(question_id=f"Q{i}", question_type="T",
                             family="legacy_head" if i < 7 else "parable")
             for i in range(7 + 32)]
    with pytest.raises(fr.FreezeError, match="T/legacy_head has 7 questions, fewer than 8"):
        fr.gans_subset(items)


# ---------------------------------------------------------------- load_frozen


def test_load_frozen_returns_union_sub_slices_and_subset():
    union, subs, gans = load_frozen()
    assert (len(union), len(gans)) == (64, 200)
    assert {k: len(v) for k, v in subs.items()} == {"G01": 56, "G15": 11, "G02": 9}
    assert subs["G02"] == frozenset(G02_QIDS)
    assert load_frozen(fr.OUT).damaged_union == union


def test_load_frozen_rejects_another_schema_or_a_union_that_does_not_add_up(tmp_path):
    doc = json.loads(fr.OUT.read_text(encoding="utf-8"))
    path = tmp_path / "frozen_r1.json"
    path.write_text(json.dumps({**doc, "schema": "other"}))
    with pytest.raises(FrozenR1Error, match="schema"):
        load_frozen(path)
    union = doc["damaged_slice"]["union"]
    union["question_ids"] = union["question_ids"][1:]
    union["n_questions"] -= 1
    path.write_text(json.dumps(doc))
    with pytest.raises(FrozenR1Error, match="union"):
        load_frozen(path)


def test_load_frozen_rejects_a_freeze_of_another_gt(tmp_path):
    doc = json.loads(fr.OUT.read_text(encoding="utf-8"))
    path = tmp_path / "frozen_r1.json"
    for field, value in (("sha256", "0" * 64), ("slot_universe", "text@000000000000")):
        path.write_bytes(fr.render({**doc, "gt": {**doc["gt"], field: value}}))
        with pytest.raises(FrozenR1Error, match=f"gt.{field} '{value}' is not GT v2's frozen"):
            load_frozen(path)


def test_load_frozen_rejects_an_id_swap_that_keeps_every_count(tmp_path):
    doc = json.loads(fr.OUT.read_text(encoding="utf-8"))
    subs, union = doc["damaged_slice"]["sub_slices"], doc["damaged_slice"]["union"]
    only_g01 = next(q for q in subs["G01"]["question_ids"]
                    if q not in subs["G15"]["question_ids"] + subs["G02"]["question_ids"])
    for ids in (subs["G01"]["question_ids"], union["question_ids"]):
        ids[ids.index(only_g01)] = "VERSE_LOOKUP_001"
    path = tmp_path / "frozen_r1.json"
    path.write_bytes(fr.render(doc))
    with pytest.raises(FrozenR1Error, match="is not the pinned freeze"):
        load_frozen(path)
    path.write_bytes(fr.OUT.read_bytes())
    assert load_frozen(path).damaged_union == load_frozen().damaged_union
