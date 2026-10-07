"""K0: names, extra spans and parallel links from the mini snapshot (design §2.17, §5.2)."""

from __future__ import annotations

import copy

import pytest

import mini_build
import mini_kg
from ragdata.contract import parse_record
from ragdata.gates.schema import check_schema
from ragdata.kg import k0, k0_spans, registries
from ragdata.kg.registries import RegistryError

BOTH = ("text", "struct")


def _snapshot(text=None):
    files = mini_build.files(*BOTH)
    if text is not None:
        files.update({f"{name}.jsonl": rows for name, rows in text.items()})
    return check_schema(files, BOTH)[1]


@pytest.fixture()
def regs(tmp_path):
    def load(**docs):
        directory = tmp_path / f"r{len(list(tmp_path.iterdir()))}"
        versions = mini_kg.write_registries(directory, **docs)
        return registries.load_k0(directory), versions
    return load


def test_mini_snapshot_gives_the_oracle_rows(regs):
    loaded, versions = regs()
    result = k0.kg0_rows(_snapshot(), loaded)
    assert result.rows == mini_kg.kg0_layer(versions)
    for name, rows in result.rows.items():
        for row in rows:
            parse_record(name, row)


def test_counts_follow_the_rows(regs):
    loaded, versions = regs()
    result = k0.kg0_rows(_snapshot(), loaded)
    assert k0.kg0_counts(result, "text@x", "struct@y") == mini_kg.kg0_counts(
        versions, "text@x", "struct@y")


def test_report_names_the_rules_and_what_they_did(regs):
    loaded, versions = regs()
    report = k0.kg0_rows(_snapshot(), loaded).report
    assert report["registries"] == versions
    assert report["normalization"]["merge"] == {"鹽海": 1}
    assert report["normalization"]["suffix_outside"] == {"人": 0, "的": 1}
    assert report["normalization"]["generic_inside"] == {
        "types": 0, "occurrences": 0, "by_noun": {}}
    assert report["lexicon"]["skipped"] == {"min_len": 0, "book_citation": 0,
                                            "exclude_context": 0, "underline": 1}


def _text_with(**units):
    text = mini_build.text_layer()
    for row in text["verse_units"]:
        if row["unit_key"] in units:
            row["text_pdf"] = row["text"] = units[row["unit_key"]]
            row["text_sha256"] = mini_build.sha(row["text"])
    return text


def _divine(snapshot, loaded):
    return [(r["container_id"], r["start"], r["surface"])
            for r in k0.kg0_rows(snapshot, loaded).rows["extra_spans"]
            if r["source"] == "divine_rule"]


def test_divine_rule_skips_excluded_words_and_takes_the_longest(regs):
    loaded, _ = regs()
    text = _text_with(**{"sng.1.1": "主人說：主耶穌是神，不是神蹟。"})
    divine = loaded.divine
    patterns = (("dr.span.009", "主耶穌"), *divine.patterns)
    loaded = registries.K0Registries(loaded.normalization,
                                     registries.DivineRefs(divine.version, "body", patterns,
                                                           divine.exclusions), loaded.fixes)
    found = [d for d in _divine(_snapshot(text), loaded) if d[0] == "sng.1.1"]
    assert found == [("sng.1.1", 4, "主耶穌"), ("sng.1.1", 8, "神")]


def test_extra_spans_never_overlap_an_underline(regs):
    loaded, _ = regs()
    text = mini_build.text_layer()
    text["name_spans"].append(mini_build._span("mat.18.2", 0, "耶穌就"))
    text["name_spans"].sort(key=lambda s: s["span_id"])
    assert ("mat.18.2", 0, "耶穌") not in _divine(_snapshot(text), loaded)


def test_not_entity_spans_make_no_name_and_stay_blocking(regs):
    fixes = mini_kg.underline_fixes()
    fixes["not_entity"] = [{"id": "uf-001", "span_id": "ns:act.10.1@11", "surface": "哥尼流",
                            "decided_by": "kay", "why": "測試"}]
    loaded, _ = regs(underline_fixes=fixes)
    result = k0.kg0_rows(_snapshot(), loaded)
    assert "哥尼流" not in {n["norm_key"] for n in result.rows["names"]}
    assert result.report["not_entity"] == ["ns:act.10.1@11"]


@pytest.mark.parametrize("span_id, surface, message", [
    ("ns:act.10.1@12", "哥尼流", "no underline span"),
    ("ns:act.10.1@11", "哥尼", "surface"),
])
def test_not_entity_must_name_a_real_underline(regs, span_id, surface, message):
    fixes = mini_kg.underline_fixes()
    fixes["not_entity"] = [{"id": "uf-001", "span_id": span_id, "surface": surface,
                            "decided_by": "kay", "why": "測試"}]
    loaded, _ = regs(underline_fixes=fixes)
    with pytest.raises(RegistryError, match=message):
        k0.kg0_rows(_snapshot(), loaded)


def test_curated_underlines_become_curated_spans(regs):
    fixes = mini_kg.underline_fixes()
    fixes["curated_underline"] = [{"id": "uf-002", "container_id": "act.9.3", "start": 11,
                                   "surface": "小河", "decided_by": "kay", "why": "測試漏畫"}]
    loaded, versions = regs(underline_fixes=fixes)
    result = k0.kg0_rows(_snapshot(), loaded)
    curated = [r for r in result.rows["extra_spans"] if r["source"] == "curated_underline"]
    assert curated == [{
        "span_id": "ns:act.9.3@11", "container_id": "act.9.3", "region": "body", "start": 11,
        "end": 13, "surface": "小河", "source": "curated_underline", "rule_id": None,
        "registry_version": versions["underline_fixes"],
        "decision_ref": "underline_fixes.yaml#uf-002", "decided_by": "kay",
        "provenance_class": "curated_human"}]
    river = next(n for n in result.rows["names"] if n["norm_key"] == "小河")
    assert river["span_sources"] == ["curated_underline"] and river["body_occurrences"] == 1


def test_curated_underline_must_fit_the_text(regs):
    fixes = mini_kg.underline_fixes()
    fixes["curated_underline"] = [{"id": "uf-002", "container_id": "act.9.3", "start": 0,
                                   "surface": "小河", "decided_by": "kay", "why": "錯位"}]
    loaded, _ = regs(underline_fixes=fixes)
    with pytest.raises(RegistryError, match="does not read"):
        k0.kg0_rows(_snapshot(), loaded)


def test_lexicon_rules_skip_short_cited_and_excluded_words(regs):
    loaded, _ = regs()
    text = mini_build.text_layer()
    heads = {h["heading_id"]: h for h in text["headings"]}
    for hid, title in (("hd:mat.18.1#1", "掃羅王大馬士革上十章"), ("hd:eph.6.1#1", "鹽海與凱撒利亞")):
        heads[hid]["text_pdf"] = heads[hid]["text"] = heads[hid]["display_title"] = title
        heads[hid]["prov"]["glyph_range"] = [100, 100 + len(title) - 1]
    result = k0.kg0_rows(_snapshot(text), loaded)
    lexicon = [(r["container_id"], r["surface"]) for r in result.rows["extra_spans"]
               if r["source"] == "lexicon"]
    assert lexicon == [("hd:act.9.1#1", "掃羅"), ("hd:eph.6.1#1", "鹽海"),
                       ("hd:eph.6.1#1", "凱撒利亞")]
    assert result.report["lexicon"]["skipped"]["book_citation"] == 1
    assert result.report["lexicon"]["skipped"]["exclude_context"] == 1


def test_a_merge_group_outside_the_registry_is_refused(regs):
    norm = mini_kg.normalization()
    norm["rules"]["merge"]["groups"] = ["加利利海"]
    loaded, _ = regs(name_normalization=norm)
    with pytest.raises(RegistryError, match="鹽海"):
        k0.kg0_rows(_snapshot(), loaded)


def test_an_unknown_interpunct_is_refused(regs):
    loaded, _ = regs()
    text = mini_build.text_layer()
    unit = next(u for u in text["verse_units"] if u["unit_key"] == "act.10.1")
    unit["text_pdf"] = unit["text"] = "在凱撒・利亞有一個人名叫哥尼流。"
    unit["text_sha256"] = mini_build.sha(unit["text"])
    span = next(s for s in text["name_spans"] if s["span_id"] == "ns:act.10.1@1")
    span.update(surface="凱撒・利亞", end=6)
    other = next(s for s in text["name_spans"] if s["span_id"] == "ns:act.10.1@11")
    other.update(span_id="ns:act.10.1@12", start=12, end=15)
    with pytest.raises(RegistryError, match="interpunct"):
        k0.kg0_rows(_snapshot(text), loaded)


def test_parallel_links_skip_section_ranges(regs):
    loaded, _ = regs()
    text = mini_build.text_layer()
    section = copy.deepcopy(text["parallel_refs"][2])
    assert section["kind"] == "section_range"
    links = k0.kg0_rows(_snapshot(text), loaded).rows["parallel_links"]
    assert section["pr_id"] not in {link["pr_id"] for link in links}



def test_a_name_opening_a_book_title_is_a_citation(regs):
    rules = regs()[0].normalization.lexicon
    rows, skipped = k0_spans.lexicon_spans(
        [("fn:eph.6.1#1", "footnote", "路加與路加福音同")], {"路加"}, rules, "v", {})
    assert [r["start"] for r in rows] == [0]
    assert skipped["book_citation"] == 1
