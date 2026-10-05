"""validate_kg quality gate (plan §3.6): exit codes, ratchet, warnings and the CLI.

Exit codes and ratchet direction run through main() against a baseline built
from the shipped config/kg_quality_baseline/ with its values cleared, so the
shipped severities/directions are what is being tested. The split baseline
directory itself is read merged and written back part by part (its own
section below). The live projection test is read-only and skips without Neo4j.

Split from test_validate_kg.py, together with test_validate_kg_checks.py and
test_validate_kg_shipped.py; shared pieces are in _validate_kg_helpers.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import validate_kg as vk
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
    read_rows,
    unsupported_edge,
    write_rows,
    write_step0_sha,
)
# snap is a pytest fixture: importing it is what makes it available here.
from _validate_kg_helpers import snap  # noqa: F401


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


def _prior_father(head: str, tail: str) -> dict:
    """A prior (phase 3) FATHER_OF with no source pericope: H3 exempts it, so of the
    scored checks only R6 (and W's histogram, a warning) sees it."""
    return {"head_id": head, "relation": "FATHER_OF", "tail_id": tail, "source_pericope_id": "",
            "extraction_phase": 3, "notes": "", "source": "prior"}


def test_record_metric_inside_a_hard_check_regresses_without_failing(snap, tmp_path, capsys):
    # K3: R6 turns hard in 1A while its functionality rate stays a record ratchet
    baseline = fresh_baseline(tmp_path, snap)
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    r6 = next(c for c in doc["checks"] if c["id"] == "R6")
    r6["severity"] = "hard"
    r6["metrics"]["functional_violation_rate"]["severity"] = "record"
    baseline.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert cli(snap, baseline, capsys, "--ratchet")[0] == 0
    assert _stored(baseline, "R6", "functional_violation_rate") == 0.0

    append_row(snap / "relations.jsonl", _prior_father("person:nahe", "person:yisa"))
    code, report = cli(snap, baseline, capsys)  # 以撒 has 2 fathers: rate 0.25, over the 0.05 target
    rate = report["checks"]["R6"]["metrics"]["functional_violation_rate"]
    assert (code, report["regressions"], report["failures"]) == (2, ["R6"], [])
    assert rate["status"] == "regressed" and rate["severity"] == "record"
    vk.print_report(report)
    assert "functional_violation_rate=0.25 (vs 0) [regressed]" in capsys.readouterr().out  # its baseline, not 0.05

    append_row(snap / "relations.jsonl", _prior_father("person:maliya", "person:make"))
    code, report = cli(snap, baseline, capsys)  # a female head: a hard metric of the same check
    r6 = report["checks"]["R6"]
    assert (code, report["hard_failures"], r6["status"]) == (1, ["R6"], "fail")
    assert r6["metrics"]["female_head"]["status"] == "fail"
    assert r6["metrics"]["functional_violation_rate"]["status"] == "regressed"


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
           "source_pericope_id": "gen:11:2", "extraction_phase": 2, "source": "rule"}
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
    doc = vk.load_baseline(SHIPPED_BASELINE)
    next(c for c in doc["checks"] if c["id"] == "PROBES")["metrics"]["failures"]["value"] += 1
    (tmp_path / "baseline.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="PROBES.failures"):
        vk.load_baseline(tmp_path / "baseline.json")


@pytest.mark.parametrize("severity,loads", [("hard", True), ("record", True), ("warn", False),
                                            ("soft", False), (None, False)])
def test_metric_severity_must_be_hard_or_record(tmp_path, severity, loads):
    doc = vk.load_baseline(SHIPPED_BASELINE)
    next(c for c in doc["checks"] if c["id"] == "R6")["metrics"]["female_head"]["severity"] = severity
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if loads:
        assert vk.load_baseline(path) == doc
    else:
        with pytest.raises(ValueError, match="R6.female_head"):
            vk.load_baseline(path)


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
# the split baseline directory: read merged, written back part by part
# ---------------------------------------------------------------------------

def split_baseline(tmp_path: Path, snap: Path) -> Path:
    """fresh_baseline's cleared values, kept in the shipped split layout."""
    dest = tmp_path / "baseline"
    shutil.copytree(SHIPPED_BASELINE, dest)
    for part in dest.glob("*.json"):
        doc = json.loads(part.read_text(encoding="utf-8"))
        for check in doc.get("checks", []):
            for metric in check["metrics"].values():
                metric["value"] = None
        part.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_step0_sha(tmp_path / "step0_sha.json", _sha(snap / "embedding_queue.jsonl"))
    return dest


def _rewritten_by(baseline: Path, run) -> set[str]:
    """Names of the baseline files whose bytes `run` changed."""
    before = {p.name: p.read_bytes() for p in baseline.iterdir()}
    run()
    return {p.name for p in baseline.iterdir() if before.get(p.name) != p.read_bytes()}


def test_ratchet_and_accept_write_each_check_back_to_its_part(snap, tmp_path, capsys):
    baseline = split_baseline(tmp_path, snap)

    def run(*extra: str):
        return lambda: cli(snap, baseline, capsys, *extra)

    append_row(snap / "relations.jsonl", unsupported_edge())
    assert _rewritten_by(baseline, run("--ratchet")) == {"h.json", "r.json", "misc.json"}  # nulls filled
    single = fresh_baseline(tmp_path, snap)  # the same run on one file stores the same checks
    assert cli(snap, single, capsys, "--ratchet")[0] == 0
    assert vk.load_baseline(baseline)["checks"] == vk.load_baseline(single)["checks"]

    write_rows(snap / "relations.jsonl", read_rows(snap / "relations.jsonl")[:-1])  # H3 heals
    assert _rewritten_by(baseline, run("--ratchet")) == {"h.json"}
    append_row(snap / "cross_references.jsonl", {"source_id": "exo:1:0", "target_id": "gen:22:0",
                                                 "source": "tsk", "votes": 3, "curated": False, "tsk": True})
    assert _rewritten_by(baseline, run("--ratchet")) == {"r.json"}  # R11 rises
    append_row(snap / "entities.jsonl", {"entity_id": "person:xin", "labels": ["Person"],
                                         "canonical_name": "新人", "aliases": [], "description": ""})
    assert _rewritten_by(baseline, run("--accept", "W")) == {"misc.json"}  # W's histogram drifted

    stored = {c["id"]: c["metrics"] for c in vk.load_baseline(baseline)["checks"]}
    assert (stored["H3"]["unsupported"]["value"], stored["R11"]["tsk_votes_edges"]["value"]) == (0, 2)
    code, report = cli(snap, baseline, capsys)
    assert code == 0 and report["checks"]["W"]["status"] == "ok"  # the accepted histogram is the new one


@pytest.mark.parametrize("damage,named", [("stray_part", "extra.json"), ("missing_part", "r.json"),
                                          ("duplicate_id", "H1")])
def test_split_baseline_layout_errors_refuse_to_load(tmp_path, damage, named):
    # a part outside the index, or a check in two parts, would drop out of the
    # gate or be written back twice: the whole baseline refuses to load
    baseline = tmp_path / "baseline"
    shutil.copytree(SHIPPED_BASELINE, baseline)
    if damage == "stray_part":
        (baseline / "extra.json").write_text(json.dumps({"format": "kg_quality_baseline/v1", "checks": []}),
                                             encoding="utf-8")
    elif damage == "missing_part":
        (baseline / "r.json").unlink()
    else:
        h1 = next(c for c in json.loads((baseline / "h.json").read_text(encoding="utf-8"))["checks"]
                  if c["id"] == "H1")
        r = json.loads((baseline / "r.json").read_text(encoding="utf-8"))
        (baseline / "r.json").write_text(json.dumps({**r, "checks": r["checks"] + [h1]}), encoding="utf-8")
    with pytest.raises(ValueError, match=named):
        vk.load_baseline(baseline)


@pytest.mark.parametrize("edit", ["check_added", "check_removed"])
def test_save_refuses_a_document_stale_against_the_parts_on_disk(tmp_path, edit):
    # a part edited by hand while a run is going (D1 can take ~15 min): writing
    # the stale document back would KeyError or silently drop the new check
    baseline = tmp_path / "baseline"
    shutil.copytree(SHIPPED_BASELINE, baseline)
    doc = vk.load_baseline(baseline)
    r = json.loads((baseline / "r.json").read_text(encoding="utf-8"))
    extra = {**r["checks"][0], "id": "R99"}
    checks = r["checks"] + [extra] if edit == "check_added" else r["checks"][1:]
    (baseline / "r.json").write_text(json.dumps({**r, "checks": checks}), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in baseline.glob("*.json")}

    with pytest.raises(ValueError, match="parts hold"):
        vk.save_baseline(baseline, doc)
    assert {p.name: p.read_bytes() for p in baseline.glob("*.json")} == before


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
