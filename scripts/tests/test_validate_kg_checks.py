"""validate_kg quality gate (plan §3.6): each check on the kg_snapshot fixture.

The fixture is a clean KG (every violation metric is 0). Each test copies it,
injects one defect, and asserts the metric moves by exactly that defect, so
every check has a negative (clean) and a positive (broken) example.

Split from test_validate_kg.py, together with test_validate_kg_gate.py (exit
codes, ratchet, CLI, live) and test_validate_kg_shipped.py (the shipped config
files); shared pieces are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

import validate_kg as vk
from kg_validate import model
from _validate_kg_helpers import (
    SHIPPED_BASELINE,
    SHIPPED_PROBES,
    _sha,
    _stored,
    append_row,
    argv,
    cli,
    edit_rows,
    fresh_baseline,
    measure,
    metric,
    read_rows,
    unsupported_edge,
    write_rows,
)
# snap is a pytest fixture: importing it is what makes it available here.
from _validate_kg_helpers import snap  # noqa: F401


# ---------------------------------------------------------------------------
# the clean fixture
# ---------------------------------------------------------------------------

VIOLATION_METRICS = [
    ("H1", "duplicate_ids"), ("H1", "missing_constraint"),
    ("H2", "bad_type_labels"),
    ("H3", "unsupported"), ("H4", "whitespace_names"), ("H6", "missing_region_or_pos"),
    ("H7", "prefix_mismatch"), ("H8", "no_provenance"),
    ("H9", "domain_range_violations"), ("H9", "unknown_relation_types"),
    ("R1", "book_region_mentions"), ("R2", "contaminated"), ("R3", "foreign_surface_entities"),
    ("R3", "all_forms_entities"),
    ("R4", "misaligned"), ("R5", "cross_type_names"),
    ("R6", "probe_failures"), ("R6", "contradictions"), ("R6", "female_head"),
    ("R6", "functional_violation_rate"),
    ("R8", "junk_event"), ("R8", "junk_theme"), ("R8", "junk_object"),
    ("R9", "duplicate_positions"), ("R9", "span_mismatch"),
    ("R10", "conflicting_aliases"), ("PROBES", "failures"),
]


def test_clean_fixture_has_no_violations(snap):
    res = measure(snap)
    for check_id, name in VIOLATION_METRICS:
        assert metric(res, check_id, name) == 0, (check_id, name, res[check_id].detail)
    assert metric(res, "R11", "tsk_votes_edges") == 1
    assert metric(res, "H10", "event_mentions") == 2
    assert metric(res, "R7", "single_pericope_events") == 2


def test_rows_collapse_to_edges_with_first_row_winning(snap):
    kg = vk.load_snapshot(snap)
    tala = [m for m in kg.mentions if (m["source_id"], m["entity_id"]) == ("gen:11:2", "person:tala")]
    assert len(tala) == 1 and tala[0]["start_pos"] == 24  # the 2nd row (pos 34) loses
    assert len(kg.mention_rows) == len(kg.mentions) + 1


def test_legacy_mention_rows_map_verse_to_parent_pericope(snap):
    rows = read_rows(snap / "mentions.jsonl")
    legacy = {"entity_id": "person:yisa", "source_id": "gen:22:0:v:2", "source_type": "verse",
              "text_span": "以撒", "start_pos": None, "end_pos": None}
    write_rows(snap / "mentions.jsonl", rows + [legacy])
    kg = vk.load_snapshot(snap)
    last = kg.mention_rows[-1]
    assert (last["source_label"], last["source_id"], last["text_id"]) == ("Pericope", "gen:22:0", "gen:22:0:v:2")


# ---------------------------------------------------------------------------
# hard checks
# ---------------------------------------------------------------------------

def test_h1_duplicate_entity_ids(snap):
    append_row(snap / "entities.jsonl", {"entity_id": "person:make", "labels": ["Person"],
                                         "canonical_name": "馬可", "aliases": [], "description": ""})
    assert metric(measure(snap), "H1", "duplicate_ids") == 1


def test_h1_missing_global_constraint(snap):
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    manifest["constraints"] = [{"label": "Person", "property": "entity_id", "type": "UNIQUENESS"}]
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert metric(measure(snap), "H1", "missing_constraint") == 1


def test_h1_constraint_not_applicable_when_snapshot_declares_none(snap):
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    del manifest["constraints"]
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert metric(measure(snap), "H1", "missing_constraint") is None


@pytest.mark.parametrize("labels", [["Person", "Place"], []])
def test_h2_entity_needs_exactly_one_type_label(snap, labels):
    edit_rows(snap / "entities.jsonl", lambda r: r["entity_id"] == "person:make", labels=labels)
    assert metric(measure(snap), "H2", "bad_type_labels") == 1


def test_h7_prefix_mismatch_and_allowlist(snap, tmp_path):
    edit_rows(snap / "entities.jsonl", lambda r: r["entity_id"] == "group:yiselie", labels=["Person"])
    assert metric(measure(snap), "H7", "prefix_mismatch") == 1
    doc = vk.load_baseline(SHIPPED_BASELINE)
    h7 = next(c for c in doc["checks"] if c["id"] == "H7")
    h7["params"]["id_prefix_allowlist"] = {"group:yiselie": "Person"}
    path = tmp_path / "allow.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert metric(measure(snap, path), "H7", "prefix_mismatch") == 0


def test_h7_embedding_queue_sha_is_a_hard_gate(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    code, _ = cli(snap, baseline, capsys)
    assert code == 0
    with open(snap / "embedding_queue.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "x", "type": "verse", "text": "改了"}, ensure_ascii=False) + "\n")
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    manifest["embedding_queue_sha256"] = _sha(snap / "embedding_queue.jsonl")
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    code, report = cli(snap, baseline, capsys)
    assert code == 1
    assert report["checks"]["H7"]["status"] == "fail"


def test_d1_runs_export_event_registry_check_against_the_target(monkeypatch):
    seen = {}

    def fake_run(cmd, env):
        seen["cmd"], seen["uri"] = cmd, env["NEO4J_URI"]
        return 1, "DRIFT: backend/data/event_registry.json differs"

    monkeypatch.setattr(vk, "_run_registry_check", fake_run)
    kg = vk.KG(mode="live")
    ctx = vk.Context(baseline=vk.load_baseline(SHIPPED_BASELINE), probes=vk.load_probes(SHIPPED_PROBES),
                     target=vk.resolve_target("staging", environ={}, dotenv={}))
    res = vk.run_checks(kg, ctx, only={"D1"})
    assert res["D1"].metrics["drift"] == 1
    assert seen["uri"] == "bolt://localhost:7688"
    assert "--check" in seen["cmd"]


# ---------------------------------------------------------------------------
# record checks
# ---------------------------------------------------------------------------

def test_h3_unsupported_derived_edge(snap):
    append_row(snap / "relations.jsonl", unsupported_edge())
    assert metric(measure(snap), "H3", "unsupported") == 1


@pytest.mark.parametrize("over", [
    {"extraction_phase": 3},                                   # prior
    {"curated": True},                                         # curated
    {"extraction_phase": 5, "source_pericope_id": "", "notes": "derived_from=FATHER_OF"},  # inverse of a prior
])
def test_h3_exemptions(snap, over):
    append_row(snap / "relations.jsonl", unsupported_edge(**over))
    assert metric(measure(snap), "H3", "unsupported") == 0


def test_h3_edge_without_provenance_counts(snap):
    append_row(snap / "relations.jsonl", unsupported_edge(source_pericope_id=""))
    assert metric(measure(snap), "H3", "unsupported") == 1


def test_h4_whitespace_names(snap):
    edit_rows(snap / "entities.jsonl", lambda r: r["entity_id"] == "person:luode", canonical_name="羅得 ")
    assert metric(measure(snap), "H4", "whitespace_names") == 1


def test_h6_ppg_mention_without_region(snap):
    rows = read_rows(snap / "mentions.jsonl")
    rows[0].pop("source_region")
    write_rows(snap / "mentions.jsonl", rows)
    assert metric(measure(snap), "H6", "missing_region_or_pos") == 1


def test_h8_xref_without_provenance_flag(snap):
    append_row(snap / "cross_references.jsonl", {"source_id": "exo:1:0", "target_id": "gen:22:0",
                                                 "source": "markdown", "votes": None})
    assert metric(measure(snap), "H8", "no_provenance") == 1


def test_h9_domain_range_and_unknown_type(snap):
    append_row(snap / "relations.jsonl", {"head_id": "person:yage", "relation": "FATHER_OF",
                                          "tail_id": "place:aiji", "source_pericope_id": "exo:1:0",
                                          "extraction_phase": 4})
    append_row(snap / "relations.jsonl", {"head_id": "person:yage", "relation": "LOVES",
                                          "tail_id": "place:aiji", "source_pericope_id": "exo:1:0",
                                          "extraction_phase": 4})
    res = measure(snap)
    assert metric(res, "H9", "domain_range_violations") == 1
    assert metric(res, "H9", "unknown_relation_types") == 1


def test_h10_event_mention_set_is_fingerprinted(snap):
    before = metric(measure(snap), "H10", "fingerprint")
    edit_rows(snap / "mentions.jsonl", lambda r: r["entity_id"] == "event:xianyisa", source_id="gen:11:2")
    after = measure(snap)
    assert metric(after, "H10", "event_mentions") == 2
    assert metric(after, "H10", "fingerprint") != before


def test_r1_first_position_inside_book_name(snap):
    # mrk:1:0 text starts with 馬可福音; position 0 is the book name, not a mention
    append_row(snap / "mentions.jsonl", {"source_label": "Pericope", "source_id": "mrk:1:0",
                                         "entity_id": "person:make", "text_span": "馬可",
                                         "start_pos": 0, "end_pos": 2, "text_id": "mrk:1:0",
                                         "source_region": "book"})
    res = measure(snap)
    assert metric(res, "R1", "book_region_mentions") == 1
    assert metric(res, "PROBES", "failures") == 1  # book-region-mark probe trips too


def test_r1_book_name_boundary_is_not_book_region(snap):
    # 使徒行傳 is 4 chars: a first position of exactly 4 lies past the book name
    append_row(snap / "mentions.jsonl", {"source_label": "Chunk", "source_id": "act:12:1:0",
                                         "entity_id": "place:aiji", "text_span": " 第",
                                         "start_pos": 4, "end_pos": 6, "text_id": "act:12:1:0",
                                         "source_region": "title"})
    assert metric(measure(snap), "R1", "book_region_mentions") == 0


def test_r2_substring_contamination(snap):
    text = read_rows(snap / "embedding_queue.jsonl")
    act8 = next(r["text"] for r in text if r["id"] == "act:8:0")
    pos = act8.index("撒馬利亞城") + 1
    append_row(snap / "mentions.jsonl", {"source_label": "Pericope", "source_id": "act:8:0",
                                         "entity_id": "person:maliya", "text_span": "馬利亞",
                                         "start_pos": pos, "end_pos": pos + 3, "text_id": "act:8:0",
                                         "source_region": "body"})
    res = measure(snap)
    assert metric(res, "R2", "contaminated") == 1
    assert metric(res, "PROBES", "failures") == 1  # mention-act8-not-mary


def rename_second_tala_row(snap: Path) -> None:
    """他拉's 2nd row loses the edge collapse, so only an all-forms reading sees this form."""
    rows = read_rows(snap / "mentions.jsonl")
    next(r for r in rows if r["entity_id"] == "person:tala" and r["start_pos"] == 34)["text_span"] = "他辣"
    write_rows(snap / "mentions.jsonl", rows)


@pytest.mark.parametrize("edge_span_foreign", [True, False])
def test_r3_edge_span_and_all_forms_are_separate_metrics(snap, edge_span_foreign):
    # the edge span is what live Neo4j keeps; every occurrence row is the plan's definition
    if edge_span_foreign:  # 馬利亞's only row
        edit_rows(snap / "mentions.jsonl", lambda r: r["entity_id"] == "person:maliya", text_span="瑪利亞")
    else:
        rename_second_tala_row(snap)
    res = measure(snap)
    edge = int(edge_span_foreign)
    assert (metric(res, "R3", "foreign_surface_entities"), metric(res, "R3", "person"),
            metric(res, "R3", "all_forms_entities"), metric(res, "R3", "all_forms_person")) == (edge, edge, 1, 1)


def live_shaped(snap: Path) -> vk.KG:
    """The snapshot's graph as load_live projects it: one row per edge, no text_id."""
    kg = vk.load_snapshot(snap)
    return vk.KG(mode="live", entity_rows=kg.entity_rows, mentions=[{**m, "text_id": None} for m in kg.mentions],
                 relations=kg.relations, xrefs=kg.xrefs, pericopes=kg.pericopes, chunk_parent=kg.chunk_parent,
                 books=kg.books, manifest={**kg.manifest, "origin": "live:test"}, origin="live:test")


@pytest.mark.parametrize("extra,occurrences", [({"mentions_granularity": "edge"}, False),
                                               ({"origin": "live:prod"}, False),  # a dump older than the marker
                                               ({"origin": "live:x", "mentions_granularity": "occurrence"}, True)])
def test_snapshot_granularity_marker_then_live_origin(snap, extra, occurrences):
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    (snap / "manifest.json").write_text(json.dumps({**manifest, **extra}), encoding="utf-8")
    assert (vk.load_snapshot(snap).mention_rows is not None) is occurrences


def test_live_and_snapshot_of_one_graph_pass_one_baseline(snap, tmp_path, capsys, monkeypatch):
    """R3/R9 parity (review R3, R9): a full snapshot must not regress against a
    live-ratcheted baseline, and a --dump-snapshot of live scores like live."""
    rename_second_tala_row(snap)
    baseline, dump = fresh_baseline(tmp_path, snap), tmp_path / "dump"
    monkeypatch.setattr(vk, "resolve_target", lambda name: None)
    monkeypatch.setattr(vk, "_read_live", lambda target, name: live_shaped(snap))
    live = ["--live", *argv(snap, baseline, "--only", "R3,R9")[2:]]
    assert vk.main([*live, "--ratchet", "--dump-snapshot", str(dump)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [m["status"] for m in report["checks"]["R3"]["metrics"].values()] == ["ok", "ok", "n/a", "n/a"]
    assert _stored(baseline, "R3", "all_forms_entities") is None  # live never fills the snapshot reading
    shutil.copy(snap / "probes.yaml", dump / "probes.yaml")
    code, report = cli(dump, baseline, capsys, "--only", "R3,R9")
    assert code == 0  # the dump has no occurrence rows: n/a exactly where live is
    assert {m["status"] for m in report["checks"]["R9"]["metrics"].values()} == {"n/a"}
    assert report["checks"]["R3"]["metrics"]["all_forms_entities"]["status"] == "n/a"
    assert cli(snap, baseline, capsys, "--only", "R3,R9", "--ratchet")[0] == 0  # full snapshot: no false regression
    assert _stored(baseline, "R3", "all_forms_entities") == 1 and _stored(baseline, "R3", "foreign_surface_entities") == 0
    assert vk.main(live) == 0  # and live still passes once the snapshot reading is filled


# What 6.05 stamps on an id-order llm edge. H11 counts it as unflagged unless
# direction_verified reads False, so a mode that drops the field fails H11.
PROVENANCE = {"direction_verified": False, "sources": ["llm"]}


def _neo4j_columns(cypher: str, row: dict) -> dict:
    """The record Neo4j returns for `row`: only the columns the Cypher selects,
    an absent property as null. SHOW ... YIELD (no AS) returns the row as is."""
    columns = re.findall(r"\bAS (\w+)", cypher)
    return {c: row.get(c) for c in columns} if columns else row


def test_load_live_reads_direction_verified_and_sources(snap, monkeypatch):
    """load_live through the real _LIVE_QUERIES: live_shaped() reuses the
    snapshot's rows and never runs them, so a relations Cypher missing a column
    would only surface on staging (the flagged edges read as None, H11 fails)."""
    stored = {
        "entities": [{"entity_id": "place:moliya", "labels": ["Entity", "Place"], "canonical_name": "摩利亞"},
                     {"entity_id": "place:jianan", "labels": ["Entity", "Place"], "canonical_name": "迦南"}],
        "relations": [{"head_id": "place:moliya", "relation": "LOCATED_IN", "tail_id": "place:jianan",
                       "source_pericope_id": "gen:22:0", "extraction_phase": 4, "source": "llm", **PROVENANCE},
                      {"head_id": "place:jianan", "relation": "NEAR", "tail_id": "place:moliya",
                       "source_pericope_id": "gen:22:0", "extraction_phase": 4}],  # legacy: neither property
    }
    names = {cypher: name for name, cypher in model._LIVE_QUERIES.items()}
    ran: dict[str, str] = {}

    def read_query(driver, cypher, **params):
        ran[names[cypher]] = cypher
        return [_neo4j_columns(cypher, row) for row in stored.get(names[cypher], [])]

    monkeypatch.setattr(model, "read_query", read_query)
    kg = vk.load_live(driver=None)
    assert set(ran) == set(model._LIVE_QUERIES)
    assert "r.direction_verified AS direction_verified" in ran["relations"]
    assert "r.sources AS sources" in ran["relations"]
    flagged, legacy = kg.relations
    assert {k: flagged[k] for k in PROVENANCE} == PROVENANCE
    assert (legacy["direction_verified"], legacy["sources"]) == (None, None)
    assert set(flagged) == set(vk.load_snapshot(snap).relations[0])  # live and snapshot rows: same keys


def test_snapshot_relation_rows_carry_direction_verified_and_sources(snap, tmp_path):
    edit_rows(snap / "relations.jsonl", lambda r: r["relation"] == "OCCURRED_IN", **PROVENANCE)
    kg = vk.load_snapshot(snap)
    flagged = next(r for r in kg.relations if r["type"] == "OCCURRED_IN")
    assert {k: flagged[k] for k in PROVENANCE} == PROVENANCE
    assert {(r["direction_verified"], r["sources"]) for r in kg.relations if r is not flagged} == {(None, None)}
    vk.write_snapshot(kg, tmp_path / "dump")  # and a dump keeps them
    assert vk.load_snapshot(tmp_path / "dump").relations == kg.relations


@pytest.mark.parametrize("field,value", [("source_id", "heb:1:0"), ("target_verses", "13")])
def test_r4_misaligned_supplementary_anchor(snap, field, value):
    edit_rows(snap / "cross_references.jsonl", lambda r: r["source"] == "supplementary", **{field: value})
    assert metric(measure(snap), "R4", "misaligned") == 1


def test_r5_cross_type_same_name(snap):
    append_row(snap / "entities.jsonl", {"entity_id": "place:make", "labels": ["Place"],
                                         "canonical_name": "馬可", "aliases": [], "description": ""})
    assert metric(measure(snap), "R5", "cross_type_names") == 1


def test_r6_contradiction(snap):
    append_row(snap / "relations.jsonl", {"head_id": "person:yisa", "relation": "FATHER_OF",
                                          "tail_id": "person:yabolahan", "source_pericope_id": "gen:22:0",
                                          "extraction_phase": 2})
    assert metric(measure(snap), "R6", "contradictions") == 2  # both directions are contradicted


def test_r6_son_of_contradicts_father_of(snap):
    append_row(snap / "relations.jsonl", {"head_id": "person:yabolahan", "relation": "SON_OF",
                                          "tail_id": "person:yisa", "source_pericope_id": "gen:22:0",
                                          "extraction_phase": 5, "notes": "derived_from=FATHER_OF"})
    assert metric(measure(snap), "R6", "contradictions") == 1


def test_r6_female_head_and_functionality(snap):
    append_row(snap / "relations.jsonl", {"head_id": "person:maliya", "relation": "FATHER_OF",
                                          "tail_id": "person:make", "source_pericope_id": "act:12:1",
                                          "extraction_phase": 4})
    append_row(snap / "relations.jsonl", {"head_id": "person:nahe", "relation": "FATHER_OF",
                                          "tail_id": "person:luode", "source_pericope_id": "gen:11:2",
                                          "extraction_phase": 4})
    res = measure(snap)
    assert metric(res, "R6", "female_head") == 1
    # children: yabolahan, halan, luode(2 fathers), yisa, make -> 1/5
    assert metric(res, "R6", "functional_violation_rate") == pytest.approx(0.2)


def test_r6_counts_failing_kinship_probes(snap):
    append_row(snap / "relations.jsonl", {"head_id": "person:luode", "relation": "FATHER_OF",
                                          "tail_id": "person:tala", "source_pericope_id": "gen:11:2",
                                          "extraction_phase": 2})
    res = measure(snap)
    assert metric(res, "R6", "probe_failures") == 1
    assert "kin-lot-not-father-of-terah" in res["R6"].detail["failing_probes"]


def test_r7_single_pericope_events(snap):
    append_row(snap / "mentions.jsonl", {"source_label": "Pericope", "source_id": "gen:11:2",
                                         "entity_id": "event:xianyisa", "text_span": "獻以撒"})
    assert metric(measure(snap), "R7", "single_pericope_events") == 1


def test_r8_junk_names_with_allowlist(snap):
    for eid, label, name in [("event:junk1", "Event", "（太26‧26－30；可14‧22－26；路"),  # xref remnant
                             ("event:zheshijiduma", "Event", "這是基督嗎？"),          # allowlisted title
                             ("event:fuhuo", "Event", "復活在我，生命在我"),          # comma inside a real title
                             ("theme:junk2", "Theme", "獻的禱告。"),                  # sentence fragment
                             ("object:junk3", "Object", "*王下18‧13－37"),            # xref remnant
                             ("object:junk4", "Object", " 驢"),                      # padded (strip-before-compare bug)
                             ("event:wawa", "Event", "－蛙災")]:                     # dash-led subtitle: not counted
        append_row(snap / "entities.jsonl", {"entity_id": eid, "labels": [label], "canonical_name": name,
                                             "aliases": [], "description": ""})
    res = measure(snap)
    assert (metric(res, "R8", "junk_event"), metric(res, "R8", "junk_theme"),
            metric(res, "R8", "junk_object")) == (1, 1, 2)


def test_r9_duplicate_positions_and_span_mismatch(snap):
    rows = read_rows(snap / "mentions.jsonl")
    dup = dict(rows[0])
    bad = dict(rows[2], start_pos=rows[2]["start_pos"] + 1, end_pos=rows[2]["end_pos"] + 1)
    write_rows(snap / "mentions.jsonl", rows[:2] + [bad] + rows[3:] + [dup])
    res = measure(snap)
    assert metric(res, "R9", "duplicate_positions") == 1
    assert metric(res, "R9", "span_mismatch") == 1


def test_r9_snapshot_without_text_ids_is_declared_not_applicable(snap, tmp_path, capsys):
    # same as live (no row to score): reported n/a with a reason, not unmeasured (exit 1)
    write_rows(snap / "mentions.jsonl", [{k: v for k, v in r.items() if k != "text_id"}
                                         for r in read_rows(snap / "mentions.jsonl")])
    code, report = cli(snap, fresh_baseline(tmp_path, snap), capsys, "--only", "R9")
    assert code == 0 and all(m["status"] == "n/a" and "text_id" in m["reason"]
                             for m in report["checks"]["R9"]["metrics"].values())


@pytest.mark.parametrize("owner,alias", [("person:bide", "馬可"), ("person:yisa", "亞伯蘭")])
def test_r10_conflicting_alias(snap, owner, alias):
    edit_rows(snap / "entities.jsonl", lambda r: r["entity_id"] == owner, aliases=[alias])
    assert metric(measure(snap), "R10", "conflicting_aliases") == 1


def test_r11_tsk_votes(snap):
    append_row(snap / "cross_references.jsonl", {"source_id": "exo:1:0", "target_id": "gen:22:0",
                                                 "source": "tsk", "votes": 3, "curated": False, "tsk": True})
    assert metric(measure(snap), "R11", "tsk_votes_edges") == 2


@pytest.mark.parametrize("change", ["add_absent", "drop_present"])
def test_probe_failures(snap, change):
    if change == "add_absent":
        append_row(snap / "cross_references.jsonl", {"source_id": "heb:1:0", "target_id": "psa:2:0",
                                                     "source": "markdown", "curated": True})
    else:
        rows = [r for r in read_rows(snap / "mentions.jsonl")
                if (r["source_id"], r["entity_id"]) != ("gen:22:0", "person:yisa")]
        write_rows(snap / "mentions.jsonl", rows)
    res = measure(snap)
    assert metric(res, "PROBES", "failures") == 1

