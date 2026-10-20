"""GEN confirmation set: K0-合成 (k0_g; prereg §8.1-1, §3.3, §3.9, §5.3).

k0_g on tmp out roots: every item (the pool recompute, the pytest selections, the sys.modules probe) is a fake unless
named, git is a fake and the harness record a fake writing a tmp file (or f1_g's real record_k0 with a stand-in
suite). A dirty tree, a passed K0 and an existing harness record are refused before anything is computed; a failing
item or a refused harness record is kept as a numbered attempt (pass false, no k0.json, no harness record) and K0 runs
again after the fix; k0.json is written last, once, after the harness record; an item or a suite that writes below
the watched out root fails; a layer count below its total is a K-gold candidate and never prints the stop sentence;
nothing printed holds a CJK character, and k0.json holds counts, booleans, sha256 and names only; k0_problems gates
a USD step on a passing K0 and its record. The pytest summary and FAILED/ERROR parsers, the selection rule (a skip,
an xfail, an xpass, an error, a failure, no test or only deselected tests fail) and the caller's PYTHONPATH left out;
the item map: §8.1-1's lines in order with their defining tests, every test file in a selection or excluded with a
reason, every selection collects tests in a fresh interpreter and none reaches back into this file's store check. The
sys.modules rules on synthetic probe results, the probe itself on synthetic modules in a tmp folder (loading A's
support, a qset module or an A module by path, HO's banned by name, binding c_common or hoa_common, a g_common copy;
one clean), the static import scan on a synthetic source, and the §3.9 test itself on the real checkout (only the
prod-trigger load needs the store). Store tests (skipped when it is not mounted): the frozen pins of A, stage-0 and the
store hold, the F0 files are the ones the log's F0 entry names, and k0_g.check() passes on the real store and leaves
every file below its out root as it was. `k0_g.py run` is never run on the real store. Every string here is made up or
ASCII. Nothing calls Ollama or any LLM.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import f1_g as F1  # noqa: E402
import g_common as GC  # noqa: E402
import hog_common as HG  # noqa: E402
import k0_g as K0  # noqa: E402
import probe_g as PR  # noqa: E402
import run_ho_g as RH  # noqa: E402
import run_qg as RQ  # noqa: E402

STORE_OK = GC.POOL.is_file() and GC.GEN_LAYER.is_file() and GC.GEN_NAMES.is_file() and GC.R4_LAYER.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({GC.OUT_ROOT})")
CJK = re.compile(r"[㐀-鿿豈-﫿]")
COLLECTED = re.compile(r"(\d+)(?:/\d+)? tests? collected")
HEX64 = re.compile(r"[0-9a-f]{64}")
CONFIRM = "evaluation/experiments/2026-10-18_kg_cards/A/confirm"
STAGE0 = K0.rel(GC.STAGE0_DIR)
BASELINE = {n: f"{CONFIRM}/{n}.py" for n in ("analyze_c", "c_common", "guards_c")}
WIDE_BASE = {"cards_common": "evaluation/experiments/2026-10-18_kg_cards/cards_common.py",
             "a_common": "evaluation/experiments/2026-10-18_kg_cards/A/a_common.py",
             **{n: f"{STAGE0}/{n}.py" for n in ("x_common", "gen_layer", "items_x", "engine_x", "keys_x")}}
WIDE = {**BASELINE, **WIDE_BASE}                      # a wide snapshot: kg_cards (A/confirm too) and stage-0
POOL_OK = {"pass": True, "counts": {"k0_gold": [58, 58], "k0_lines": [96, 96], "k0_card": [58, 58],
                                    "max_chars_g": 338, "cap_chars": 900}, "k_gold_candidate": False}
MODULES_OK = {"pass": True, "counts": {"probed": 2, "baseline": 3, "problems": 0}}
PINS = {"sha256": "a" * 64}


def outcomes(**kw) -> dict:
    return {**dict.fromkeys(K0.OUTCOMES, 0), **kw}


def green(_selection) -> dict:
    return {"returncode": 0, "counts": outcomes(passed=3), "failed_tests": []}


@pytest.fixture
def fake(tmp_path):
    """Fake items, pins, git, suite and harness record; k0.json, the attempts and the record land in a tmp out root,
    which is the watched one."""
    store = tmp_path / "out"
    out, hr, att = store / "k0.json", store / "harness_record.json", store / "k0_attempts"
    calls, lines = [], []

    def record(*, record, tests, **_kw):                 # f1_g.record_k0's order: refused unless the suite passes
        calls.append((record, out.exists()))
        bad = tests()
        if bad:
            raise SystemExit(f"K0 harness record refused: {bad}")
        GC.write_json(record, {"schema": "fake.harness_record", "k0": dict(PINS)})

    kw = dict(pool=lambda: dict(POOL_OK), run_tests=green, modules=lambda: dict(MODULES_OK), pins=lambda: dict(PINS),
              watch=store)
    run = lambda **over: K0.run(**{"out": out, "harness_record": hr, "attempts": att, "git": lambda: [],  # noqa: E731
                                   "record": record, "suite": lambda: [], "log": lines.append, **kw, **over})
    return SimpleNamespace(out=out, hr=hr, att=att, store=store, calls=calls, lines=lines, kw=kw, run=run,
                           root=tmp_path)


def boom(*_a, **_k):
    raise AssertionError("must not be called")


def refused(*, record, **_kw):
    raise SystemExit("K0 harness record refused: ['the test_gen_confirm_* suite fails (1 failed, 9 passed in 1.0s)']")


def leaves(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from leaves(v)
    else:
        yield obj


# ---------------------------------------------------------------- run and check on a tmp out root
def test_run_refuses_a_dirty_tree_before_anything_and_writes_nothing(fake):
    with pytest.raises(SystemExit, match="harness files changed"):
        fake.run(git=lambda: ["harness files changed or untracked since the last commit"], pool=boom)
    assert not fake.store.exists() and not fake.calls and not fake.lines


def test_run_refuses_a_passed_k0_and_an_existing_harness_record(fake):
    assert fake.run() == 0
    first = fake.out.read_bytes()
    with pytest.raises(SystemExit, match="K0 passed and is made once"):
        fake.run(pool=boom)
    assert fake.out.read_bytes() == first and len(fake.calls) == 1
    fake.out.unlink()
    with pytest.raises(SystemExit, match="harness record is made once"):
        fake.run(pool=boom)
    assert not fake.out.exists()


def test_run_writes_the_harness_record_then_k0_once_and_prints_both_sha(fake):
    assert fake.run() == 0
    doc = GC.read_json(fake.out)
    assert set(doc) == {"schema", "t", "git_head", "harness_sha256", "pass", "items", "failed_attempts"}
    assert doc["schema"] == K0.SCHEMA and doc["pass"] is True and doc["harness_sha256"] == PINS["sha256"]
    assert list(doc["items"]) == list(K0.ITEM_ORDER) and all(v["pass"] for v in doc["items"].values())
    assert doc["failed_attempts"] == 0 and not fake.att.exists()
    assert fake.calls == [(fake.hr, False)]                    # the record came before k0.json
    shas = json.loads(fake.lines[-1])
    assert shas == {"k0_sha256": GC.sha256_file(fake.out), "harness_record_sha256": GC.sha256_file(fake.hr)}


def test_run_with_the_real_record_k0_records_the_harness_and_a_later_store_check_still_passes(fake):
    """F1: f1_g.record_k0 itself (the suite a stand-in): its record, then k0.json; afterwards the store check of a later
    suite (test_k0_check_passes_on_the_real_store's rule) passes with both files in the out root."""
    seen = []

    def suite():
        seen.append((fake.out.exists(), fake.hr.exists()))
        return []
    assert fake.run(record=None, suite=suite) == 0
    rec = GC.read_json(fake.hr)
    assert rec["schema"] == "gen_confirm.harness_record.v1" and rec["k0"]["sha256"] == PINS["sha256"]
    assert seen == [(False, False)] and K0.k0_problems(fake.out, fake.hr, harness=lambda **_k: []) == []
    before, lines = K0.store_snapshot(fake.store), []
    assert K0.check(log=lines.append, **fake.kw) == 0
    assert K0.changed_paths(before, K0.store_snapshot(fake.store)) == []


@pytest.mark.parametrize("which", ["pool", "selection", "modules"])
def test_a_failing_item_is_an_attempt_and_makes_neither_k0_nor_a_harness_record(fake, which):
    over = {"pool": {"pool": lambda: {**POOL_OK, "pass": False}},
            "selection": {"run_tests": lambda s: {"returncode": 1, "counts": outcomes(passed=2, failed=1),
                                                  "failed_tests": ["tests/test_x.py::test_y"]}},
            "modules": {"modules": lambda: {**MODULES_OK, "pass": False}}}[which]
    assert fake.run(**over) == 1
    assert not fake.out.exists() and not fake.hr.exists() and not fake.calls
    (attempt,) = K0.attempts_of(fake.att)
    doc = GC.read_json(attempt)
    assert attempt.name == "001.json" and doc["pass"] is False and doc["attempt"] == 1
    assert doc["harness_record"] == "not made"
    last = json.loads(fake.lines[-1])
    assert last["failed"] == (["pool"] if which == "pool" else ["modules"] if which == "modules" else
                              [k for k, _r, _s in K0.TEST_ITEMS])
    assert last["attempt"] == 1 and last["attempt_sha256"] == GC.sha256_file(attempt)


def test_a_failed_k0_is_kept_and_k0_runs_again_after_the_fix(fake):
    """F2: §8.1-1 「任何失敗都要修好」: a failed item and a refused harness record are attempts 1 and 2; the fixed K0
    then passes, once."""
    assert fake.run(pool=lambda: {**POOL_OK, "pass": False}) == 1
    assert fake.run(record=refused) == 1
    a1, a2 = (GC.read_json(p) for p in K0.attempts_of(fake.att))
    assert (a1["attempt"], a1["harness_record"], a1["items"]["pool"]["pass"]) == (1, "not made", False)
    assert (a2["attempt"], a2["harness_record"], a2["pass"], a2["items"]["pool"]["pass"]) == (2, "refused", False, True)
    assert "suite fails (1 failed, 9 passed" in a2["refusal"] and not fake.out.exists() and not fake.hr.exists()
    assert json.loads(fake.lines[-1])["harness_record"] == "refused"
    assert fake.run() == 0 and GC.read_json(fake.out)["failed_attempts"] == 2
    with pytest.raises(SystemExit, match="made once"):
        fake.run(pool=boom)


def test_an_item_that_writes_below_the_watched_root_fails_and_names_the_file(fake):
    """F3: writing nothing is checked: the first selection adds a file, the next leaves it as it is."""
    def writer(selection):
        GC.write_json(fake.store / "power" / "stray.json", {"n": 1})
        return green(selection)
    doc = K0.build(**{**fake.kw, "run_tests": writer})
    first, *rest = (doc["items"][k] for k, _r, _s in K0.TEST_ITEMS)
    assert first["pass"] is False and first["store_changed"] == ["power/stray.json"]
    assert all(v["pass"] for v in rest) and doc["pass"] is False
    lines = []
    assert K0.check(log=lines.append, **{**fake.kw, "pool": lambda: (fake.store / "power" / "stray.json").unlink()
                                         or dict(POOL_OK)}) == 1
    assert json.loads(lines[-1])["failed"] == ["pool"]


def test_a_suite_that_writes_into_the_store_refuses_the_harness_record(fake):
    def suite():
        GC.write_json(fake.store / "void.json", {"n": 1})
        return []
    assert fake.run(record=None, suite=suite) == 1
    assert not fake.hr.exists() and not fake.out.exists()
    (attempt,) = K0.attempts_of(fake.att)
    a = GC.read_json(attempt)
    assert a["harness_record"] == "refused" and "changed 1 store file(s): ['void.json']" in a["refusal"]


def test_the_store_snapshot_covers_every_file_below_its_root(tmp_path):
    GC.write_json(tmp_path / "a.json", {"n": 1})
    GC.write_json(tmp_path / "power" / "t.json", {"n": 1})
    snap = K0.store_snapshot(tmp_path)
    assert set(snap) == {"a.json", "power/t.json"} and all(HEX64.fullmatch(v) for v in snap.values())
    GC.write_json(tmp_path / "power" / "t.json", {"n": 2})
    (tmp_path / "a.json").unlink()
    GC.write_json(tmp_path / "b" / "c.json", {"n": 1})
    assert K0.changed_paths(snap, K0.store_snapshot(tmp_path)) == ["a.json", "b/c.json", "power/t.json"]
    assert K0.store_snapshot(tmp_path / "none") == {}


def test_a_layer_count_below_its_total_is_a_k_gold_candidate_without_the_stop_sentence(fake):
    """F9: §8.1-1 stops on a failure a trace puts on the layer; K0 names the candidate and leaves the trace to CPU."""
    pool = {**POOL_OK, "pass": False, "k_gold_candidate": True, "counts": {**POOL_OK["counts"], "k0_lines": [95, 96]}}
    assert fake.run(pool=lambda: pool) == 1
    last = json.loads(fake.lines[-1])
    assert last["k_gold_candidate"] is True and last["layer"] == "K0-lines 95/96"
    assert not [x for x in fake.lines if CJK.search(str(x))] and not fake.hr.exists() and not fake.calls


def test_k_gold_value_names_each_layer_check_below_its_total():
    c = {"k0_gold": [57, 58], "k0_lines": [95, 96], "k0_card": [50, 58]}
    assert K0.k_gold_value({"counts": c}) == "K0-gold 57/58、K0-lines 95/96"
    assert K0.k_gold_value({"counts": {**c, "k0_gold": [58, 58]}}) == "K0-lines 95/96"


def test_check_writes_nothing_and_its_exit_follows_the_items(fake):
    before = sorted(fake.root.rglob("*"))
    lines = []
    assert K0.check(log=lines.append, **fake.kw) == 0
    assert K0.check(log=lines.append, **{**fake.kw, "modules": lambda: {**MODULES_OK, "pass": False}}) == 1
    assert sorted(fake.root.rglob("*")) == before
    assert json.loads(lines[-1]) == {"failed": ["modules"], "k_gold_candidate": False}


def test_nothing_printed_holds_text(fake):
    lines = []
    K0.check(log=lines.append, **fake.kw)
    fake.run(pool=lambda: {**POOL_OK, "pass": False, "k_gold_candidate": True,
                           "counts": {**POOL_OK["counts"], "k0_gold": [57, 58]}})
    fake.run(record=refused)
    fake.run()
    assert len(lines + fake.lines) >= 8 and not [x for x in lines + fake.lines if CJK.search(str(x))]


def test_k0_json_holds_counts_booleans_sha_and_names_only(fake):
    fake.run(run_tests=lambda s: {"returncode": 0, "counts": outcomes(passed=4), "failed_tests": []})
    doc = GC.read_json(fake.out)
    vals = list(leaves(doc))
    assert all(isinstance(v, (str, int, float, bool)) or v is None for v in vals)
    assert not [v for v in vals if isinstance(v, str) and CJK.search(v)]
    for key, ref, selection in K0.TEST_ITEMS:
        item = doc["items"][key]
        assert item["prereg"] == ref and item["selection"] == list(selection) and item["counts"]["passed"] == 4
        assert item["files_sha256"] and all(HEX64.fullmatch(v) for v in item["files_sha256"].values())


def test_k0_problems_gate_a_usd_step_on_a_passing_k0_and_its_harness_record(fake):
    """F5's K0 side: what probe_g, run_qg, run_ho_g and the F1 manifest call before spending."""
    ok = lambda **_k: []  # noqa: E731
    assert K0.k0_problems(fake.out, fake.hr, harness=ok) == ["k0.json missing: K0 has not passed"]
    assert fake.run() == 0 and K0.k0_problems(fake.out, fake.hr, harness=ok) == []
    assert K0.k0_problems(fake.out, fake.hr, harness=lambda **_k: ["the harness differs"]) == ["the harness differs"]
    GC.write_json(fake.hr, {"k0": {"sha256": "b" * 64}})
    assert K0.k0_problems(fake.out, fake.hr, harness=ok) == ["k0.json's harness is not the K0 harness record's"]
    GC.write_json(fake.out, {**GC.read_json(fake.out), "pass": False})
    fake.hr.unlink()
    assert K0.k0_problems(fake.out, fake.hr, harness=ok) == ["k0.json is not a passing K0",
                                                             "harness_record.json missing: no K0 harness record"]


# ---------------------------------------------------------------- the pytest selections
def test_parse_summary_reads_every_outcome():
    assert K0.parse_summary("3 passed, 1 deselected in 0.12s") == outcomes(passed=3, deselected=1)
    line = "1 failed, 2 passed, 1 skipped, 1 xfailed, 1 xpassed, 2 errors, 3 warnings in 1.0s"
    assert K0.parse_summary(line) == outcomes(failed=1, passed=2, skipped=1, xfailed=1, xpassed=1, errors=2)
    assert K0.parse_summary("1 error in 0.1s") == outcomes(errors=1)
    assert K0.parse_summary("no tests ran in 0.01s") == outcomes() == K0.parse_summary("")


def test_failed_tests_name_failures_and_errors_without_parameter_or_message():
    lines = ["FAILED evaluation/tests/test_x.py::test_a[p1] - AssertionError: 1 != 2",
             "ERROR evaluation/tests/test_x.py::test_b - fixture 'syn' not found", "ERROR",
             "evaluation/tests/test_x.py::test_c PASSED", "FAILED evaluation/tests/test_x.py::test_a[p2]"]
    assert K0.failed_tests(lines) == ["evaluation/tests/test_x.py::test_a", "evaluation/tests/test_x.py::test_b"]


def test_a_selection_runs_without_the_callers_pythonpath(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return SimpleNamespace(returncode=1, stdout="ERROR evaluation/tests/test_x.py::test_b\n1 error in 0.1s\n")
    monkeypatch.setenv("PYTHONPATH", "/nowhere")
    monkeypatch.setattr(K0.subprocess, "run", fake_run)
    res = K0.pytest_selection(["evaluation/tests/test_x.py"])
    assert seen.get("env") is not None and "PYTHONPATH" not in seen["env"] and seen["cwd"] == GC.REPO
    assert res == {"returncode": 1, "counts": outcomes(errors=1), "failed_tests": ["evaluation/tests/test_x.py::test_b"]}


@pytest.mark.parametrize("rc, counts, ok", [
    (0, outcomes(passed=3), True), (0, outcomes(passed=3, deselected=2), True),
    (1, outcomes(passed=2, failed=1), False), (0, outcomes(passed=2, skipped=1), False),
    (0, outcomes(passed=2, xfailed=1), False), (0, outcomes(passed=2, xpassed=1), False),
    (1, outcomes(errors=1), False), (5, outcomes(), False), (5, outcomes(deselected=4), False),
    (0, outcomes(), False), (2, outcomes(passed=3), False)])
def test_a_selection_passes_only_with_passes_and_no_other_outcome(rc, counts, ok):
    item = K0.selection_item("§x", K0.TEST_ITEMS[0][2], run=lambda s: {"returncode": rc, "counts": counts,
                                                                         "failed_tests": []})
    assert item["pass"] is ok and item["counts"] == counts and item["returncode"] == rc


def test_a_selection_into_this_files_store_check_is_refused_unrun():
    for sel in ([K0.K0_TESTS], [f"{K0.K0_TESTS}::test_k0_check_passes_on_the_real_store"]):
        item = K0.selection_item("§x", sel, run=boom)
        assert item["pass"] is False and item["self_selected"] is True
    assert K0.selection_item("§x", [f"{K0.K0_TESTS}::test_f0_files_are_the_logged_ones"], run=green)["pass"]
    assert not any(K0.self_selected(sel) for _k, _r, sel in K0.TEST_ITEMS)


def test_selection_files_cover_the_imported_test_modules_and_conftest():
    t = K0.TESTS
    assert K0.selection_files([f"{t}/test_gen_confirm_ho_edges.py::test_x"]) == sorted(
        [f"{t}/conftest.py", f"{t}/test_gen_confirm_ho.py", f"{t}/test_gen_confirm_ho_edges.py"])
    assert f"{t}/test_gen_confirm_prompts.py" in K0.selection_files([f"{t}/test_gen_confirm_mech.py"])
    assert f"{t}/test_gen_confirm_qset.py" in K0.selection_files([f"{t}/test_gen_confirm_qset_run.py"])
    missing = K0.selection_item("§x", [f"{t}/test_gen_confirm_none.py"], run=green)
    assert missing["pass"] is False and missing["files_sha256"][f"{t}/test_gen_confirm_none.py"] is None


def collect(selection) -> tuple[int, int]:
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        *selection], cwd=GC.REPO, capture_output=True, text=True, timeout=600)
    m = COLLECTED.search(r.stdout)
    return r.returncode, int(m.group(1)) if m else 0


def test_every_item_selects_tests_that_exist():
    """Each selection collects in a fresh interpreter (pytest exits 4 on a node id it cannot find) and holds at least
    as many tests as it names."""
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = dict(zip([k for k, _r, _s in K0.TEST_ITEMS], ex.map(collect, [s for _k, _r, s in K0.TEST_ITEMS])))
    assert {k: rc for k, (rc, _n) in got.items()} == {k: 0 for k, _r, _s in K0.TEST_ITEMS}
    for key, _ref, selection in K0.TEST_ITEMS:
        assert got[key][1] >= len(selection) > 0, key
    assert len({k for k, _r, _s in K0.TEST_ITEMS}) == len(K0.TEST_ITEMS)


# §8.1-1's lines in order (pool and modules are k0_g's own items) and the tests each selection must hold
SECTION_8_1_1 = {
    "gencard_engine_x": ("§5.1", ["gencard.py::test_real_cards_equal_stage0s_engine_x_on_all_64_same_chapter_pairs"]),
    "nails_5_3": ("§5.3", ["gencard.py", "names.py"]),
    "mech_bank": ("§3.4", ["mech.py"]),
    "blinding_3_3": ("§3.3", ["prompts.py", "infra.py::test_k0_compliant_transcripts_pass_every_blinding_rule_in_both_modes",
                              "infra.py::test_k0_a_leaking_transcript_fails",
                              "qset.py::test_every_rendered_prompt_passes_the_prompt_scope_and_holds_no_cue_word",
                              "integration.py::test_each_new_marker_is_caught_in_a_transcript"]),
    "pins": ("§4.5", ["gates.py::test_stage0_problems_and_metric_version_hold_now",
                      "k0.py::test_frozen_pins_of_a_stage0_and_the_store_hold_now",
                      "k0.py::test_f0_files_are_the_logged_ones", "core.py::test_pool_is_the_registered_pool",
                      "integration.py::test_trigger_pins_have_the_shape_of_backend_pins_and_the_kept_values"]),
    "g_common_ledger": ("§3.9", ["core.py", "integration.py::test_every_alias_is_the_g_common_object",
                                 "integration.py::test_the_batch_3_values", "infra.py::test_refusal_at_49_usd",
                                 "infra.py::test_two_processes_contending_never_overrun_the_cap"]),
    "modules_tests": ("§3.9", ["run.py::test_runners_load_only_the_allowed_modules_of_a_and_none_of_ho_or_qset",
                               "infra.py::test_no_module_of_a_ho_a_or_the_qset_is_loaded"]),
}


def test_the_items_are_section_8_1_1s_lines_with_their_defining_tests():
    """F4: no line of §8.1-1 and no defining test (64 pairs, metric_version, frozen_mismatches, ...) drops out."""
    assert K0.ITEM_ORDER == ("pool", *SECTION_8_1_1, "modules")
    for key, ref, selection in K0.TEST_ITEMS:
        want_ref, need = SECTION_8_1_1[key]
        missing = [n for n in need if f"{K0.TESTS}/test_gen_confirm_{n}" not in selection]
        assert ref == want_ref and missing == [], key


def test_every_test_file_is_in_a_selection_or_excluded_with_a_reason():
    files = {p.stem[len("test_gen_confirm_"):] for p in GC.TESTS_DIR.glob("test_gen_confirm_*.py")}
    selected = {a.split("::")[0].rsplit("/", 1)[-1][len("test_gen_confirm_"):-len(".py")]
                for _k, _r, s in K0.TEST_ITEMS for a in s}
    assert selected <= files and not selected & set(K0.EXCLUDED_TESTS)
    assert sorted(files - selected) == sorted(K0.EXCLUDED_TESTS) and all(K0.EXCLUDED_TESTS.values())


# ---------------------------------------------------------------- the pool item
def pool_doc(**summary) -> dict:
    base = {"k0_gold": "58/58", "k0_lines": "96/96", "k0_card": "58/58", "max_chars_g": 338}
    return {"schema": "syn.pool", "summary": {**base, **summary}, "pool": []}


def test_pool_item_reports_counts_that_differ_and_never_adjusts_them(tmp_path):
    stored = tmp_path / "pool.json"
    GC.write_json(stored, pool_doc())
    item = K0.pool_item(build=lambda: pool_doc(k0_lines="95/96"), pool_file=stored)
    assert item["pass"] is False and item["k_gold_candidate"] is True and item["built"] is True
    assert item["counts"]["k0_lines"] == [95, 96] and item["recorded"]["k0_lines"] == [96, 96]
    assert item["same_as_recorded"] is False and item["same_as_registered"] is False
    assert item["k0_problems_none"] is False and item["rebuild_is_pool_json"] is False
    card = K0.pool_item(build=lambda: pool_doc(k0_card="57/58", max_chars_g=901), pool_file=stored)
    assert card["pass"] is False and card["k_gold_candidate"] is False and card["counts"]["max_chars_g"] == 901
    same = K0.pool_item(build=lambda: pool_doc(), pool_file=stored)
    assert same["same_as_recorded"] and same["same_as_registered"] and same["k0_problems_none"]
    assert same["pass"] is False and not same["k_gold_candidate"]   # a synthetic pool is never the pinned pool.json


def test_pool_json_must_be_the_pinned_file_even_when_the_rebuild_is(tmp_path, monkeypatch):
    """F7: the rebuild equal to the pin is not enough; store pool.json itself must be the pinned file."""
    doc, stored = pool_doc(), tmp_path / "pool.json"
    monkeypatch.setattr(GC, "POOL_SHA256", GC.sha256_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n"))
    GC.write_json(stored, doc)
    ok = K0.pool_item(build=lambda: pool_doc(), pool_file=stored)
    assert ok["pass"] is True and ok["pool_json_pinned"] is True and ok["rebuild_is_pool_json"] is True
    GC.write_json(stored, {**doc, "schema": "syn.pool.other"})
    other = K0.pool_item(build=lambda: pool_doc(), pool_file=stored)
    assert other["pass"] is False and other["pool_json_pinned"] is False and other["rebuild_is_pool_json"] is True
    stored.unlink()
    gone = K0.pool_item(build=lambda: pool_doc(), pool_file=stored)
    assert gone["pass"] is False and gone["pool_json_pinned"] is False


def test_pool_item_with_a_refused_layer_fails_without_a_k_gold_candidate(tmp_path):
    def refused_layer():
        raise SystemExit("gen_layer.json: sha256 is not the pinned prefix")
    item = K0.pool_item(build=refused_layer, pool_file=tmp_path / "pool.json")
    assert item == {"pass": False, "counts": {}, "built": False, "k_gold_candidate": False,
                    "files_sha256": item["files_sha256"]}
    assert item["files_sha256"][K0.rel(tmp_path / "pool.json")] is None

    def unmounted():
        raise FileNotFoundError("no store")
    assert K0.pool_item(build=unmounted, pool_file=tmp_path / "pool.json")["built"] is False


def test_timeouts_are_failures_not_crashes(monkeypatch):
    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired("python", 1)
    monkeypatch.setattr(K0.subprocess, "run", slow)
    res = K0.pytest_selection(["evaluation/tests/test_x.py"])
    assert res == {"returncode": None, "counts": outcomes(), "failed_tests": ["timeout"]}
    assert K0.selection_item("§x", K0.TEST_ITEMS[0][2], run=K0.pytest_selection)["pass"] is False
    assert K0.probe("k0_g", {}) == {"probe_error": "timeout"}


# ---------------------------------------------------------------- §3.9: the sys.modules rules
HO = dict(K0.HO_ALIASES)
GOOD = {"import_error": None, "own": {"c_common": BASELINE["c_common"]}, "own_wide": dict(WIDE), "trigger_errors": {},
        "as_is_error": None, "full": dict(BASELINE), "wide": dict(WIDE), "never": [], "ho": HO,
        "constants": {"binds": {"GC": {"stem": "g_common", "file": "x/g_common.py", "is_g_common": True}}, "values": []}}
BASE_RES = {"full": dict(BASELINE), "wide": dict(WIDE), "never": [], "ho": {"ho_bt_guard_for_g": HO["ho_bt_guard_for_g"]}}
SEG = f"{CONFIRM}/segments.py"
A_EXTRA = "evaluation/experiments/2026-10-18_kg_cards/A/report_md.py"
BAD_CASES = [
    ({"own": {"segments": SEG}}, ["x_g alone: loads segments (A/confirm)"]),
    ({"full": {**BASELINE, "banned_a": f"{CONFIRM}/ho_a/banned_a.py"}}, ["x_g: loads banned_a (ho_a)"]),
    ({"full": {**BASELINE, "q_x": "evaluation/experiments/2026-10-19_regnal_qset/q_x.py"}},
     ["x_g: loads q_x (regnal_qset)"]),
    ({"full": {**BASELINE, "c_common": "elsewhere/c_common.py"}}, ["x_g: c_common resolves to another file"]),
    ({"full": {k: v for k, v in BASELINE.items() if k != "guards_c"}}, ["x_g: guards_c of the baseline is not loaded"]),
    ({"own_wide": {"report_md": A_EXTRA}}, ["x_g alone: loads report_md (kg_cards)"]),
    ({"wide": {**WIDE, "report_md": A_EXTRA}}, ["x_g: loads report_md (kg_cards)"]),
    ({"wide": {**WIDE, "units_x": f"{STAGE0}/units_x.py"}}, ["x_g: loads units_x (stage-0)"]),
    ({"wide": {**WIDE, "x_common": "evaluation/experiments/2026-10-18_kg_cards/A/x_common.py"}},
     ["x_g: x_common resolves to another file"]),
    ({"wide": {k: v for k, v in WIDE.items() if k != "keys_x"}}, ["x_g: keys_x of the baseline is not loaded"]),
    ({"never": ["q_common"]}, ["x_g: loads q_common"]),
    ({"ho": {**HO, "ho_other": "evaluation/experiments/2026-10-14_graph_gd/ho_tools/bt.py"}},
     ["x_g: loads HO module ho_other"]),
    ({"ho": {**HO, "ho_bt_guard_for_g": "elsewhere/bt_guard.py"}}, ["x_g: loads HO module ho_bt_guard_for_g"]),
    ({"trigger_errors": {"stage0": "SystemExit"}}, ["x_g: trigger stage0 raised SystemExit"]),
    ({"import_error": "SystemExit"}, ["x_g: import raised SystemExit"]),
    ({"as_is_error": "ImportError"}, ["x_g: the as-is group raised ImportError"]),
    ({"constants": {"binds": {"C": {"stem": "c_common", "file": "f", "is_g_common": False}}, "values": []}},
     ["x_g.C: binds c_common"]),
    ({"constants": {"binds": {"H": {"stem": "hoa_common", "file": None, "is_g_common": False}}, "values": []}},
     ["x_g.H: binds hoa_common"]),
    ({"constants": {"binds": {"Q": {"stem": "q_common", "file": "f", "is_g_common": False}}, "values": []}},
     ["x_g.Q: binds q_common"]),
    ({"constants": {"binds": {"X": {"stem": "x_common", "file": "f", "is_g_common": False}}, "values": []}},
     ["x_g.X: binds stage-0's x_common"]),
    ({"constants": {"binds": {"GC": {"stem": "g_common", "file": "f", "is_g_common": False}}, "values": []}},
     ["x_g.GC: a g_common other than this folder's"]),
    ({"constants": {"binds": {}, "values": ["USD_CAP"]}}, ["x_g.USD_CAP: differs from g_common's"]),
]


def problems_of(res: dict) -> list[str]:
    return K0.module_problems("x_g", res, BASELINE, K0.outside(WIDE))


def test_a_clean_probe_has_no_problem():
    assert problems_of(GOOD) == [] and K0.outside(WIDE) == WIDE_BASE


@pytest.mark.parametrize("change, want", BAD_CASES)
def test_each_sys_modules_rule_names_its_breach(change, want):
    assert problems_of({**GOOD, **change}) == want


def test_a_failed_probe_and_a_missing_module_are_problems():
    assert problems_of({"probe_error": "exit 1"}) == ["x_g: probe exit 1"]
    assert problems_of({k: v for k, v in GOOD.items() if k != "constants"}) == ["x_g: not in sys.modules after its import"]


def test_x_common_is_allowed_only_where_listed():
    x = {"binds": {"X": {"stem": "x_common", "file": "f", "is_g_common": False}}, "values": []}
    assert K0.constants_problems("run_g", x) == [] and K0.X_COMMON_ALLOWED == {"run_g": ("X",)}
    assert K0.constants_problems("run_g", {"binds": {"Y": x["binds"]["X"]}, "values": []}) == [
        "run_g.Y: binds stage-0's x_common"]


def test_the_baseline_holds_the_as_is_imports_and_bt_guard_and_nothing_of_ho_a_or_the_qset():
    assert K0.baseline_problems(BASE_RES) == []
    assert K0.baseline_problems({**BASE_RES, "full": {}}) == [f"as-is group: lacks {n}" for n in sorted(BASELINE)]
    assert K0.baseline_problems({**BASE_RES, "wide": dict(BASELINE)}) == [
        f"as-is group: lacks {n}" for n in K0.BASELINE_WIDE_HAS]
    assert K0.baseline_problems({**BASE_RES, "ho": {}}) == ["as-is group: lacks HO's ho_bt_guard_for_g"]
    ho_a = {**BASELINE, "bt_a": f"{CONFIRM}/ho_a/bt_a.py"}
    assert K0.baseline_problems({**BASE_RES, "full": ho_a}) == ["as-is group: loads bt_a (ho_a)"]
    assert K0.baseline_problems({**BASE_RES, "never": ["support"]}) == ["as-is group: loads support"]


def fake_probe(seen: dict, base: dict | None = None):
    def run_probe(target, triggers):
        seen[target] = sorted(triggers)
        return dict(base or BASE_RES) if target is None else GOOD
    return run_probe


def test_modules_item_records_the_baseline_and_leaves_out_store_triggers_only_without_the_store():
    seen = {}
    r = K0.modules_item(store=True, run_probe=fake_probe(seen), targets=list(K0.CLI_ENTRIES), workers=2)
    assert r["pass"] is True and r["baseline"] == BASELINE and r["baseline_wide"] == WIDE_BASE and r["problems"] == []
    assert seen[None] == [] and seen["run_g"] == sorted(K0.TRIGGERS) and r["skipped_triggers"] == []
    assert r["counts"] == {"probed": len(K0.CLI_ENTRIES), "baseline": 3, "baseline_wide": len(WIDE_BASE), "problems": 0,
                           "static_problems": 0, "skipped_triggers": 0}
    no_store = K0.modules_item(store=False, run_probe=fake_probe(seen), targets=["k0_g"], workers=1)
    assert no_store["pass"] is False and no_store["skipped_triggers"] == ["prod_trigger"]
    assert "prod_trigger" not in seen["k0_g"]
    assert sum(p.startswith("CLI entry") for p in no_store["problems"]) == len(K0.CLI_ENTRIES) - 1


def test_static_or_baseline_problems_fail_the_modules_item(monkeypatch):
    """F6: a breach the static scan or the as-is probe finds fails the item, not only the per-module probes."""
    targets = list(K0.CLI_ENTRIES)
    bad_base = K0.modules_item(run_probe=fake_probe({}, {**BASE_RES, "never": ["q_common"]}), targets=targets, workers=2)
    assert bad_base["pass"] is False and bad_base["problems"] == ["as-is group: loads q_common"]
    monkeypatch.setattr(K0, "static_problems", lambda: ["syn_g.py: imports support"])
    bad_static = K0.modules_item(run_probe=fake_probe({}), targets=targets, workers=2)
    assert bad_static["pass"] is False and bad_static["problems"] == ["syn_g.py: imports support"]
    assert bad_static["counts"]["static_problems"] == 1 and bad_static["counts"]["problems"] == 0


SYN_MODULES = {
    "k0syn_bad": "import g_common\ng_common.stage0()\nimport support\nimport c_common as C\nUSD_CAP = 140.0\n",
    "k0syn_ok": "import g_common as GC\nimport hog_common\n",
    "k0syn_qset": "import importlib.util as u\nspec = u.spec_from_file_location('k0syn_qset_guard', {qset!r})\n"
                  "m = u.module_from_spec(spec)\nspec.loader.exec_module(m)\nimport sys\nsys.modules[spec.name] = m\n",
    "k0syn_a": "import importlib.util as u\nspec = u.spec_from_file_location('k0syn_a_report', {a!r})\n"
               "m = u.module_from_spec(spec)\nspec.loader.exec_module(m)\nimport sys\nsys.modules[spec.name] = m\n",
    "k0syn_ho": "import sys\nsys.path.insert(0, {ho!r})\nimport banned\n",
    "k0syn_hoa": "import types\nH = types.ModuleType('hoa_common')\n",
    "k0syn_gc": "import sys\nsys.path.insert(0, {gc_dir!r})\nimport g_common as GC\n",
}


@pytest.fixture(scope="module")
def syn_probes(tmp_path_factory):
    """The probe end to end on synthetic modules in a tmp folder (put after this experiment's folder on sys.path)."""
    tmp = tmp_path_factory.mktemp("k0syn")
    gc_dir = tmp / "gc_copy"
    gc_dir.mkdir()
    (gc_dir / "g_common.py").write_text("USD_CAP = 50.0\n", encoding="utf-8")
    fill = {"qset": str(K0.QSET_DIR / "bt_guard.py"), "a": str(GC.REPO / A_EXTRA), "ho": str(K0.HO_DIR / "ho_tools"),
            "gc_dir": str(gc_dir)}
    for name, src in SYN_MODULES.items():
        (tmp / f"{name}.py").write_text(src.format(**fill), encoding="utf-8")
    base = K0.probe(None, {})
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = dict(zip(SYN_MODULES, ex.map(lambda n: K0.probe(n, {}, extra_path=[tmp]), SYN_MODULES)))
    return SimpleNamespace(base=base, res=res, problems={n: K0.module_problems(n, r, base["full"], K0.outside(
        base["wide"])) for n, r in res.items()})


def test_a_probe_catches_a_module_loading_an_a_module_or_binding_its_constants(syn_probes):
    assert syn_probes.problems["k0syn_bad"] == [
        "k0syn_bad: loads support", "k0syn_bad alone: loads support (A/confirm)", "k0syn_bad: loads support (A/confirm)",
        "k0syn_bad.C: binds c_common", "k0syn_bad.USD_CAP: differs from g_common's"]
    assert syn_probes.problems["k0syn_ok"] == []


def test_a_probe_catches_a_qset_or_an_a_module_loaded_by_path_under_another_name(syn_probes):
    assert syn_probes.problems["k0syn_qset"] == ["k0syn_qset alone: loads k0syn_qset_guard (regnal_qset)",
                                                 "k0syn_qset: loads k0syn_qset_guard (regnal_qset)"]
    assert syn_probes.problems["k0syn_a"] == ["k0syn_a alone: loads k0syn_a_report (kg_cards)",
                                              "k0syn_a: loads k0syn_a_report (kg_cards)"]


def test_a_probe_catches_hos_banned_by_name_a_hoa_common_binding_and_a_g_common_copy(syn_probes):
    assert syn_probes.problems["k0syn_ho"] == ["k0syn_ho: loads HO module banned"]
    assert syn_probes.problems["k0syn_hoa"] == ["k0syn_hoa.H: binds hoa_common"]
    assert "k0syn_gc.GC: a g_common other than this folder's" in syn_probes.problems["k0syn_gc"]


def test_the_as_is_group_loads_bt_guard_under_its_alias_and_a_run_both_ho_originals(syn_probes):
    assert syn_probes.base["ho"] == {"ho_bt_guard_for_g": HO["ho_bt_guard_for_g"]}
    assert K0.baseline_problems(syn_probes.base) == []
    assert K0.probe("banned_g", {"cue_literals": K0.TRIGGERS["cue_literals"]})["ho"] == HO


# ---------------------------------------------------------------- §3.9 (3), static
SYN_SOURCE = """\
import c_common
import cards_common
from analyze_c import wrong_rate, k3
from support import seg_cross
from . import engine
import importlib
importlib.import_module("q_common")
X, cc = S.x_common, None
a = X.OUT_ROOT
b = X.TEXT
c = S.x_common.USD_CAP
import x_common as Y
d = Y.OPTIONS
import items_x
"""


def test_the_static_scan_flags_foreign_imports_and_constants_read_through_x_common(tmp_path):
    src = tmp_path / "syn_g.py"
    src.write_text(SYN_SOURCE, encoding="utf-8")
    got = K0.source_problems(src, K0.foreign_modules(), K0.static_consts())
    name = K0.rel(src)
    assert sorted(got) == sorted(f"{name}: {p}" for p in (
        "imports c_common", "imports analyze_c.k3", "imports support.seg_cross", "imports q_common by name",
        "reads OUT_ROOT through x_common", "reads USD_CAP through x_common", "reads OPTIONS through x_common",
        "imports x_common", "imports items_x"))
    assert all(hasattr(GC, v) for v in K0.X_REPLACED.values())


def test_the_static_scan_passes_on_this_experiment():
    assert K0.static_problems() == []
    foreign = K0.foreign_modules()
    assert {"c_common", "hoa_common", "q_common", "segments", "support", "items_c", "x_common", "bt_guard"} <= set(foreign)


def test_the_command_line_takes_check_or_run_only():
    with pytest.raises(SystemExit):
        K0.main(["probe"])


# ---------------------------------------------------------------- §3.9: the sys.modules test itself
def test_sys_modules_of_every_gen_module_match_the_as_is_group():
    """prereg §3.9: the as-is group's modules under A/confirm, ho_a and the qset; every GEN module (found at run time),
    then every lazy import, then the as-is group: exactly those modules with the same files (kg_cards and stage-0
    too); the constants objects."""
    r = K0.modules_item(store=STORE_OK)
    assert r["problems"] == []
    assert r["baseline"] == BASELINE and r["probed"] == K0.gen_modules()
    assert set(K0.BASELINE_WIDE_HAS) <= set(r["baseline_wide"]) and r["counts"]["baseline_wide"] == len(r["baseline_wide"])
    assert {K0.folder_of(f) for f in r["baseline_wide"].values()} == set(K0.WIDE)
    assert set(K0.CLI_ENTRIES) <= set(r["probed"]) and {"gencard", "gencard.trigger", "k0_g"} <= set(r["probed"])
    assert r["skipped_triggers"] == ([] if STORE_OK else ["prod_trigger"])
    assert all(HEX64.fullmatch(v or "") for v in r["baseline_sha256"].values())


# ---------------------------------------------------------------- store: pins and the real check
@needs_store
def test_frozen_pins_of_a_stage0_and_the_store_hold_now():
    """§4.5: A's frozen pins (c_common.frozen_mismatches, read only), stage-0's input pins, the layer, pool.json and
    the r4 layer; the metric version constant (its probe is test_gen_confirm_run's)."""
    X = GC.stage0().x_common
    assert X.c_common.frozen_mismatches() == [] and X.check_pins() == []
    assert GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX)
    assert GC.sha256_file(GC.POOL) == GC.POOL_SHA256 and GC.sha256_file(GC.R4_LAYER) == GC.R4_LAYER_SHA256
    assert GC.METRIC_VERSION == "4d0826bb8d14"


F0_FILES = ("g_common.py", "pool_g.py", "power_g.py", "order_g.py", "test_gen_confirm_core.py")
F0_ENTRY = re.compile(r"^### 2026-10-21 F0\b.*?(?=^### |\Z)", re.M | re.S)
LOGGED_SHA = re.compile(r"`([\w.]+\.py)`：`([0-9a-f]{64})`")


def f0_logged(log: str) -> dict[str, str]:
    """{file: sha256} the log's F0 entry names (a later entry naming its own files is not F0's)."""
    m = F0_ENTRY.search(log)
    return dict(LOGGED_SHA.findall(m.group(0))) if m else {}


def test_only_the_f0_entry_names_the_f0_files():
    """F8: a later entry in the same `name.py`：`sha` form (K0's files, F1a's mech_g) leaves the F0 list as it is."""
    log = (f"\n### 2026-10-21 F0 (syn)\n- `pool_g.py`：`{'1' * 64}`\n- `order_g.py`：`{'2' * 64}`\n"
           f"\n### 2026-10-22 K0 (syn)\n- `k0_g.py`：`{'3' * 64}`\n- `pool_g.py`：`{'4' * 64}`\n")
    assert f0_logged(log) == {"pool_g.py": "1" * 64, "order_g.py": "2" * 64}
    assert f0_logged("\n### 2026-10-22 K0 (syn)\n") == {}


def test_f0_files_are_the_logged_ones():
    """The F0 entry of the 執行紀錄: the prereg text above the log and pool_g, power_g, order_g and the core test as
    logged (g_common only gains names after F0; test_gen_confirm_core pins its F0 values)."""
    log = F1.log_text(H / "prereg.md")
    logged = f0_logged(log)
    assert sorted(logged) == sorted(F0_FILES)
    now = {n: GC.sha256_file((Path(__file__).parent if n.startswith("test_") else H) / n) for n in logged}
    assert {n: now[n] == logged[n] for n in logged if n != "g_common.py"} == dict.fromkeys(
        ("pool_g.py", "power_g.py", "order_g.py", "test_gen_confirm_core.py"), True)
    above = re.search(r"「執行紀錄」以上文字的 sha256：`([0-9a-f]{64})`", log)
    assert above and F1.harness_files_sha256()["prereg.md"] == above.group(1)


@needs_store
def test_k0_check_passes_on_the_real_store():
    """k0_g.check() on the real store (never run): every item passes, only counts and names are printed, and every
    file below the store's out root is as it was (k0.json and the harness record may exist: a later suite runs this)."""
    before = K0.store_snapshot(GC.OUT_ROOT)
    lines = []
    rc = K0.check(log=lines.append)
    assert rc == 0, lines[-1]
    assert not [x for x in lines if CJK.search(str(x))]
    assert K0.changed_paths(before, K0.store_snapshot(GC.OUT_ROOT)) == []


# ---------------------------------------------------------------- the K0 gate of every USD command (§8.1-1)
class Reached(Exception):
    """The command got past the K0 gate to its first step."""


def _reached(*_a, **_k):
    raise Reached


USD_COMMANDS = [(PR, "probe", ["run", "--version", "2.1.302"]), (RQ, "context", ["gen", "--set", "p1"]),
                (RQ, "context", ["refill", "--set", "p2"]), (RH, "pilot", ["pilot"]), (RH, "main_phase", ["main"]),
                (RH, "kay_work", ["kay"])]
CPU_COMMANDS = [(PR, "pin_from", ["pin", "--verdict", "v.json"]), (RQ, "context", ["score", "--set", "p1"]),
                (RQ, "cmd_status", ["status"]), (RH, "kp", ["kp"]), (RH, "status", ["status"])]


@pytest.mark.parametrize("mod, first, argv", USD_COMMANDS, ids=lambda x: getattr(x, "__name__", str(x)))
def test_every_usd_command_refuses_before_a_passing_k0_and_starts_after_it(monkeypatch, mod, first, argv):
    monkeypatch.setattr(mod, first, _reached)
    monkeypatch.setattr(K0, "k0_problems", lambda: ["k0.json missing: K0 has not passed"])
    with pytest.raises(HG.HoError, match="K0 first"):
        mod.main(argv)
    monkeypatch.setattr(K0, "k0_problems", lambda: [])
    with pytest.raises(Reached):
        mod.main(argv)


@pytest.mark.parametrize("mod, first, argv", CPU_COMMANDS, ids=lambda x: getattr(x, "__name__", str(x)))
def test_the_cpu_commands_do_not_need_k0(monkeypatch, mod, first, argv):
    monkeypatch.setattr(mod, first, _reached)
    monkeypatch.setattr(K0, "k0_problems", lambda: ["k0.json missing: K0 has not passed"])
    with pytest.raises(Reached):
        mod.main(argv)


def test_the_gate_is_k0_problems_and_it_refuses_without_a_k0(tmp_path):
    hr = tmp_path / "harness_record.json"
    assert K0.k0_problems(k0=tmp_path / "k0.json", harness_record=hr) == ["k0.json missing: K0 has not passed"]
