"""validate_kg quality gate (plan §3.6): the shipped config files.

config/kg_quality_baseline/ is the baseline split by check family (index.json
lists the parts in merge order); config/kg_probes.yaml the probe facts;
config/step0_sha.json the H7 sha target. Every file stays under the repo's
800-line limit, so a growing check family gets a part of its own instead.

Split from test_validate_kg.py (see test_validate_kg_checks.py); shared pieces
are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import json
import re

import validate_kg as vk
from _validate_kg_helpers import SHIPPED_BASELINE, SHIPPED_PROBES

MAX_LINES = 800
# The single config/kg_quality_baseline.json at 7fa9d00, in order: the merged
# parts must hold exactly these checks (a check added later extends the list).
PRE_SPLIT_IDS = [*(f"H{i}" for i in range(1, 12)), *(f"R{i}" for i in range(1, 12)), "PROBES", "W", "D1"]
FAMILY = {"h.json": r"H\d+", "r.json": r"R\d+", "misc.json": r"(?!H\d|R\d).+"}
# The hard checks, keyed by the batch that made them hard (their hard_from);
# a batch that hardens a check adds its own key.
HARD_BY_BATCH = {"0": {"H1", "H2", "H7", "D1"}, "1A": {"H3", "H9", "H11", "R6"},
                 "1B": {"H8", "R4", "R11"}}
# K3 (batch-1 plan §2.1): R6 gates contradictions, female heads and its probes;
# its functionality readings stay record ratchets (≤5% is deferred-A).
R6_RECORD_METRICS = {"functional_violation_rate", "children_with_2plus_nonfemale_parents",
                     "children_with_gt2_parents"}
# 1A's relation probes (kg_probes.yaml): id -> (check, edge, expect).
PROBES_1A = {
    "kin-david-son-of-jesse": ("R6", ("person:dawei", "SON_OF", "person:yexi"), "present"),
    "kin-esau-father-of-jalam": ("R6", ("person:yisao", "FATHER_OF", "person:yalan"), "present"),
    "kin-amram-father-of-moses": ("R6", ("person:anlan", "FATHER_OF", "person:moxi"), "present"),
    "edge-no-dan-near-jordan": ("H3", ("place:dan", "NEAR", "place:yuedan"), "absent"),
    "edge-no-galilee-in-nazareth": ("H11", ("place:jialili", "LOCATED_IN", "place:nasalei"), "absent"),
    "kin-peter-not-son-of-john": ("R6", ("person:bide", "SON_OF", "person:yuehan（shitu）"), "absent"),
    "kin-jethro-not-son-of-esau": ("R6", ("person:yeteluo", "SON_OF", "person:yisao"), "absent"),
    "kin-nahath-not-son-of-jethro": ("R6", ("person:naha", "SON_OF", "person:yeteluo"), "absent"),
}
FAIL_TODAY_1A = {"kin-esau-father-of-jalam", "edge-no-dan-near-jordan", "edge-no-galilee-in-nazareth"}
LIUER_GUARDS = {"kin-jethro-not-son-of-esau", "kin-nahath-not-son-of-jethro"}
# Of the probes' edges: those on prod 2026-10-05 (David's as a phase-5 inverse,
# Amram's a prior) and those in the W1 6.05 output after 10.2 (sha 1c0cf064…).
PROD_EDGES = (("person:dawei", "SON_OF", "person:yexi"), ("person:anlan", "FATHER_OF", "person:moxi"),
              ("place:dan", "NEAR", "place:yuedan"), ("place:jialili", "LOCATED_IN", "place:nasalei"))
W1_EDGES = (("person:dawei", "SON_OF", "person:yexi"), ("person:yisao", "FATHER_OF", "person:yalan"),
            ("person:anlan", "FATHER_OF", "person:moxi"))
# What gen 36 gives once 流珥 (person:liuer) resolves to 葉忒羅 (batch-1 plan C4)
LIUER_AS_JETHRO = (("person:yeteluo", "SON_OF", "person:yisao"), ("person:naha", "SON_OF", "person:yeteluo"))


# ---------------------------------------------------------------------------
# shipped config files
# ---------------------------------------------------------------------------

def test_shipped_baseline_covers_every_check_with_batch_severities():
    doc = vk.load_baseline(SHIPPED_BASELINE)
    ids = {c["id"] for c in doc["checks"]}
    assert ids == set(vk.CHECKS)
    severity = {c["id"]: c["severity"] for c in doc["checks"]}
    assert {i for i, s in severity.items() if s == "hard"} == set().union(*HARD_BY_BATCH.values())
    hard_from = {c["id"]: c["hard_from"] for c in doc["checks"]}
    assert all(hard_from[i] == batch for batch, hard in HARD_BY_BATCH.items() for i in hard)
    assert severity["W"] == "warn"
    for check in doc["checks"]:
        assert check.get("query"), check["id"]
        for name, m in check["metrics"].items():
            assert {"value", "direction", "tolerance"} <= set(m), (check["id"], name)


def test_shipped_r6_keeps_its_functionality_metrics_record():
    doc = vk.load_baseline(SHIPPED_BASELINE)
    overridden = {(c["id"], name): m["severity"]
                  for c in doc["checks"] for name, m in c["metrics"].items() if "severity" in m}
    assert overridden == {("R6", name): "record" for name in R6_RECORD_METRICS}
    rate = next(c for c in doc["checks"] if c["id"] == "R6")["metrics"]["functional_violation_rate"]
    assert rate["target"] == 0.05  # kept for reference: the ratchet, not 5%, is what gates


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


def _results_1a(edges: tuple) -> dict[str, bool]:
    kg = vk.KG(mode="snapshot", relations=[{"head": h, "type": r, "tail": t} for h, r, t in edges])
    ctx = vk.Context(baseline={"checks": []}, probes=vk.load_probes(SHIPPED_PROBES))
    return {p["id"]: p["passed"] for p in vk.evaluate_probes(kg, ctx) if p["id"] in PROBES_1A}


def test_shipped_probes_cover_the_1a_facts():
    facts = {f["id"]: f for f in vk.load_probes(SHIPPED_PROBES)["facts"] if f["id"] in PROBES_1A}
    assert {pid: (f["kind"], f["check"], (f["head"], f["rel"], f["tail"]), f["expect"])
            for pid, f in facts.items()} == {pid: ("relation", *spec) for pid, spec in PROBES_1A.items()}
    # prod fails three (jalam missing, the 但 and 加利利 edges present); the W1
    # edges pass all eight; 流珥 resolved to 葉忒羅 fails the two guards alone
    assert _results_1a(PROD_EDGES) == {pid: pid not in FAIL_TODAY_1A for pid in PROBES_1A}
    assert _results_1a(W1_EDGES) == dict.fromkeys(PROBES_1A, True)
    assert _results_1a((*W1_EDGES, *LIUER_AS_JETHRO)) == {pid: pid not in LIUER_GUARDS for pid in PROBES_1A}


def test_1a_fail_today_probes_stay_out_of_the_stored_ids():
    # kg_probes.yaml header, PROBES/R6 ids_note: they must pass once W1 is
    # loaded and are never --accept'ed in (every pre-W1 run reports them new)
    by_id = {c["id"]: c["metrics"] for c in vk.load_baseline(SHIPPED_BASELINE)["checks"]}
    stored = set(by_id["PROBES"]["failing"]["value"]) | set(by_id["R6"]["failing_probes"]["value"])
    assert not stored & FAIL_TODAY_1A


# ---------------------------------------------------------------------------
# the split baseline layout
# ---------------------------------------------------------------------------

def test_gate_config_files_stay_under_800_lines():
    files = [*sorted(vk.DEFAULT_BASELINE.glob("*.json")), vk.DEFAULT_PROBES, vk.DEFAULT_STEP0_SHA]
    assert len(files) == len(FAMILY) + 3  # the parts, index.json, probes and step0 sha
    for path in files:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= MAX_LINES, path


def test_split_baseline_merges_to_the_pre_split_checks_in_order():
    index = json.loads((SHIPPED_BASELINE / "index.json").read_text(encoding="utf-8"))
    assert index["parts"] == list(FAMILY)
    for name, pattern in FAMILY.items():
        part = json.loads((SHIPPED_BASELINE / name).read_text(encoding="utf-8"))
        assert part["checks"] and all(re.fullmatch(pattern, c["id"]) for c in part["checks"]), name
    assert [c["id"] for c in vk.load_baseline(SHIPPED_BASELINE)["checks"]] == PRE_SPLIT_IDS


def test_baseline_files_are_stored_as_the_gate_writes_them():
    # --ratchet/--accept rewrite a part with json.dumps(indent=2); a part kept in
    # any other layout would turn its first ratchet into a whole-file diff
    for path in sorted(SHIPPED_BASELINE.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n", path.name
