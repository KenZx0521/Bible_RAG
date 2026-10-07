"""G-KG0 and G-PROV over the mini kg0 rows (design §8)."""

from __future__ import annotations

import copy

import pytest

import mini_build
import mini_kg
from ragdata.gates.kg0 import check_kg0
from ragdata.gates.prov import check_prov
from ragdata.gates.schema import check_schema

LAYERS = ("text", "struct", "kg0")
VERSIONS = {"divine_refs": "divine_refs@aaaaaaaaaaaa",
            "name_normalization": "name_normalization@bbbbbbbbbbbb",
            "underline_fixes": "underline_fixes@cccccccccccc"}
DEPENDS = {"text": "text@111111111111", "struct": "struct@222222222222"}


def _files(kg0=None):
    files = mini_build.files("text", "struct")
    rows = mini_kg.kg0_layer(VERSIONS) if kg0 is None else kg0
    files.update({f"{name}.jsonl": table for name, table in rows.items()})
    return files


def _report(**changes):
    return {"registries": dict(VERSIONS), "not_entity": [], **changes}


def _expected(**changes):
    doc = mini_kg.kg0_counts(VERSIONS, DEPENDS["text"], DEPENDS["struct"])
    doc.update(changes)
    return doc


def _gate(kg0=None, report=None, expected=None):
    schema, snap = check_schema(_files(kg0), LAYERS)
    assert schema.passed, schema.details
    return check_kg0(snap, report or _report(), expected or _expected(), DEPENDS)


def test_mini_kg0_passes():
    result = _gate()
    assert result.passed, result.details
    assert result.name == "G-KG0" and result.hard


def _mutated(mutate):
    rows = copy.deepcopy(mini_kg.kg0_layer(VERSIONS))
    mutate(rows)
    return rows


def _span(rows, surface):
    return next(r for r in rows["extra_spans"] if r["surface"] == surface)


def _shift(row, start):
    row.update(start=start, end=start + len(row["surface"]),
               span_id=f"ns:{row['container_id']}@{start}")


MUTATIONS = {
    "span off its text": lambda r: _shift(_span(r, "主"), 6),
    "span over an underline": lambda r: (_span(r, "掃羅").update(
        container_id="fn:act.9.1#1", region="footnote", span_id="ns:fn:act.9.1#1@0")),
    "two extra spans overlap": lambda r: r["extra_spans"].append(
        {**r["extra_spans"][0], "span_id": "ns:psa.42.1@1", "start": 1, "end": 2,
         "surface": "帝"}),
    "lexicon word that is no name": lambda r: _span(r, "掃羅").update(surface="歸主", start=2,
                                                                     end=4,
                                                                     span_id="ns:hd:act.9.1#1@2"),
    "name dropped": lambda r: r["names"].pop(),
    "occurrences off": lambda r: r["names"][0].update(body_occurrences=3),
    "name with a stray dot": lambda r: r["names"][0].update(norm_key="掃・羅"),
    "section range linked": lambda r: r["parallel_links"].append(
        {**r["parallel_links"][0], "pr_id": "pr:hd:act.9.1#1#1",
         "link_key": "pr:hd:act.9.1#1#1|pc:act.9.1", "from_pericope": "pc:act.9.3b"}),
    "link from the wrong pericope": lambda r: r["parallel_links"][0].update(
        from_pericope="pc:psa.42.1"),
    "link to a pericope the target misses": lambda r: r["parallel_links"][1].update(
        to_pericope="pc:act.9.1", link_key="pr:hd:mat.18.1#1#2|pc:act.9.1"),
    "link to the far half of a cut verse": lambda r: r["parallel_links"][2].update(
        to_pericope="pc:act.9.3b", link_key="pr:hd:eph.6.1#1#1|pc:act.9.3b"),
}


@pytest.mark.parametrize("case", sorted(MUTATIONS))
def test_mutations_turn_g_kg0_red(case):
    rows = _mutated(MUTATIONS[case])
    for name in rows["names"]:
        from ragcommon import ids
        name["name_id"] = ids.name_id(name["norm_key"])
    result = _gate(rows)
    assert not result.passed, case


@pytest.mark.parametrize("report, expected", [
    (_report(registries={**VERSIONS, "divine_refs": "divine_refs@dddddddddddd"}), None),
    (None, _expected(names=6)),
    (None, _expected(inputs={"text": "text@333333333333", "struct": DEPENDS["struct"]})),
    (None, {**_expected(), "extra_spans": {**_expected()["extra_spans"], "divine_rule": {
        "total": 7, "by_region": {"body": 7}, "by_surface": {"上帝": 4, "主": 1, "耶穌": 2}}}}),
])
def test_counts_and_bindings_are_checked(report, expected):
    assert not _gate(report=report, expected=expected).passed


def test_a_lone_cut_verse_may_link_both_halves():
    files = _files()
    ref = next(r for r in files["parallel_refs.jsonl"] if r["pr_id"] == "pr:hd:eph.6.1#1#1")
    ref["targets"] = [{"book_id": "act", "start_slot": "act.9.3", "end_slot": "act.9.3"}]
    links = files["parallel_links.jsonl"]
    links[2].update(target_end_slot="act.9.3", target_start_slot="act.9.3")
    links.append({**links[2], "to_pericope": "pc:act.9.3b",
                  "link_key": "pr:hd:eph.6.1#1#1|pc:act.9.3b"})
    schema, snap = check_schema(files, LAYERS)
    assert schema.passed, schema.details
    result = check_kg0(snap, _report(), _expected(parallel_links=4), DEPENDS)
    assert result.passed, result.details


def test_not_entity_spans_count_as_absent_names():
    report = _report(not_entity=["ns:act.10.1@11"])
    rows = _mutated(lambda r: r["names"].pop())
    result = _gate(rows, report, _expected(names=4))
    assert result.passed, result.details


def test_prov_passes_on_the_mini_rows():
    result = check_prov({f"{k}.jsonl": v for k, v in mini_kg.kg0_layer(VERSIONS).items()})
    assert result.passed, result.details
    assert result.name == "G-PROV"


@pytest.mark.parametrize("row, message", [
    ({"provenance_class": "made_up", "span_id": "x"}, "not in the closed enumeration"),
    ({"surface": "x"}, "no provenance_class"),
    ({"provenance_class": "pdf_rule", "span_id": "ns:x@1"}, "rule"),
    ({"provenance_class": "pdf_deterministic"}, "coordinate"),
    ({"provenance_class": "curated_human", "span_id": "ns:x@1"}, "decided_by"),
    ({"provenance_class": "external_legacy", "source": "s", "note": "n"}, "retire_by"),
    ({"provenance_class": "legacy_tuned", "anchors": [{"start_slot": "a"}]}, "slot_range"),
    ({"provenance_class": "external_legacy", "source": "s", "note": "n", "retire_by": "R2",
      "legacy_triggers": [{"provenance_class": "external_legacy", "source": "", "note": "n",
                           "retire_by": "R2"}]}, "source"),
])
def test_prov_requires_class_and_evidence(row, message):
    result = check_prov({"x.jsonl": [row]})
    assert not result.passed
    assert message in " ".join(result.details)


def test_prov_accepts_nested_evidence():
    event = {"provenance_class": "legacy_tuned",
             "anchors": [{"start_slot": "a.1.1", "end_slot": "a.1.2",
                          "provenance_class": "legacy_tuned"}]}
    assert check_prov({"events.jsonl": [event]}).passed


def test_prov_is_red_on_no_rows():
    assert not check_prov({}).passed
