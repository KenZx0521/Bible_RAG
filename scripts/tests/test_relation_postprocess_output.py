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

from entity_extraction import entity_overrides, geo_rules
from relation_extraction import relation_postprocess as pp
from relation_extraction.anchored_rules import GuardConfig

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


@pytest.mark.skipif(not _inputs_present(), reason="output/ JSONL artifacts are not present")
def test_none_mode_is_byte_identical_across_hash_seeds(tmp_path):
    out, report = tmp_path / "relations_clean.jsonl", tmp_path / "relations_clean.report.json"
    runs = []
    for seed in ("1", "987"):
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.relation_extraction.relation_postprocess", "--rules", "none",
             "--out", str(out), "--report", str(report)],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONHASHSEED": seed})
        assert proc.returncode == 0, proc.stderr
        runs.append((out.read_bytes(), report.read_bytes()))
    assert runs[0] == runs[1]
