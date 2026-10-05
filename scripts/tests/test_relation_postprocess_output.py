"""Step 6.05 on the real output/ inputs (gitignored build products).

The counts are pinned to the W1 inputs: they hold only when output/ is the
batch-1 W1 snapshot, so the module-scoped run is skipped unless every input's
sha256 equals its pin (the run reads ~175k mention rows, so it happens once
per module). The hash-seed test only needs the inputs to exist.

None mode is the K8 staging-P1 control: its edge set after 10.2 is what the
batch-0 staging build (bolt://localhost:7688) holds per phase, rule 772 /
prior 64 / llm 5,278 / inverse 752 (read 2026-10-05; the 9,060 phase-5
cooccurrence edges come from 10.3, not from relations.jsonl).
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

from entity_extraction import entity_overrides, geo_rules
from kg_validate.checks_probes import evaluate_probes
from kg_validate.checks_r import check_r6
from kg_validate.model import KG
from kg_validate.registry import Context
from relation_extraction import relation_postprocess as pp
from relation_extraction.anchored_rules import GuardConfig
from relation_extraction.models import PHASE_OF_SOURCE

ROOT = Path(__file__).resolve().parents[2]
W1_PINS = {
    "relations": "fe7f0cfda391991a1d9768c3f4b4dce18df2e033b4bc68dbc353d8b188730f5c",
    "entities": "9f2d1f39251d9a3ce5834f52d129bda8e13cd2e1afdfa30d04962d23c7034142",
    "mentions": "ba7ed1884355e3f8d60952b4e89bff6c6dfb094818caee168dd5c387cd9e896c",
    "chunks": "46ca73105170489182c3bfb5c0ed6fbcef3083a21634197e0b9b62976a154f12",
    "pericopes": "2e46fea4817c538ae4b5b4c6535491277674dc140c8b81dbf2fec8235a038c2c",
}
# edge_set_sha256 of the none-mode rows left after 10.2 (6,866 lines). Computed
# independently on 2026-10-05 from both relations.jsonl minus the generic-event
# rows and the 7688 edges (source from phase 2/3/4/5); the two line sets were equal.
NONE_AFTER_10_2_SHA256 = "7fde48c7b815c1839d32adc64e005985e09c4e1d271caa66d0efa8ec010392f5"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inputs_present() -> bool:
    return all(path.exists() for path in pp.default_paths().values())


@pytest.fixture(scope="module")
def real_inputs():
    """(Inputs, Config) of the default paths; skipped unless output/ is the W1 snapshot."""
    paths = pp.default_paths()
    if not _inputs_present():
        pytest.skip("output/ JSONL artifacts are not present (gitignored build products)")
    drifted = [name for name, pin in W1_PINS.items() if _sha256(paths[name]) != pin]
    if drifted:
        pytest.skip(f"output/ is not the W1 snapshot: {drifted} differ from their pins")
    return pp.load_inputs(paths)


@pytest.fixture(scope="module")
def none_run(real_inputs):
    return pp.postprocess(*real_inputs, "none")


def test_none_mode_counts(none_run):
    rows, report = none_run
    assert report["flow"]["input"] == report["flow"]["output"] == len(rows) == 6958
    assert report["output"]["by_source"] == {"inverse": 752, "llm": 5370, "prior": 64, "rule": 772}

    after = report["expected_after_10_2"]
    assert len(after["generic_event_ids"]) == 16
    assert (after["edges_on_generic_events"], after["edges"]) == (92, 6866)
    by_phase = Counter()
    for key, n in after["by_ee_key"].items():
        by_phase[key.split(" ", 1)[1]] += n
    assert by_phase == {"phase=2 source=rule": 772, "phase=3 source=prior": 64,
                        "phase=4 source=llm": 5278, "phase=5 source=inverse": 752}
    assert after["edge_set_sha256"] == NONE_AFTER_10_2_SHA256


@pytest.fixture(scope="module")
def all_run(real_inputs):
    return pp.postprocess(*real_inputs, "all")


def _pairs(rows) -> set[frozenset]:
    return {frozenset((r["head_id"], r["tail_id"])) for r in rows}


def test_inverse_drops(real_inputs, all_run):
    rows, report = all_run
    assert report["flow"]["drops"]["inverse"] == {
        "FATHER_OF": 462, "SON_OF": 221, "ANCESTOR_OF": 27, "DESCENDANT_OF": 22, "TEACHER_OF": 13,
        "DISCIPLE_OF": 7}
    assert sum(report["flow"]["drops"]["inverse"].values()) == 752
    assert not any(r["source"] == "inverse" for r in rows)

    # entity_path walks edges undirected: the rule on its own leaves every pair connected
    inputs, cfg = real_inputs
    stamped = [pp.base_stamp(r, cfg) for r in inputs.relations]
    kept = pp.drop_inverse(stamped, inputs, cfg, pp.Flow())
    assert len(stamped) - len(kept) == 752
    assert _pairs(kept) == _pairs(stamped)


RULE_DROPS = {
    "SON_OF": 401, "FATHER_OF": 140, "RULED": 65, "MOTHER_OF": 29, "MEMBER_OF": 25, "DAUGHTER_OF": 23,
    "SPOUSE_OF": 22, "SIBLING_OF": 16, "RETURNED_FROM": 13, "BUILT": 9, "DESCENDANT_OF": 9, "ANCESTOR_OF": 7,
    "EXILED_TO": 6, "LOCATED_IN": 4, "SUCCEEDED_BY": 2, "BORN_IN": 1}
P1, P2, P3, P4 = "P1_child_of", "P2_is_child_of", "P3_begot", "P4_wife"
HITS = {P1: 565, P2: 113, P3: 10, P4: 13}
# flow.anchored per guard setting (ambiguous_name is report-only and not pinned). The key sets
# equal the W1 simulator's (docs/records/2026-10-04_kg_fix/batch1/w1_1A/sim_1a_w1.py: sim2_final.json,
# sim2_no_disagreement.json, and --guard off --disagree off without --homonym).
ANCHORED = {
    "full": {
        "pattern_hits": 701, "by_pattern": HITS, "guard_other_parent": 56, "guard_homonym": 4,
        "disagreement_children": 49, "disagreement_abstain": 176,
        "emitted_hits": 465, "emitted_by_pattern": {P1: 377, P2: 68, P3: 7, P4: 13}, "unique_keys": 328,
        "key_set_sha256": "57bf0c82e3cbced99ff07ad55413cacf907bd82d0aead72dcab302dae4723432"},
    "disagreement_off": {
        "pattern_hits": 701, "by_pattern": HITS, "guard_other_parent": 56, "guard_homonym": 4,
        "disagreement_children": 0, "disagreement_abstain": 0,
        "emitted_hits": 641, "emitted_by_pattern": {P1: 518, P2: 101, P3: 9, P4: 13}, "unique_keys": 469,
        "key_set_sha256": "fbe95cfb5b84ea276acdc801dad5120f341661f2385edcb00ca741bebf3e21c6"},
    "guards_off": {
        "pattern_hits": 701, "by_pattern": HITS, "guard_other_parent": 0, "guard_homonym": 0,
        "disagreement_children": 0, "disagreement_abstain": 0,
        "emitted_hits": 701, "emitted_by_pattern": HITS, "unique_keys": 512,
        "key_set_sha256": "6914aeb160abb085330b9bda4d8212198c59e8b71a84e941f448414bfc8e2459"},
}
ANCHORED_REASONS = ("other_parent", "homonym", "anchored_disagreement")


@pytest.fixture(scope="module")
def rows_before_anchored(real_inputs):
    """What rules_to_anchored sees in all mode: the base-stamped rows less the inverses."""
    inputs, cfg = real_inputs
    return pp.drop_inverse([pp.base_stamp(r, cfg) for r in inputs.relations], inputs, cfg, pp.Flow())


def _guard(guard: GuardConfig, variant: str) -> GuardConfig:
    if variant == "disagreement_off":
        return dataclasses.replace(guard, disagreement=False)
    if variant == "guards_off":
        return GuardConfig(other_parent=False, homonym_ids=frozenset(), disagreement=False)
    return guard


def _key(row) -> tuple[str, str, str]:
    return row["head_id"], row["relation"], row["tail_id"]


@pytest.mark.parametrize("variant", list(ANCHORED))
def test_rule_drops_and_anchored_counts(real_inputs, all_run, rows_before_anchored, variant):
    inputs, cfg = real_inputs
    anchored_cfg = dataclasses.replace(cfg.anchored, guard=_guard(cfg.anchored.guard, variant))
    flow = pp.Flow()
    out = pp.rules_to_anchored(rows_before_anchored, inputs, dataclasses.replace(cfg, anchored=anchored_cfg), flow)

    assert flow.drops == {"rule": RULE_DROPS}
    assert sum(RULE_DROPS.values()) == 772
    stats = {k: v for k, v in flow.anchored.items() if k != "ambiguous_name"}
    assert stats == {"enabled": True, "foreign_surface_skipped": 2366, **ANCHORED[variant]}
    anchored = [r for r in out if r["source"] == "anchored_rule"]
    assert len(anchored) == len({_key(r) for r in anchored}) == stats["unique_keys"]
    assert len(out) == len(rows_before_anchored) - 772 + len(anchored)
    assert len(flow.conflicts) == stats["guard_other_parent"] + stats["guard_homonym"] + stats["disagreement_abstain"]
    if variant != "full":
        return

    rows, report = all_run
    assert report["flow"]["drops"]["rule"] == RULE_DROPS
    assert report["flow"]["anchored"] == flow.anchored
    assert Counter(c["reason"] for c in report["conflicts"] if c["reason"] in ANCHORED_REASONS) == {
        "other_parent": 56, "homonym": 4, "anchored_disagreement": 176}
    by_key = {_key(r): r for r in anchored}
    # the rule rows behind kin-lot-not-father-of-terah and kin-leah-* are gone, with no anchored twin
    for key in (("person:luode", "FATHER_OF", "person:tala"), ("person:liya", "FATHER_OF", "person:lvbian"),
                ("person:liya", "FATHER_OF", "person:yisa")):
        assert key not in {_key(r) for r in out}
    # 1ch 29:26 (P1) and luk 3:32 (P2) both give 大衛 SON_OF 耶西; the smaller pericope id is primary
    david = by_key[("person:dawei", "SON_OF", "person:yexi")]
    assert (david["source_pericope_id"], david["verse"], david["notes"]) == ("1ch:29:2", 26, P1)
    assert (david["support_pericopes"], david["evidence_count"]) == (["1ch:29:2", "luk:3:2"], 2)


def test_event_event_drops(real_inputs, all_run, rows_before_anchored):
    rows, report = all_run
    assert report["flow"]["drops"]["llm_event_event"] == {"PRECEDED_BY": 24, "CAUSED": 14}
    assert report["rules"]["ran"][2] == "drop_llm_event_event"

    inputs, cfg = real_inputs
    types = {eid: entity_overrides.final_type(eid, e["type"], cfg.overrides) for eid, e in inputs.entities.items()}

    def llm_event_event(row) -> bool:
        return row["source"] == "llm" and types[row["head_id"]] == types[row["tail_id"]] == "Event"

    assert not any(llm_event_event(r) for r in rows)
    # every Event–Event row in relations.jsonl is an llm one (38); prod holds 26 of them,
    # because 10.2 DETACH DELETEd the generic events the other 12 hang on
    dropped = [r for r in rows_before_anchored if llm_event_event(r)]
    assert len(dropped) == sum(types[r["head_id"]] == types[r["tail_id"]] == "Event"
                               for r in inputs.relations) == 38
    generic = set(report["expected_after_10_2"]["generic_event_ids"])
    assert sum(r["head_id"] in generic or r["tail_id"] in generic for r in dropped) == 12


def test_domain_range_drops(real_inputs, all_run, rows_before_anchored):
    rows, report = all_run
    # G-2: 13 llm rows on 耶和華, a Group in entities.jsonl and a Person once the curated
    # override (D9) applies: a Person LEADER_OF or MEMBER_OF it, or it SETTLED_IN or
    # ORIGINATED_FROM a place
    assert report["flow"]["drops"]["domain_range"] == {
        "LEADER_OF": 7, "MEMBER_OF": 1, "ORIGINATED_FROM": 1, "SETTLED_IN": 4}
    assert "unknown_relation" not in report["flow"]["drops"]
    ran = report["rules"]["ran"]
    assert ran.index("drop_llm_event_event") < ran.index("domain_range") < ran.index("provenance_gate")

    inputs, cfg = real_inputs
    final = {eid: entity_overrides.final_type(eid, e["type"], cfg.overrides) for eid, e in inputs.entities.items()}
    extracted = {eid: e["type"] for eid, e in inputs.entities.items()}

    def illegal(row, types) -> bool:
        return not cfg.schema.get(row["relation"]).accepts_pair(types[row["head_id"]], types[row["tail_id"]])

    # H9 on the final types is 0
    assert [_key(r) for r in rows if illegal(r, final)] == []
    # relations.jsonl (less the inverses) holds 14 such rows, live H9: the 13 and the id-order
    # rule row 耶利米 MEMBER_OF 耶和華, which rules_to_anchored drops first. Every one is on
    # 耶和華 and legal on the extracted types: the override alone makes them violations
    violations = [r for r in rows_before_anchored if illegal(r, final)]
    assert Counter((r["source"], r["relation"]) for r in violations) == {
        ("llm", "LEADER_OF"): 7, ("llm", "MEMBER_OF"): 1, ("llm", "ORIGINATED_FROM"): 1,
        ("llm", "SETTLED_IN"): 4, ("rule", "MEMBER_OF"): 1}
    assert all("group:yehehua" in (r["head_id"], r["tail_id"]) for r in violations)
    assert not any(illegal(r, extracted) for r in rows_before_anchored)


def _support_after_10_2(inputs) -> set[tuple[str, str]]:
    """{(pericope, entity_id)} of the MENTIONS edges 10.2 leaves, computed apart from 6.05."""
    keep = geo_rules.compute_dan_keep_sources(pp.default_paths()["mentions"])
    support = set()
    for m in inputs.mentions:
        key = m["source_id"].split(":v:")[0]   # what action_dan compares against s.id
        if m["entity_id"] == "place:dan" and key not in keep:
            continue
        support.add((inputs.chunk_parent[key] if m["source_type"] == "chunk" else key, m["entity_id"]))
    return support


def test_gate_drops(real_inputs, all_run, rows_before_anchored):
    rows, report = all_run
    dan_near = ("place:dan", "NEAR", "place:yuedan")
    # the gate's one drop: 但 NEAR 約旦 from 「疏割和撒拉但中間」 (1ki 7:46), whose 但 MENTIONS
    # edge 10.2 deletes; prod and the batch-0 staging build both hold the edge unsupported
    assert report["flow"]["drops"]["provenance_gate"] == {"NEAR": 1}
    assert report["flow"]["drops_due_to_dan_filter"] == {"NEAR": 1}
    assert report["rules"]["ran"].index("provenance_gate") > report["rules"]["ran"].index("drop_llm_event_event")
    [row] = [r for r in rows_before_anchored if _key(r) == dan_near]
    assert (row["source"], row["source_pericope_id"]) == ("llm", "1ki:7:5")
    assert dan_near not in {_key(r) for r in rows}

    # every row left but the exempt ones has both endpoints mentioned in its pericope
    inputs, _ = real_inputs
    support = _support_after_10_2(inputs)
    assert [_key(r) for r in rows if r["source"] not in ("prior", "curated") and not (
        r["source_pericope_id"] and {(r["source_pericope_id"], r["head_id"]),
                                     (r["source_pericope_id"], r["tail_id"])} <= support)] == []
    # G-3: the 64 priors name no pericope and pass ungated; the gate's one drop is an llm
    # row, so every anchored row it saw is supported
    priors = [r for r in rows if r["source"] == "prior"]
    assert len(priors) == 64 and not any(r["source_pericope_id"] for r in priors)


def test_direction_flags(real_inputs, all_run, rows_before_anchored):
    rows, report = all_run
    _, cfg = real_inputs
    id_order = cfg.schema.id_order_relations()
    # REL-03: the llm rows of the id-order relations all have head < tail; 47 LOCATED_IN and
    # 1 SUCCEEDED_BY stay flagged. 加利利 LOCATED_IN 拿撒勒 (「加利利拿撒勒」, mat:21:0)
    # reverses the prior 拿撒勒 LOCATED_IN 加利利 (路 1:26) and goes
    assert report["flow"]["flagged"] == {"LOCATED_IN": 47, "SUCCEEDED_BY": 1}
    assert report["flow"]["drops"]["contradicts_prior"] == {"LOCATED_IN": 1}
    reversed_key = ("place:jialili", "LOCATED_IN", "place:nasalei")
    [row] = [r for r in rows_before_anchored if _key(r) == reversed_key]
    assert (row["source"], row["source_pericope_id"]) == ("llm", "mat:21:0")
    assert reversed_key not in {_key(r) for r in rows}
    ran = report["rules"]["ran"]
    assert ran.index("provenance_gate") < ran.index("flag_id_order")

    flagged = [r for r in rows if r.get("direction_verified") is False]
    verified = [r for r in rows if r.get("direction_verified") is True]
    assert len(flagged) == 48 and {r["source"] for r in flagged} == {"llm"}
    assert all(r["head_id"] < r["tail_id"] for r in flagged)
    # the 7 priors (4 SUCCEEDED_BY, 3 LOCATED_IN) are verified; no other row has the field,
    # and no id-order row is left without it (H11's unflagged_id_order_edges is 0)
    assert len(verified) == 7 and {r["source"] for r in verified} == {"prior"}
    assert Counter(r["relation"] for r in verified) == {"SUCCEEDED_BY": 4, "LOCATED_IN": 3}
    assert all(r["relation"] in id_order for r in flagged + verified)
    assert [_key(r) for r in rows if (r["relation"] in id_order) != ("direction_verified" in r)] == []


def _r6(rows, female: set[str]) -> tuple[int, int]:
    """(contradictions, female_head) as validate_kg R6 counts them over the FATHER_OF rows."""
    parent_of = {(r["head_id"], r["tail_id"]) for r in rows if r["relation"] in ("FATHER_OF", "MOTHER_OF")}
    parent_of |= {(r["tail_id"], r["head_id"]) for r in rows if r["relation"] in ("SON_OF", "DAUGHTER_OF")}
    fathers = [(r["head_id"], r["tail_id"]) for r in rows if r["relation"] == "FATHER_OF"]
    return sum((t, h) in parent_of for h, t in fathers), sum(h in female for h, _ in fathers)


def test_conflict_drops(real_inputs, all_run):
    rows, report = all_run
    drops, keys = report["flow"]["drops"], {_key(r): r["source"] for r in rows}
    # no parent/child pair reaches the rule in both directions: the draft's one case, the
    # anchored 比利家 SON_OF 米書蘭 against the llm 比利家 FATHER_OF 米書蘭 (neh:6:1), is
    # abstained earlier by the anchored disagreement guard (1A-C3c)
    assert "kin_direction_conflict" not in drops
    assert [c for c in report["conflicts"] if c["reason"] == "kin_direction_conflict"] == []
    assert ("person:bilijia", "SON_OF", "person:mishulan") not in keys
    assert keys[("person:bilijia", "FATHER_OF", "person:mishulan")] == "llm"
    ran = report["rules"]["ran"]
    assert ran.index("flag_id_order") < ran.index("resolve_kinship_direction") < ran.index("dedup_undirected")

    # an undirected pair keeps one row, the best-ranked in its own orientation: the prior
    # over the llm row that restates it reversed (3), the llm over the anchored P4 row of
    # the same key (密迦 SPOUSE_OF 拿鶴, gen:11:2 v29), and 亞伯拉罕 SPOUSE_OF 撒拉 (prior)
    # over both rows of the other orientation (llm and anchored)
    assert drops["undirected_duplicate"] == {"ALLY_OF": 1, "ENEMY_OF": 1, "SPOUSE_OF": 4}
    for key, source in ((("person:yuenadan", "ALLY_OF", "person:dawei"), "prior"),
                        (("person:saoluo", "ENEMY_OF", "person:dawei"), "prior"),
                        (("person:yage", "SPOUSE_OF", "person:liya"), "prior"),
                        (("person:mijia", "SPOUSE_OF", "person:nahe"), "llm"),
                        (("person:yabolahan", "SPOUSE_OF", "person:sala"), "prior")):
        assert keys[key] == source
    for key in (("person:dawei", "ALLY_OF", "person:yuenadan"), ("person:dawei", "ENEMY_OF", "person:saoluo"),
                ("person:liya", "SPOUSE_OF", "person:yage"), ("person:sala", "SPOUSE_OF", "person:yabolahan")):
        assert key not in keys
    _, cfg = real_inputs
    undirected = [r for r in rows if cfg.schema.get(r["relation"]).direction == "undirected"]
    assert len(undirected) == len({(frozenset((r["head_id"], r["tail_id"])), r["relation"]) for r in undirected})

    # R6: relations.jsonl holds 25 FATHER_OF rows reversed by a parent row and 42 with a
    # female head (rule and inverse rows); 6.05's output holds none of either
    inputs, _ = real_inputs
    female = set(yaml.safe_load((ROOT / "config" / "kg_probes.yaml").read_text(encoding="utf-8"))["female_persons"])
    assert _r6(inputs.relations, female) == (25, 42)
    assert _r6(rows, female) == (0, 0)


# The rows 6.05 hands 6.1 (1A-C4i on), as the W1 simulator predicted them (sim_1a_w1.py:
# sim2_final.json): the sha256 of edge_set_lines over all 5,696 rows, and over the 5,616 left after 10.2
FINAL_EDGE_SET_SHA256 = "80c0534862b3e8fcccb24d7b6e55e08f15ce29df46193ae3471f7293baa3c1de"
FINAL_AFTER_10_2_SHA256 = "661cfc6289e2966e71a0c83d974be99d256e04e0f90ac78ae28f8fb518c7bbc1"
KINSHIP = {"FATHER_OF": 50, "SON_OF": 335, "DAUGHTER_OF": 14, "MOTHER_OF": 15, "SPOUSE_OF": 30, "SIBLING_OF": 32,
           "ANCESTOR_OF": 15, "DESCENDANT_OF": 18}


def _after_10_2(rows, report) -> list[dict]:
    gone = set(report["expected_after_10_2"]["generic_event_ids"])
    return [r for r in rows if r["head_id"] not in gone and r["tail_id"] not in gone]


def _parents(rows, female: set[str]) -> tuple[int, int, int]:
    """(children, those with 2+ parents not on the female list, those with >2 parents) over all four encodings."""
    parents: dict[str, set[str]] = {}
    for r in rows:
        if r["relation"] in ("FATHER_OF", "MOTHER_OF"):
            parents.setdefault(r["tail_id"], set()).add(r["head_id"])
        elif r["relation"] in ("SON_OF", "DAUGHTER_OF"):
            parents.setdefault(r["head_id"], set()).add(r["tail_id"])
    return (len(parents), sum(len(p - female) >= 2 for p in parents.values()),
            sum(len(p) > 2 for p in parents.values()))


def test_final_edge_set(none_run, all_run):
    rows, report = all_run
    # one row per key: of the 7 keys the anchored rule shares with the llm (5) or a prior (2), the
    # better-ranked row is primary, so the anchored rows that 6.1 imports drop from 326 to 319
    assert len(rows) == len({_key(r) for r in rows}) == report["output"]["rows"] == 5696
    assert report["output"]["by_source"] == {"anchored_rule": 319, "llm": 5313, "prior": 64}
    assert report["flow"]["collapsed_keys"] == {"anchored_rule+llm": 5, "anchored_rule+prior": 2}
    assert pp.edge_set_sha256(rows) == FINAL_EDGE_SET_SHA256
    after = report["expected_after_10_2"]
    assert (len(after["generic_event_ids"]), after["edges_on_generic_events"], after["edges"]) == (16, 80, 5616)
    by_source = Counter()
    for key, n in after["by_ee_key"].items():
        by_source[key.rsplit("source=", 1)[1]] += n
    assert by_source == {"anchored_rule": 319, "llm": 5233, "prior": 64}
    assert after["edge_set_sha256"] == FINAL_AFTER_10_2_SHA256
    assert {rel: n for rel, n in after["by_type"].items() if rel in KINSHIP} == KINSHIP
    assert sum(KINSHIP.values()) == 509

    # batch 0's four SON_OF edges (prod and staging held different phases, REL-10): one row each
    by_key = {_key(r): r for r in rows}
    for key, primary in ((("person:yage", "SON_OF", "person:yisa"), ("llm", 4, "gen:28:1", None)),
                         (("person:bianyamin", "SON_OF", "person:yage"), ("llm", 4, "gen:35:1", None)),
                         (("person:bianyamin", "SON_OF", "person:lajie"), ("llm", 4, "gen:35:1", None)),
                         (("person:dawei", "SON_OF", "person:yexi"), ("anchored_rule", 6, "1ch:29:2", 26))):
        row = by_key[key]
        assert (row["source"], row["extraction_phase"], row["source_pericope_id"], row.get("verse")) == primary
        assert row["sources"] == [primary[0]]

    # R6 and the 8 shipped relation probes, scored by validate_kg on the edges left after 10.2
    kept = _after_10_2(rows, report)
    probes = yaml.safe_load((ROOT / "config" / "kg_probes.yaml").read_text(encoding="utf-8"))
    kg = KG(mode="snapshot", relations=[{"head": r["head_id"], "type": r["relation"], "tail": r["tail_id"]}
                                        for r in kept])
    ctx = Context(baseline={}, probes=probes)
    r6 = check_r6(kg, ctx)
    assert r6.metrics == {"probe_failures": 0, "failing_probes": [], "contradictions": 0, "female_head": 0,
                          "functional_violation_rate": 0.0638}
    assert (sum(r["relation"] == "FATHER_OF" for r in kept), r6.detail["children"],
            r6.detail["children_with_2plus_fathers"]) == (50, 47, 3)
    relation_probes = {fact["id"] for fact in probes["facts"] if fact["kind"] == "relation"}
    assert len(relation_probes) == 8
    assert [p["id"] for p in evaluate_probes(kg, ctx) if p["id"] in relation_probes and not p["passed"]] == []

    # every parent encoding: children with 2+ non-female parents 135 of 262 -> 8 of 383, with >2
    # parents 87 -> 1 (none mode after 10.2 is the batch-0 staging graph; live gives the same figures)
    female = set(probes["female_persons"])
    assert _parents(_after_10_2(*none_run), female) == (262, 135, 87)
    assert _parents(kept, female) == (383, 8, 1)


def test_stamps(real_inputs, all_run):
    rows, report = all_run
    # REL-04/09: every row says where it came from; K5: none keeps the lookup-table confidence
    assert not any("confidence" in r for r in rows)
    assert all(r.get(k) for r in rows for k in ("source", "pp_version", "schema_version", "run_id"))
    assert [_key(r) for r in rows if r["extraction_phase"] != PHASE_OF_SOURCE[r["source"]]] == []
    legacy = "legacy-re-2026-05"
    assert Counter((r["source"], r["run_id"], r.get("model")) for r in rows) == {
        ("prior", legacy, None): 64, ("llm", legacy, "unknown"): 5313, ("anchored_rule", report["run_id"], None): 319}

    # confidence_raw is the confidence the primary row came with, null on exactly the 319 anchored
    # rows; the 7 keys the anchored rule shares keep their prior's or llm row's
    inputs, cfg = real_inputs
    given = {(*_key(r), r["source"]): r["confidence"] for r in (pp.base_stamp(r, cfg) for r in inputs.relations)}
    assert [_key(r) for r in rows if r["source"] != "anchored_rule"
            and r["confidence_raw"] != given[(*_key(r), r["source"])]] == []
    assert Counter(r["source"] for r in rows if r["confidence_raw"] is None) == {"anchored_rule": 319}
    shared = [r for r in rows if len(r["sources"]) > 1]
    assert Counter((r["source"], r["confidence_raw"]) for r in shared) == {("llm", 0.78): 5, ("prior", 0.99): 2}

    # the diff_kg ee_edges keys after 10.2: prior 22 (64 edges), llm 35 (5,233), anchored 4 (319)
    keys: dict[str, dict[str, int]] = {}
    for key, n in report["expected_after_10_2"]["by_ee_key"].items():
        keys.setdefault(key.rsplit("source=", 1)[1], {})[key.split(" ", 1)[0]] = n
    assert {source: (len(by), sum(by.values())) for source, by in keys.items()} == {
        "prior": (22, 64), "llm": (35, 5233), "anchored_rule": (4, 319)}
    assert keys["anchored_rule"] == {"SON_OF": 298, "DAUGHTER_OF": 10, "FATHER_OF": 5, "SPOUSE_OF": 6}


def _seed_runs(tmp_path: Path, rules: str) -> list[tuple[bytes, bytes]]:
    """relations_clean.jsonl and report bytes of 6.05 --rules RULES run under PYTHONHASHSEED 1 and 987."""
    out, report = tmp_path / "relations_clean.jsonl", tmp_path / "relations_clean.report.json"
    runs = []
    for seed in ("1", "987"):
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.relation_extraction.relation_postprocess", "--rules", rules,
             "--out", str(out), "--report", str(report)],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONHASHSEED": seed})
        assert proc.returncode == 0, proc.stderr
        runs.append((out.read_bytes(), report.read_bytes()))
    return runs


@pytest.mark.skipif(not _inputs_present(), reason="output/ JSONL artifacts are not present")
def test_none_mode_is_byte_identical_across_hash_seeds(tmp_path):
    runs = _seed_runs(tmp_path, "none")
    assert runs[0] == runs[1]


@pytest.mark.skipif(not _inputs_present(), reason="output/ JSONL artifacts are not present")
def test_all_mode_is_byte_identical_across_hash_seeds(tmp_path):
    # every rule, the anchored rule's set and dict walks included, and the stamps: the bytes 6.1
    # imports and the report do not depend on the hash seed
    runs = _seed_runs(tmp_path, "all")
    assert runs[0] == runs[1]
    assert b'"run_id": "legacy-re-2026-05"' in runs[0][0] and b'"confidence"' not in runs[0][0]
