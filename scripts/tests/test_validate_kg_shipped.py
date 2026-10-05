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
PRE_SPLIT_IDS = [*(f"H{i}" for i in range(1, 11)), *(f"R{i}" for i in range(1, 12)), "PROBES", "W", "D1"]
FAMILY = {"h.json": r"H\d+", "r.json": r"R\d+", "misc.json": r"(?!H\d|R\d).+"}
# Record checks turned hard when their batch landed (hard_from), one set per batch.
HARD_FROM_1B = {"H8", "R4", "R11"}


# ---------------------------------------------------------------------------
# shipped config files
# ---------------------------------------------------------------------------

def test_shipped_baseline_covers_every_check_with_batch0_severities():
    doc = vk.load_baseline(SHIPPED_BASELINE)
    ids = {c["id"] for c in doc["checks"]}
    assert ids == set(vk.CHECKS)
    severity = {c["id"]: c["severity"] for c in doc["checks"]}
    assert {i for i, s in severity.items() if s == "hard"} == {"H1", "H2", "H7", "D1"} | HARD_FROM_1B
    assert {c["hard_from"] for c in doc["checks"] if c["id"] in HARD_FROM_1B} == {"1B"}
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
