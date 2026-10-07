"""``stages.build("text")``: S0–S2 on six real PDFs, its gates, and G-DET over two runs.

The fixture books cover the special cases of the text body: rut and jon (plain
prose and poetry), hab (selah, twice in mid-verse), zep (a merged verse), ezr
(123 glyphs typeset past the page edge) and mrk (two omitted variant slots, 90
parallel-reference lines, a merge group); ezr and mrk cite verses in footnotes.
Records are diffed against the audit's canonical_full.jsonl when it is present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragdata import stages, store
from ragdata.gates import check_det, check_schema, sourced
from ragdata.gates.base import GateInputError
from ragdata.gates.runner import GateInputs, gate_layer, merge_files
from ragdata.store import read_layer

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
COUNTS = HERE / "fixture_counts.yaml"
EXPECT = HERE / "fixture_source_expect.yaml"
DIFF_EXPECT = HERE / "fixture_diff_expect.yaml"
CANONICAL = Path("/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/gap_pdf_canonical/"
                 "canonical_full.jsonl")
FILES = ("路得記", "約拿書", "哈巴谷書", "西番雅書", "以斯拉記", "馬可福音")
BOOKS = ("rut", "ezr", "jon", "hab", "zep", "mrk")
REPORTS = ("xcheck_report.json", "overlay_report.json", "diff_vs_bible_md.tsv",
           "diff_vs_canonical_full.tsv", "diff_summary.json")


def _pdf_dir(root: Path) -> Path:
    root.mkdir()
    for name in FILES:
        (root / f"{name}.pdf").symlink_to(REPO / "bible_pdf" / f"{name}.pdf")
    return root


def _build(tmp: Path, store: str = "store", **kwargs) -> stages.BuildResult:
    pdf_dir = tmp / "pdf" if (tmp / "pdf").exists() else _pdf_dir(tmp / "pdf")
    kwargs.setdefault("inputs", stages.TextInputs(diff_expect=DIFF_EXPECT))
    return stages.build("text", pdf_dir, tmp / store, counts_path=COUNTS, expect_path=EXPECT,
                        **kwargs)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("build")
    return tmp, _build(tmp)


def test_the_build_passes_its_gates_and_writes_src_and_text(built):
    _, result = built
    assert result.passed, [g.details for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-TOOL", "G-SRC", "G-CONSERVE", "G-COUNT",
                                              "G-REFINT", "G-TEXT", "G-XCHECK", "G-DIFF"]
    src, text = read_layer(result.layers["src"].path), read_layer(result.layers["text"].path)
    assert set(src.file_shas) == {"source_manifest.json", "depends_on.json",
                                  *(f"extract_{b}.jsonl" for b in BOOKS)}
    assert set(text.file_shas) == {"depends_on.json", *(f"{t}.jsonl" for t in stages.TEXT_TYPES),
                                   *REPORTS}
    assert text.depends_on == {"src": src.version}
    assert [r["book_id"] for r in text.rows["books.jsonl"]] == list(BOOKS)


def test_the_report_accounts_for_every_glyph_with_a_record(built):
    _, result = built
    doc = json.loads(json.dumps(result.to_json()))
    assert doc["pass"] is True and doc["layers"]["text"]["version"].startswith("text@")
    conserve = next(g for g in doc["gates"] if g["name"] == "G-CONSERVE")
    assert conserve["observed"]["output"] == conserve["observed"]["source"]
    assert conserve["observed"]["output"]["navy"] == 2807
    assert set(doc["timings_s"]) == {"s0_s1_extract", "s2_parse", "s4_overlay", "s3_xcheck",
                                     "diffs", "gates", "store"}


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


def _reference_annotations() -> dict[str, set]:
    keys = {"heading": ("offset", "text"), "parallel_ref": ("text",), "footnote": ("n", "text"),
            "name": ("start", "surface"), "speaker": ("offset", "text")}
    found: dict[str, set] = {kind: set() for kind in keys}
    with CANONICAL.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["book"] not in BOOKS or row["status"] != "present":
                continue
            for a in row["annotations"]:
                if a["type"] in keys:
                    found[a["type"]].add((row["id"], *(a[k] for k in keys[a["type"]])))
    return found


@pytest.mark.skipif(not CANONICAL.exists(), reason="audit reference not available")
def test_headings_references_footnotes_and_names_agree_with_the_audit_reference(built):
    _, result = built
    rows = read_layer(result.layers["text"].path).rows
    anchor = {h["heading_id"]: h["anchor_unit_key"] for h in rows["headings.jsonl"]}
    mine = {
        "heading": {(h["anchor_unit_key"], h["anchor_offset"], h["text_pdf"])
                    for h in rows["headings.jsonl"]},
        "parallel_ref": {(anchor[p["heading_id"]], p["raw"]) for p in rows["parallel_refs.jsonl"]},
        "footnote": {(f["unit_key"], f["n"], f["text_pdf"]) for f in rows["footnotes.jsonl"]},
        "name": {(n["container_id"], n["start"], n["surface"]) for n in rows["name_spans.jsonl"]
                 if n["region"] == "body"},
        "speaker": {(s["unit_key"], s["offset"], s["text_pdf"]) for s in rows["speakers.jsonl"]},
    }
    assert mine == _reference_annotations()


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
    (COUNTS, "headings: {value: 138", "headings: {value: 137", "G-COUNT"),
    (EXPECT, "路得記.pdf: 1", "路得記.pdf: 0", "G-SRC"),
    (EXPECT, "mutool: 1.23.10", "mutool: 1.23.9", "G-TOOL"),
    (DIFF_EXPECT, "loss.units: 18", "loss.units: 17", "G-DIFF"),
])
def test_a_red_build_stores_no_layer(built, tmp_path, pinned, old, new, gate):
    tmp, _ = built
    edited = tmp_path / pinned.name
    edited.write_text(pinned.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    paths = {"counts_path": COUNTS, "expect_path": EXPECT,
             "inputs": stages.TextInputs(diff_expect=DIFF_EXPECT)}
    if pinned == DIFF_EXPECT:
        paths["inputs"] = stages.TextInputs(diff_expect=edited)
    else:
        paths["counts_path" if pinned == COUNTS else "expect_path"] = edited
    result = stages.build("text", tmp / "pdf", tmp_path / "store", **paths)
    assert not result.passed
    assert [g.name for g in result.gates if g.hard and not g.passed] == [gate]
    assert result.layers == {} and result.to_json()["layers"] == {}
    assert not (tmp_path / "store").exists()


def _gate_stored(built, text_path=None, gates=None):
    tmp, result = built
    return gate_layer(text_path or result.layers["text"].path, "text",
                      [result.layers["src"].path], COUNTS, gates=gates,
                      inputs=GateInputs(pdf_dir=tmp / "pdf", source_expect=EXPECT))


def test_the_stored_layer_passes_every_required_gate_again_from_its_sources(built):
    report = _gate_stored(built)
    assert report.passed, [(g.name, g.details) for g in report.gates if not g.passed]
    xcheck = next(g for g in report.gates if g.name == "G-XCHECK")
    assert xcheck.observed["raw"] == xcheck.observed["layout"] == 1197


def test_gate_time_conserve_catches_a_glyph_missing_from_the_stored_records(built, tmp_path):
    _, result = built
    data = read_layer(result.layers["text"].path)
    rows = {name[:-6]: [dict(r) for r in data.rows[name]] for name in data.rows}
    unit = next(u for u in rows["verse_units"] if u["unit_key"] == "rut.1.1")
    cut = unit["text_pdf"][:-1]
    unit.update(text_pdf=cut, text=cut, text_sha256=mini_build_sha(cut), line_breaks=[])
    files = {f"{name}.jsonl": store.encode_jsonl(r) for name, r in rows.items()}
    other = store.write_layer(tmp_path, "text", files, depends_on=dict(data.depends_on))
    report = _gate_stored(built, other.path, gates=["G-CONSERVE"])
    assert not report.gates[0].passed and "rut body" in " ".join(report.gates[0].details)


def test_gate_time_xcheck_requires_the_stored_report_to_match(built):
    tmp, result = built
    _, snap = check_schema(merge_files([read_layer(result.layers["text"].path)]), ["text"])
    assert not sourced.xcheck_from_pdfs(snap, tmp / "pdf", b"{}\n").passed


def test_gate_time_conserve_needs_every_extract(built):
    _, result = built
    _, snap = check_schema(merge_files([read_layer(result.layers["text"].path)]), ["text"])
    with pytest.raises(GateInputError, match="extract_rut"):
        sourced.conserve_from_src(snap, {}, EXPECT)


def test_the_layer_stores_its_reports(built):
    _, result = built
    text = result.layers["text"].path
    xcheck = json.loads((text / "xcheck_report.json").read_text(encoding="utf-8"))
    assert xcheck["units"] == xcheck["containment"]["raw"]["contained"] == 1197
    assert xcheck["gaps"]["unexplained"] == [] and xcheck["gaps"]["explained"] > 0
    assert all(c["poppler"] == c["layer"] and not c["books_off"]
               for c in xcheck["characters"].values())
    summary = json.loads((text / "diff_summary.json").read_text(encoding="utf-8"))
    assert summary["bible_md"]["by_class"]["other"]["rows"] == 0
    assert all(r["match"] for r in summary["reconciliation"])
    overlay = json.loads((text / "overlay_report.json").read_text(encoding="utf-8"))
    assert overlay["errata"]["applied"] == 0 and overlay["ref_aliases"]["emitted"] == 0



def test_the_reports_name_the_inputs_that_shaped_the_layer(built):
    _, result = built
    text = result.layers["text"].path
    overlay = json.loads((text / "overlay_report.json").read_text(encoding="utf-8"))
    registry = REPO / "config" / "registries" / "errata.yaml"
    assert overlay["registries"]["errata.yaml"] == mini_build_sha_bytes(registry.read_bytes())
    assert set(overlay["registries"]) == {"errata.yaml", "normalization.yaml",
                                          "versification.yaml"}
    inputs = json.loads((text / "diff_summary.json").read_text(encoding="utf-8"))["inputs"]
    assert inputs["diff_expect"] == mini_build_sha_bytes(DIFF_EXPECT.read_bytes())
    assert set(inputs) == {"bible_md", "canonical_full", "diff_expect"}


def mini_build_sha_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def mini_build_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
