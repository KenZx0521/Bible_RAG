"""validate_kg quality gate (plan §3.6) on the kg_snapshot fixture.

The fixture is a clean KG (every violation metric is 0). Each test copies it,
injects one defect, and asserts the metric moves by exactly that defect, so
every check has a negative (clean) and a positive (broken) example. Exit
codes and ratchet direction run through main() against a baseline built from
the shipped config/kg_quality_baseline.json with its values cleared, so the
shipped severities/directions are what is being tested.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import validate_kg as vk

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kg_snapshot"
REPO = Path(__file__).resolve().parents[2]
SHIPPED_BASELINE = REPO / "config" / "kg_quality_baseline.json"
SHIPPED_PROBES = REPO / "config" / "kg_probes.yaml"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def snap(tmp_path: Path) -> Path:
    dest = tmp_path / "snap"
    shutil.copytree(FIXTURE, dest)
    return dest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def append_row(path: Path, row: dict) -> None:
    write_rows(path, read_rows(path) + [row])


def edit_rows(path: Path, match, **changes) -> None:
    rows = read_rows(path)
    hit = 0
    for r in rows:
        if match(r):
            r.update(changes)
            hit += 1
    assert hit, f"no row matched in {path.name}"
    write_rows(path, rows)


def write_step0_sha(path: Path, sha: str) -> None:
    path.write_text(json.dumps({"version": 1, "files": {"embedding_queue.jsonl": {"sha256": sha}}}),
                    encoding="utf-8")


def fresh_baseline(tmp_path: Path, snap: Path) -> Path:
    """Shipped specs with every value cleared; H7's sha target (step0_sha.json
    next to the baseline, see cli) = the fixture's."""
    doc = json.loads(SHIPPED_BASELINE.read_text(encoding="utf-8"))
    for check in doc["checks"]:
        for metric in check["metrics"].values():
            metric["value"] = None
    write_step0_sha(tmp_path / "step0_sha.json", _sha(snap / "embedding_queue.jsonl"))
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def measure(snap: Path, baseline: Path | None = None) -> dict:
    ctx = vk.Context(
        baseline=vk.load_baseline(baseline or SHIPPED_BASELINE),
        probes=vk.load_probes(snap / "probes.yaml"),
        embedding_queue=snap / "embedding_queue.jsonl",
    )
    return vk.run_checks(vk.load_snapshot(snap), ctx)


def metric(results: dict, check_id: str, name: str):
    return results[check_id].metrics[name]


def argv(snap: Path, baseline: Path, *extra: str) -> list[str]:
    return ["--snapshot", str(snap), "--baseline", str(baseline), "--probes", str(snap / "probes.yaml"),
            "--embedding-queue", str(snap / "embedding_queue.jsonl"),
            "--step0-sha", str(baseline.with_name("step0_sha.json")), "--json", *extra]


def cli(snap: Path, baseline: Path, capsys, *extra: str) -> tuple[int, dict]:
    code = vk.main(argv(snap, baseline, *extra))
    return code, json.loads(capsys.readouterr().out)


def unsupported_edge(**over) -> dict:
    """馬可 VISITED 摩利亞, sourced from gen:22:0 where 馬可 is never mentioned.

    Deliberately not a kinship edge, so it moves H3 and nothing else (R6's
    functionality rate would change with a FATHER_OF)."""
    row = {"head_id": "person:make", "relation": "VISITED", "tail_id": "place:moliya",
           "source_pericope_id": "gen:22:0", "extraction_phase": 4, "notes": ""}
    row.update(over)
    return row


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
    doc = json.loads(SHIPPED_BASELINE.read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------------------
# exit codes, ratchet, warnings
# ---------------------------------------------------------------------------

def test_exit_codes_pass_hard_fail_and_regression(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    code, _ = cli(snap, baseline, capsys, "--ratchet")
    assert code == 0
    code, report = cli(snap, baseline, capsys)
    assert code == 0 and report["exit_code"] == 0

    append_row(snap / "relations.jsonl", unsupported_edge())
    code, report = cli(snap, baseline, capsys)
    assert code == 2
    assert report["checks"]["H3"]["status"] == "regressed"

    edit_rows(snap / "entities.jsonl", lambda r: r["entity_id"] == "person:make", labels=[])
    code, report = cli(snap, baseline, capsys)
    assert code == 1  # hard failure outranks the regression
    assert report["checks"]["H2"]["status"] == "fail"


def _stored(baseline: Path, check_id: str, name: str):
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    return next(c for c in doc["checks"] if c["id"] == check_id)["metrics"][name]["value"]


def test_ratchet_only_moves_toward_improvement(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    append_row(snap / "relations.jsonl", unsupported_edge())
    append_row(snap / "relations.jsonl", unsupported_edge(head_id="person:bide"))
    cli(snap, baseline, capsys, "--ratchet")
    assert _stored(baseline, "H3", "unsupported") == 2  # null baseline: first measurement sets it
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    h3 = next(c for c in doc["checks"] if c["id"] == "H3")
    assert h3["measured"]["origin"].startswith("snapshot:")  # provenance is stamped per check

    rows = read_rows(snap / "relations.jsonl")[:-1]
    write_rows(snap / "relations.jsonl", rows)
    code, _ = cli(snap, baseline, capsys, "--ratchet")
    assert code == 0 and _stored(baseline, "H3", "unsupported") == 1  # improved: moves down

    append_row(snap / "relations.jsonl", unsupported_edge(head_id="person:bide"))
    append_row(snap / "relations.jsonl", unsupported_edge(head_id="person:yage"))
    code, _ = cli(snap, baseline, capsys, "--ratchet")
    assert code == 2 and _stored(baseline, "H3", "unsupported") == 1  # regressed: never moves up


def test_ratchet_raises_up_direction_metric(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    cli(snap, baseline, capsys, "--ratchet")
    append_row(snap / "cross_references.jsonl", {"source_id": "exo:1:0", "target_id": "gen:22:0",
                                                 "source": "tsk", "votes": 3, "curated": False, "tsk": True})
    code, _ = cli(snap, baseline, capsys, "--ratchet")
    assert code == 0 and _stored(baseline, "R11", "tsk_votes_edges") == 2


def test_tolerance_absorbs_small_regressions(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    cli(snap, baseline, capsys, "--ratchet")
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    next(c for c in doc["checks"] if c["id"] == "H3")["metrics"]["unsupported"]["tolerance"] = 1
    baseline.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    append_row(snap / "relations.jsonl", unsupported_edge())
    code, _ = cli(snap, baseline, capsys)
    assert code == 0


def test_equal_direction_needs_explicit_accept(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    cli(snap, baseline, capsys, "--ratchet")
    # an extra Event anchor changes only H10 (plus R7, which has no direction)
    append_row(snap / "mentions.jsonl", {"source_label": "Pericope", "source_id": "gen:11:2",
                                         "entity_id": "event:xianyisa", "text_span": "獻以撒"})
    code, report = cli(snap, baseline, capsys, "--ratchet")
    assert code == 2 and report["checks"]["H10"]["status"] == "regressed"
    code, _ = cli(snap, baseline, capsys, "--accept", "H10")
    assert code == 0
    code, _ = cli(snap, baseline, capsys)
    assert code == 0


def test_w_histogram_drift_warns_without_failing(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    cli(snap, baseline, capsys, "--ratchet")
    append_row(snap / "entities.jsonl", {"entity_id": "person:xin", "labels": ["Person"],
                                         "canonical_name": "新人", "aliases": [], "description": ""})
    code, report = cli(snap, baseline, capsys)
    assert code == 0
    assert report["checks"]["W"]["status"] == "warn"
    assert any("Person" in w for w in report["checks"]["W"]["warnings"])


def test_probe_swap_with_unchanged_count_is_a_regression(snap, tmp_path, capsys):
    """A must-hold probe breaking while a known failure heals keeps the count:
    the per-id baseline still flags it (edges lost in a rebuild, review E-1)."""
    baseline = fresh_baseline(tmp_path, snap)
    lot = {"head_id": "person:luode", "relation": "FATHER_OF", "tail_id": "person:tala",
           "source_pericope_id": "gen:11:2", "extraction_phase": 2}
    append_row(snap / "relations.jsonl", lot)
    cli(snap, baseline, capsys, "--ratchet")
    assert _stored(baseline, "PROBES", "failing") == ["kin-lot-not-father-of-terah"]
    write_rows(snap / "relations.jsonl", [r for r in read_rows(snap / "relations.jsonl")
                                          if r != lot and (r["head_id"], r["tail_id"]) != ("person:tala", "person:yabolahan")])
    code, report = cli(snap, baseline, capsys)
    assert code == 2 and report["checks"]["PROBES"]["metrics"]["failures"]["status"] == "ok"  # 1 vs 1
    pairs = (("PROBES", "failing", "failures"), ("R6", "failing_probes", "probe_failures"))
    for check_id, name, _ in pairs:
        m = report["checks"][check_id]["metrics"][name]
        assert m["status"] == "regressed" and m["new"] == ["kin-terah-father-of-abraham"], check_id
    code, report = cli(snap, baseline, capsys, "--ratchet")
    for check_id, name, count in pairs:
        assert _stored(baseline, check_id, name) == []  # the healed probe is locked in, the new one is not
        assert _stored(baseline, check_id, count) == 0  # count = len(ids): never failures=1 with failing=[]
        assert code == 2 and report["checks"][check_id]["metrics"][count]["status"] == "regressed"


def test_baseline_count_must_equal_its_id_set(tmp_path):
    doc = json.loads(SHIPPED_BASELINE.read_text(encoding="utf-8"))
    next(c for c in doc["checks"] if c["id"] == "PROBES")["metrics"]["failures"]["value"] += 1
    (tmp_path / "baseline.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="PROBES.failures"):
        vk.load_baseline(tmp_path / "baseline.json")


def test_record_check_error_fails_the_gate(snap, tmp_path, capsys, monkeypatch):
    baseline = fresh_baseline(tmp_path, snap)
    cli(snap, baseline, capsys, "--ratchet")

    def unreadable_store(kg, ctx):
        raise RuntimeError("database bible_rag_staging does not exist")
    monkeypatch.setitem(vk.CHECKS, "H5", unreadable_store)
    code, report = cli(snap, baseline, capsys)
    assert code == 1 and report["checks"]["H5"]["status"] == "error"


# H5's live branch (staging without a Qdrant collection is unmeasured, never n/a)
# runs through fake PG/Qdrant connections in test_check_identity.py.


def test_unmeasurable_hard_metric_fails(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    del manifest["embedding_queue_sha256"]
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (snap / "embedding_queue.jsonl").unlink()
    code, report = cli(snap, baseline, capsys, "--only", "H7,H2")
    assert code == 1 and report["checks"]["H7"]["metrics"]["embedding_queue_sha256"]["status"] == "unmeasured"


def test_declared_not_applicable_is_reported_and_passes(snap, tmp_path, capsys):
    code, report = cli(snap, fresh_baseline(tmp_path, snap), capsys, "--only", "D1,H5")
    assert code == 0
    assert report["checks"]["D1"]["metrics"]["drift"]["status"] == "n/a"
    assert report["checks"]["D1"]["metrics"]["drift"]["reason"]
    assert {m["status"] for m in report["checks"]["H5"]["metrics"].values()} == {"n/a"}


def test_h7_sha_target_comes_from_step0_sha_json(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    assert cli(snap, baseline, capsys, "--ratchet")[0] == 0
    assert _stored(baseline, "H7", "embedding_queue_sha256") is None  # never copied into the baseline
    write_step0_sha(tmp_path / "step0_sha.json", "0" * 64)  # check_step0 --record moved the sha
    code, report = cli(snap, baseline, capsys)
    assert code == 1 and report["checks"]["H7"]["metrics"]["embedding_queue_sha256"]["status"] == "fail"
    (tmp_path / "step0_sha.json").unlink()
    assert cli(snap, baseline, capsys)[0] == 1  # no target is not a pass


def test_snapshot_missing_a_file_is_an_error(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    (snap / "books.jsonl").unlink()
    assert vk.main(argv(snap, baseline)) == 1
    assert "books.jsonl" in capsys.readouterr().err


def test_allow_partial_skips_dependent_checks_and_refuses_ratchet(snap, tmp_path, capsys):
    baseline = fresh_baseline(tmp_path, snap)
    (snap / "books.jsonl").unlink()
    code, report = cli(snap, baseline, capsys, "--allow-partial")
    assert code == 0 and report["partial"] == ["books.jsonl"]
    assert report["checks"]["R1"]["metrics"]["book_region_mentions"]["status"] == "n/a"
    before = baseline.read_text(encoding="utf-8")
    assert vk.main(argv(snap, baseline, "--allow-partial", "--ratchet")) == 1
    assert "partial" in capsys.readouterr().err
    assert baseline.read_text(encoding="utf-8") == before


def test_live_prod_refuses_a_shell_still_pointing_at_staging(monkeypatch, capsys):
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7688")  # refused before any connection
    assert vk.main(["--live", "--target", "prod", "--only", "H2"]) == 1
    assert "NEO4J_URI" in capsys.readouterr().err


def test_snapshot_dump_round_trip_preserves_every_metric(snap, tmp_path):
    kg = vk.load_snapshot(snap)
    out = tmp_path / "dumped"
    vk.write_snapshot(kg, out)
    shutil.copy(snap / "probes.yaml", out / "probes.yaml")
    shutil.copy(snap / "embedding_queue.jsonl", out / "embedding_queue.jsonl")
    a, b = measure(snap), measure(out)
    for check_id in a:
        assert a[check_id].metrics == b[check_id].metrics, check_id


@pytest.mark.parametrize("uri,message", [("bolt://localhost:7687", "prod endpoint"),
                                         ("bolt://localhost:1", "cannot read")])
def test_unusable_live_target_exits_1_with_a_message(monkeypatch, capsys, uri, message):
    # a gate that could not read its target must never report a pass
    for key in ("POSTGRES_DB", "QDRANT_ENTITY_COLLECTION"):  # other test modules load .env into os.environ
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NEO4J_URI", uri)
    code = vk.main(["--live", "--target", "staging", "--only", "H2"])
    assert code == 1
    assert message in capsys.readouterr().err


# ---------------------------------------------------------------------------
# shipped config files
# ---------------------------------------------------------------------------

def test_shipped_baseline_covers_every_check_with_batch0_severities():
    doc = vk.load_baseline(SHIPPED_BASELINE)
    ids = {c["id"] for c in doc["checks"]}
    assert ids == set(vk.CHECKS)
    severity = {c["id"]: c["severity"] for c in doc["checks"]}
    assert {i for i, s in severity.items() if s == "hard"} == {"H1", "H2", "H7", "D1"}
    assert severity["W"] == "warn"
    for check in doc["checks"]:
        assert check.get("query"), check["id"]
        for name, m in check["metrics"].items():
            assert {"value", "direction", "tolerance"} <= set(m), (check["id"], name)


def test_shipped_baseline_keeps_probe_ids_and_no_step0_sha_copy():
    doc = vk.load_baseline(SHIPPED_BASELINE)
    by_id = {c["id"]: c for c in doc["checks"]}
    sha = by_id["H7"]["metrics"]["embedding_queue_sha256"]
    assert sha["target_from"] and sha["value"] is None and "target" not in sha
    probes = {f["id"] for f in vk.load_probes(SHIPPED_PROBES)["facts"]}
    for check_id, name, count in (("PROBES", "failing", "failures"), ("R6", "failing_probes", "probe_failures")):
        failing = by_id[check_id]["metrics"][name]
        assert failing["direction"] == "subset" and set(failing["value"]) <= probes
        assert by_id[check_id]["metrics"][count]["count_of"] == name
        assert len(failing["value"]) == by_id[check_id]["metrics"][count]["value"]
    r3 = by_id["R3"]["metrics"]
    assert r3["all_forms_entities"]["value"] is None and r3["all_forms_person"]["value"] is None


def test_shipped_probes_cover_the_required_kinds():
    probes = vk.load_probes(SHIPPED_PROBES)
    facts = probes["facts"]
    assert len(facts) >= 15
    assert len({f["id"] for f in facts}) == len(facts)
    kinds = {f["kind"] for f in facts}
    assert {"mention", "relation", "xref", "event_anchor"} <= kinds
    assert any(f["kind"] == "relation" and f.get("check") == "R6" for f in facts)


# ---------------------------------------------------------------------------
# live (read-only; skipped when Neo4j is not reachable)
# ---------------------------------------------------------------------------

def _neo4j_or_skip():
    try:
        target = vk.resolve_target("prod")
        driver = vk.open_neo4j(target)
        driver.verify_connectivity()
        return target, driver
    except Exception as e:  # noqa: BLE001  (any connection problem means "service not here")
        pytest.skip(f"Neo4j not reachable: {e}")


def test_live_projection_round_trips_through_a_snapshot(tmp_path):
    target, driver = _neo4j_or_skip()
    try:
        kg = vk.load_live(driver)
    finally:
        driver.close()
    assert kg.entities and kg.mentions and kg.xrefs
    ctx = vk.Context(baseline=vk.load_baseline(SHIPPED_BASELINE), probes=vk.load_probes(SHIPPED_PROBES))
    skip = {"D1", "H5"}  # external processes / stores; covered elsewhere
    live = vk.run_checks(kg, ctx, only=set(vk.CHECKS) - skip)
    vk.write_snapshot(kg, tmp_path / "live")
    offline = vk.run_checks(vk.load_snapshot(tmp_path / "live"), ctx, only=set(vk.CHECKS) - skip)
    for check_id, result in live.items():
        for name, value in result.metrics.items():
            if value is not None and offline[check_id].metrics[name] is not None:
                assert offline[check_id].metrics[name] == value, (check_id, name)
    assert live["H2"].metrics["bad_type_labels"] == 0
