"""``stages.build("text")``: S0–S2a on six real PDFs, its gates, and G-DET over two runs.

The fixture books cover the special cases of the text body: rut and jon (plain
prose and poetry), hab (selah, twice in mid-verse), zep (a merged verse), ezr
(123 glyphs typeset past the page edge) and mrk (two omitted variant slots).
Records are diffed against the audit's canonical_full.jsonl when it is present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragdata import stages
from ragdata.gates import check_det
from ragdata.store import read_layer

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
COUNTS = HERE / "fixture_counts.yaml"
EXPECT = HERE / "fixture_source_expect.yaml"
CANONICAL = Path("/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/gap_pdf_canonical/"
                 "canonical_full.jsonl")
FILES = ("路得記", "約拿書", "哈巴谷書", "西番雅書", "以斯拉記", "馬可福音")
BOOKS = ("rut", "ezr", "jon", "hab", "zep", "mrk")


def _pdf_dir(root: Path) -> Path:
    root.mkdir()
    for name in FILES:
        (root / f"{name}.pdf").symlink_to(REPO / "bible_pdf" / f"{name}.pdf")
    return root


def _build(tmp: Path, store: str = "store", **kwargs) -> stages.BuildResult:
    pdf_dir = tmp / "pdf" if (tmp / "pdf").exists() else _pdf_dir(tmp / "pdf")
    return stages.build("text", pdf_dir, tmp / store, counts_path=COUNTS, expect_path=EXPECT,
                        **kwargs)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("build")
    return tmp, _build(tmp)


def test_the_build_passes_its_gates_and_writes_src_and_text(built):
    _, result = built
    assert result.passed, [g.details for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-TOOL", "G-SRC", "G-CONSERVE", "G-COUNT"]
    src, text = read_layer(result.layers["src"].path), read_layer(result.layers["text"].path)
    assert set(src.file_shas) == {"source_manifest.json", "depends_on.json",
                                  *(f"extract_{b}.jsonl" for b in BOOKS)}
    assert set(text.file_shas) == {"books.jsonl", "chapters.jsonl", "verse_units.jsonl",
                                   "verse_slots.jsonl", "depends_on.json"}
    assert text.depends_on == {"src": src.version}
    assert [r["book_id"] for r in text.rows["books.jsonl"]] == list(BOOKS)


def test_the_report_names_what_s2b_still_owes(built):
    _, result = built
    doc = json.loads(json.dumps(result.to_json()))
    assert doc["pass"] is True and doc["layers"]["text"]["version"].startswith("text@")
    conserve = next(g for g in doc["gates"] if g["name"] == "G-CONSERVE")
    assert conserve["observed"]["pending_s2b"]["navy"] == 2807
    assert set(doc["timings_s"]) == {"s0_s1_extract", "s2_parse", "gates", "store"}


def test_omitted_slots_link_to_their_variant_footnotes(built):
    _, result = built
    slots = read_layer(result.layers["text"].path).rows["verse_slots.jsonl"]
    omitted = {s["slot_key"]: s["variant_footnote_id"] for s in slots
               if s["status"] == "omitted_variant"}
    assert omitted == {"mrk.7.16": "fn:mrk.7.15#1", "mrk.15.28": "fn:mrk.15.27#1"}


@pytest.mark.skipif(not CANONICAL.exists(), reason="audit reference not available")
def test_units_agree_with_the_audit_reference(built):
    _, result = built
    units = read_layer(result.layers["text"].path).rows["verse_units.jsonl"]
    reference = {}
    with CANONICAL.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["book"] in BOOKS and row["status"] == "present":
                reference[row["id"]] = row
    assert {u["unit_key"] for u in units} == set(reference)
    for u in units:
        ref = reference[u["unit_key"]]
        selah = [{"type": "selah", "start": a["start"], "end": a["end"]}
                 for a in ref["annotations"] if a["type"] == "selah"]
        assert (u["text_pdf"], u["pages"], u["markers"], u["prov"]["first_glyph"]) == \
            (ref["text"], ref["pages"], selah, ref["prov"]["first_glyph"]), u["unit_key"]
        assert [b["offset"] for b in u["line_breaks"]] == ref["line_starts"][1:]


def test_two_builds_are_identical_file_by_file(built, tmp_path):
    first_tmp, first = built
    (tmp_path / "pdf").symlink_to(first_tmp / "pdf", target_is_directory=True)
    second = _build(tmp_path, workers=2)
    for layer in ("src", "text"):
        result = check_det(first.layers[layer].path, second.layers[layer].path)
        assert result.passed, result.details


def test_rebuilding_into_the_same_store_reuses_the_versions(built):
    tmp, first = built
    again = _build(tmp)
    assert {k: v.version for k, v in again.layers.items()} == \
        {k: v.version for k, v in first.layers.items()}


@pytest.mark.parametrize("pinned, old, new, gate", [
    (COUNTS, "value: 1197", "value: 1196", "G-COUNT"),
    (EXPECT, "路得記.pdf: 1", "路得記.pdf: 0", "G-SRC"),
    (EXPECT, "mutool: 1.23.10", "mutool: 1.23.9", "G-TOOL"),
])
def test_a_red_build_stores_no_layer(built, tmp_path, pinned, old, new, gate):
    tmp, _ = built
    edited = tmp_path / pinned.name
    edited.write_text(pinned.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    paths = {"counts_path": COUNTS, "expect_path": EXPECT}
    paths["counts_path" if pinned == COUNTS else "expect_path"] = edited
    result = stages.build("text", tmp / "pdf", tmp_path / "store", **paths)
    assert not result.passed
    assert [g.name for g in result.gates if g.hard and not g.passed] == [gate]
    assert result.layers == {} and result.to_json()["layers"] == {}
    assert not (tmp_path / "store").exists()


def test_only_the_text_layer_has_a_stage(tmp_path):
    with pytest.raises(ValueError, match="struct"):
        stages.build("struct", tmp_path, tmp_path / "store")
