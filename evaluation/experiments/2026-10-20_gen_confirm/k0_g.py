"""K0-合成 of the GEN confirmation set (prereg §8.1-1, §3.3, §3.9, §5.3): every CPU check before any USD is spent.

    python -B k0_g.py check   # recompute every item, print counts and booleans only, write nothing; exit 0 iff all pass
    python -B k0_g.py run     # at the K0 commit only (f1_g.git_problems() empty): recompute every item; when every
                              # item passes, the K0 harness record (f1_g.record_k0: the test_gen_confirm_* suite
                              # passes and leaves the store as it was), then store k0.json once; prints both sha256

Items (the sections of k0.json, in this order; each has "pass" and "counts"):
  pool          K0-gold 58/58, K0-lines 96/96, K0-card 58/58 and the largest G block (338 characters, cap 900):
                pool_g.build() (F0; imported, never edited) recomputed in memory on the real store, compared with store
                pool.json's summary and with the values §2.1 registered; the rebuild must be pool.json byte for byte
                (POOL_SHA256). Counts that differ are reported, never adjusted. K0-gold or K0-lines below its total is
                a K-gold candidate only: §3.6 and §8.1-1 stop on a failure a CPU trace puts on the layer, so k0_g
                never prints the stop sentence itself.
  TEST_ITEMS    one pytest selection per remaining line of §8.1-1 (gencard ≡ engine_x, the §5.3 nails, mech_g's bank
                with the §3.4 nails, §3.3's transcript and prompt checks, the frozen-file pins and metric_version,
                g_common and the ledger, the per-group sys.modules tests), each in a fresh interpreter as stage-0's
                run_x.k0_tests: the outcome counts, the failing test names (no parameter, no message) and the sha256
                of the test files run. A selection passes only with passed > 0 and no failed, error, skipped, xfailed
                or xpassed test (K0 needs the store mounted); deselected tests beside passing ones are fine. Every
                test_gen_confirm_*.py is in some selection or in EXCLUDED_TESTS (with its reason; the harness
                record's suite runs it).
  modules       §3.9's sys.modules test (``modules_item``):
                (1) the as-is group alone in a fresh interpreter (hog_common.bt_guard(); stage-0's gen_layer, items_x,
                    engine_x and keys_x through g_common.stage0(); A's cards_common; analyze_c's wrong_rate and
                    calls_of) and its modules under A/confirm, ho_a and 2026-10-19_regnal_qset (name -> file): the
                    baseline, kept in k0.json; beside it the as-is group's modules elsewhere under kg_cards and in
                    stage-0's folder (``baseline_wide``);
                (2) every GEN module (every .py here and in gencard/, found at run time, so a new module such as
                    smoke_g is covered; every CLI entry must be among them) first in its own fresh interpreter, then
                    every lazy import a run makes (TRIGGERS; nothing is launched, the store only read), then the
                    as-is group: what the module loads alone lies inside the baseline, and at the end the modules
                    under the three folders are the baseline exactly, with the same files (and so for kg_cards and
                    stage-0 against baseline_wide); hoa_common, q_common, segments, support and items_c are never
                    loaded, nor an HO module other than the two loaded by path under their aliases;
                (3) every GEN module's constants object is g_common: a bound g_common is this folder's; c_common,
                    hoa_common and q_common are never bound; stage-0's x_common only where X_COMMON_ALLOWED says; a
                    constant g_common defines has g_common's value; and no source reads through x_common a g_common
                    constant or one g_common replaces (X_REPLACED: OPTIONS), or imports a module of A, the qset, HO or stage-0 by name (``static_problems``).
Writing nothing is checked, not promised: each item runs between two snapshots of the store's out root (every file
below it, path -> sha256), and a file added, changed or removed fails that item (the harness record's suite too).
k0.json (schema gen_confirm.k0.v1): t, git_head, harness_sha256 (f1_g.harness_pins()["sha256"]), pass, the items
and failed_attempts; counts, booleans, sha256 and module, file and test names only, never question, card or verse
text. It is written once, only for a K0 that passed with its harness record. A failed K0 (an item, or a refused
harness record) is kept as k0_attempts/<n>.json and K0 is run again after the fix (§8.1-1 「任何失敗都要修好」).
``k0_problems`` is the gate every USD command calls first (probe_g run, run_qg gen/refill, run_ho_g pilot/main/kay;
empty = K0 passed and the harness is still its record's). Nothing here
calls an LLM or Ollama; only k0.json (once), k0_attempts/ and, through f1_g, harness_record.json are ever written.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import f1_g as F1
import g_common as GC
import pool_g

SCHEMA = "gen_confirm.k0.v1"
K0_FILE = GC.K0_FILE
K0_ATTEMPTS = GC.K0_ATTEMPTS
TESTS = "evaluation/tests"
K0_TESTS = f"{TESTS}/test_gen_confirm_k0.py"
SELF_TESTS = ("test_k0_check_passes_on_the_real_store",)       # calls check(): never inside a selection
CAP_CHARS = 900
REGISTERED = {"k0_gold": [58, 58], "k0_lines": [96, 96], "k0_card": [58, 58], "max_chars_g": 338}   # §2.1
LAYER_CHECKS = ("k0_gold", "k0_lines")              # the layer against the independent verse reader (K-gold)
TEST_TIMEOUT, PROBE_TIMEOUT, PROBE_WORKERS = 3600, 600, 8
OUTCOMES = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed", "deselected")
BAD_OUTCOMES = ("failed", "errors", "skipped", "xfailed", "xpassed")
SUMMARY = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
SIBLING = re.compile(r"^(?:from|import) (test_gen_confirm_\w+)", re.M)

EXP = GC.REPO / "evaluation/experiments"
KG = EXP / "2026-10-18_kg_cards"
HO_DIR = EXP / "2026-10-14_graph_gd"
QSET_DIR = EXP / "2026-10-19_regnal_qset"
DIRS = {"A/confirm": KG / "A/confirm", "ho_a": KG / "A/confirm/ho_a", "regnal_qset": QSET_DIR}
WIDE = {"kg_cards": KG, "stage-0": GC.STAGE0_DIR}     # the rest of what the as-is group loads (HO: the "ho" snapshot)
FOREIGN_DIRS = (KG, KG / "A", KG / "A/confirm", KG / "A/confirm/ho_a", QSET_DIR, GC.STAGE0_DIR, HO_DIR / "ho_tools")
# HO's originals, loaded by path after their sha256 check under these aliases (hog_common.bt_guard, banned_g)
HO_ALIASES = {"ho_bt_guard_for_g": "evaluation/experiments/2026-10-14_graph_gd/ho_tools/bt_guard.py",
              "ho_banned_for_g": "evaluation/experiments/2026-10-14_graph_gd/ho_tools/banned.py"}
NEVER = ("hoa_common", "q_common", "segments", "support", "items_c")
BASELINE_HAS = ("analyze_c", "c_common", "guards_c")  # §3.9: A's c_common through x_common, guards_c through analyze_c
BASELINE_WIDE_HAS = ("cards_common", "x_common", "gen_layer", "items_x", "engine_x", "keys_x")   # the as-is imports
BASELINE_HO = ("ho_bt_guard_for_g",)                 # bt_guard, loaded by path by the as-is group
CONSTANTS_FAMILY = ("g_common", "c_common", "x_common", "hoa_common", "q_common")
FORBIDDEN_BINDS = ("c_common", "hoa_common", "q_common")
# run_g calls stage-0's functions through X: its frozen pins (check_pins, harness_files_sha256), its jsonl reader and
# A's c_common.frozen_mismatches (§4.5); no constant (static_problems)
X_COMMON_ALLOWED = {"run_g": ("X",)}
# x_common constants g_common replaces under another name: never read through x_common (static_problems)
X_REPLACED = {"OPTIONS": "OLLAMA_OPTIONS"}
ALLOWED_IMPORT = ("cards_common",)                    # the as-is imports by name (stage-0's go through g_common.stage0())
ALLOWED_FROM = {"analyze_c": ("calls_of", "wrong_rate"), "cards_common": None}
CLI_ENTRIES = ("run_g", "run_ho_g", "run_qg", "spec_qg", "f1a_g", "probe_g", "kay_g", "freeze_g", "f2_g", "k0_g")
# the test files in no §8.1-1 selection: the harness record's suite runs them (f1_g.suite_problems)
EXCLUDED_TESTS = {
    "analyze": "§1.3, §9: the verdict and its sensitivities, used after the run",
    "qset_run": "§5.4, §8.1-3..5: the P1/P2 runner (its prompt checks are blinding_3_3's qset selection)",
    "smoke": "§4.4, §8.1-11: F3's smoke and its void record",
}

AS_IS = """
import importlib, sys
import g_common, hog_common
hog_common.bt_guard()
S = g_common.stage0()
if importlib.import_module("cards_common") is not S.x_common.cc:
    raise ImportError("cards_common is not the one x_common imports")
ev = str(g_common.REPO / "evaluation")
if ev not in sys.path:
    sys.path.insert(0, ev)
from analyze_c import calls_of, wrong_rate
"""
# every import a run makes after start-up; nothing launches and the store is only read (prod_trigger: the r4 layer)
TRIGGERS = {
    "bt_guard": "import hog_common; hog_common.bt_guard()",
    "stage0": "import g_common; g_common.stage0()",
    "cue_literals": "import banned_g; banned_g.cue_literals()",
    "trigger_words": "import mech_g; mech_g.trigger_words()",
    "qset_cue_literals": "import prompt_qg; prompt_qg.cue_literals()",
    "probe_prompts": "import probe_g; probe_g.plan(); probe_g.check_prompts()",
    "transcript": "import transcript_g; transcript_g.check_events([], {}, 'm', 'bt')",
    "lazy_imports": "import analyze_g, gencard, names_g, power_g",    # imported inside spec_qg, f2_g and run_qg
    # freeze_g reads the F1 manifest's prod items (f1_g.prod_pins(): backend_pins() and trigger_pins()); before F1,
    # the same items computed now
    "prod_trigger": "import f1_g, freeze_g, g_common; "
                    "freeze_g.prod_trigger(getattr(f1_g, 'prod_pins', g_common.backend_pins)())",
}
STORE_TRIGGERS = ("prod_trigger",)
PROBE_TAG = "K0PROBE "
PROBE = r'''
import importlib, json, sys, types
from pathlib import Path

cfg = json.loads(sys.argv[1])
here, repo = Path(cfg["here"]), Path(cfg["repo"])
if sys.path and sys.path[0] in ("", "."):
    sys.path[0] = str(here)                          # as `python -B <module>.py` started in this folder
else:
    sys.path.insert(0, str(here))
sys.path[1:1] = cfg.get("extra_path", [])            # tests only: a folder with a synthetic module


def file_of(m):
    f = getattr(m, "__file__", None)
    return Path(f).resolve() if f else None


def rel(p):
    try:
        return p.relative_to(repo).as_posix()
    except ValueError:
        return str(p)


def snap(roots):
    roots = [Path(d).resolve() for d in roots]
    out = {}
    for n, m in list(sys.modules.items()):
        p = file_of(m)
        if p is not None and any(p == d or d in p.parents for d in roots):
            out[n] = rel(p)
    return dict(sorted(out.items()))


def attempt(code):
    try:
        exec(code, {"__name__": "k0_probe"})
    except BaseException as err:                     # a refusal is SystemExit; only the class is reported
        return type(err).__name__
    return None


def constants(mod):
    gc = sys.modules.get("g_common")
    gc_ok = gc is not None and file_of(gc) == (here / "g_common.py").resolve()
    binds, values = {}, []
    for n, o in sorted(vars(mod).items()):
        if isinstance(o, types.ModuleType):
            p = file_of(o)
            stem = p.stem if p is not None else o.__name__.rpartition(".")[2]
            if stem in cfg["family"]:
                binds[n] = {"stem": stem, "file": rel(p) if p else None, "is_g_common": o is gc and gc_ok}
    for k in cfg["gc_names"] if gc is not None and mod is not gc else ():
        if k in vars(mod):
            try:
                same = vars(mod)[k] is getattr(gc, k, None) or bool(vars(mod)[k] == getattr(gc, k, None))
            except Exception:                        # an incomparable value is not g_common's
                same = False
            values += [] if same else [k]
    return {"binds": binds, "values": values}


out, target = {}, cfg["target"]
if target:
    out["import_error"] = attempt("import importlib; importlib.import_module(" + repr(target) + ")")
    out["own"] = snap(cfg["dirs"])
    out["own_wide"] = snap(cfg["wide"])
    out["trigger_errors"] = {k: e for k, c in cfg["triggers"].items() for e in [attempt(c)] if e}
out["as_is_error"] = attempt(cfg["as_is"])
out["full"] = snap(cfg["dirs"])
out["wide"] = snap(cfg["wide"])
out["never"] = sorted(n for n in cfg["never"] if n in sys.modules)
out["ho"] = snap([cfg["ho_dir"]])
if target and target in sys.modules:
    out["constants"] = constants(sys.modules[target])
print("K0PROBE " + json.dumps(out))
'''


def _nodes(file: str, *tests: str) -> tuple[str, ...]:
    return tuple(f"{TESTS}/test_gen_confirm_{file}.py::{t}" for t in tests)


def _files(*files: str) -> tuple[str, ...]:
    return tuple(f"{TESTS}/test_gen_confirm_{f}.py" for f in files)


ENGINE_EQ = _nodes("gencard", "test_real_cards_equal_stage0s_engine_x_on_all_64_same_chapter_pairs",
                   "test_engine_is_a_verbatim_copy_of_engine_xs_genesis_functions",
                   "test_card_for_seeds_is_engine_xs_genesis_branch")
TEST_ITEMS = (                                        # (k0.json section, prereg section, pytest arguments)
    ("gencard_engine_x", "§5.1", ENGINE_EQ),
    ("nails_5_3", "§5.3", _files("gencard", "names")),    # the whole §5.1–§5.3 file (ENGINE_EQ runs again: harmless)
    ("mech_bank", "§3.4", _files("mech")),
    ("blinding_3_3", "§3.3", (
        *_files("prompts"),
        *_nodes("infra", "test_k0_compliant_transcripts_pass_every_blinding_rule_in_both_modes",
                "test_k0_a_leaking_transcript_fails", "test_tool_rules_per_mode", "test_path_rule", "test_init_rules",
                "test_scope_rule_of_prompt_parts", "test_cue_words_in_agent_output_are_never_checked",
                "test_probe_prompts_pass_the_full_check_with_the_real_cue_words"),
        *_nodes("qset", "test_every_rendered_prompt_passes_the_prompt_scope_and_holds_no_cue_word",
                "test_positive_blocks_are_the_ho_writers_definition_and_naming",
                "test_a_banned_term_or_cue_word_refuses_the_render", "test_store_prompts_all_pass_without_printing"),
        *_nodes("integration", "test_every_file_of_this_folder_is_a_memory_marker",
                "test_each_new_marker_is_caught_in_a_transcript", "test_a_marker_never_hits_a_longer_name_that_contains_it",
                "test_no_marker_hits_a_compliant_transcript_the_bt_tool_the_probe_or_the_prompt_files",
                "test_no_marker_hits_a_rendered_ho_prompt", "test_no_marker_hits_a_rendered_qset_prompt",
                "test_no_marker_hits_a_store_rendered_qset_or_ho_prompt"))),
    ("pins", "§4.5", (
        *_nodes("gates", "test_stage0_problems_and_metric_version_hold_now",
                "test_stage0_problems_name_a_failing_pin_and_a_changed_harness",
                "test_pin_problems_pass_and_name_each_broken_pin"),
        *_nodes("core", "test_pool_is_the_registered_pool", "test_tables_were_made_by_this_power_g",
                "test_backend_pins_cover_the_parity_and_trigger_files"),
        *_nodes("infra", "test_guard_is_hos_original_by_sha_and_loaded_by_path",
                "test_inf11_bt_guard_refuses_a_changed_file", "test_bt_g_pins_equal_bt_a_and_it_imports_no_c_common"),
        *_nodes("prompts", "test_pinned_sources_refuse_a_changed_file"),
        *_nodes("ho", "test_prod_dynasty_trigger_loads_by_path_after_the_pins"),
        *_nodes("ho_edges", "test_prod_trigger_pins_the_routing_files_and_lexicon_it_loads"),
        *_nodes("integration", "test_g_common_is_one_of_f1s_own_files",
                "test_trigger_pins_have_the_shape_of_backend_pins_and_the_kept_values",
                "test_the_f1_manifest_holds_the_trigger_pins_and_g_common",
                "test_the_ho_runner_checks_the_trigger_pins_and_g_common_against_the_manifest",
                "test_f2_frozen_group_is_exactly_the_cards_files_of_the_f1a_group_by_key",
                "test_the_tool_files_are_the_ho_and_qset_runners_and_their_prompts"),
        *_nodes("k0", "test_frozen_pins_of_a_stage0_and_the_store_hold_now", "test_f0_files_are_the_logged_ones"))),
    ("g_common_ledger", "§3.9", (
        *_files("core"),
        *_nodes("integration", "test_every_alias_is_the_g_common_object",
                "test_no_gen_module_builds_its_own_amount_path_or_file_constant",
                "test_the_constant_scan_catches_each_kind", "test_the_batch_3_values"),
        *_nodes("infra", "test_a_run_counts_its_result_else_its_reserved_cap",
                "test_every_root_of_every_kind_counts_and_other_folders_do_not", "test_refusal_at_49_usd",
                "test_probe_sub_caps_money_and_invocations", "test_qset_sub_cap", "test_a_job_cap_must_fit_its_kind",
                "test_run_ids_and_release", "test_two_processes_contending_never_overrun_the_cap",
                "test_threads_contending_never_overrun_the_cap", "test_ledger_defaults_are_the_prereg_values",
                "test_inf4_any_failure_before_the_start_releases_the_reservation",
                "test_inf4_a_started_run_keeps_its_reservation_when_the_launcher_dies",
                "test_inf5_concurrent_snapshots_never_collide",
                "test_inf6_reserve_waits_for_another_process_holding_the_ledger_flock",
                "test_inf11_the_ledger_counts_the_last_result_and_a_prompts_only_run",
                "test_run_reserved_releases_the_reservation_when_refused_before_start"))),
    ("modules_tests", "§3.9", (
        *_nodes("run", "test_runners_load_only_the_allowed_modules_of_a_and_none_of_ho_or_qset"),
        *_nodes("ho", "test_runners_load_only_the_allowed_modules"),
        *_nodes("infra", "test_no_module_of_a_ho_a_or_the_qset_is_loaded",
                "test_no_module_of_a_ho_a_or_the_qset_is_loaded_with_the_real_cue_words"),
        *_nodes("qset", "test_the_qset_tools_load_only_the_allowed_modules_of_a_and_none_of_ho_or_qset"),
        *_nodes("prompts", "test_a_lists_equal_banned_a_at_run_time_and_no_ho_a_module_is_loaded"),
        *_nodes("core", "test_g_common_imports_neither_a_nor_stage0_constants"),
        *_nodes("names", "test_names_g_imports_neither_a_nor_stage0"))),
)
ITEM_ORDER = ("pool", *(k for k, _r, _s in TEST_ITEMS), "modules")


def rel(p: Path | str, root: Path = GC.REPO) -> str:
    p = Path(p).resolve()
    for r in (Path(root).resolve(), GC.STORE.resolve()):
        if p == r or r in p.parents:
            return p.relative_to(r).as_posix()
    return str(p)


def sha_or_none(p: Path) -> str | None:
    return GC.sha256_file(p) if Path(p).is_file() else None


def gc_names() -> list[str]:
    """g_common's constant names (upper case; the names appended after F0 included)."""
    return sorted(n for n in vars(GC) if n.isupper())


# ---------------------------------------------------------------- writing nothing: the store before and after
def store_snapshot(root: Path = GC.OUT_ROOT) -> dict[str, str]:
    """{path relative to ``root``: sha256} of every file below it (empty when it does not exist)."""
    root = Path(root)
    if not root.is_dir():
        return {}
    return {p.relative_to(root).as_posix(): GC.sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def changed_paths(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    """The paths added, changed or removed between two snapshots."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def watched(compute: Callable[[], dict], watch: Path) -> dict:
    """One item computed between two snapshots of ``watch``: a file it adds, changes or removes fails it."""
    before = store_snapshot(watch)
    item = compute()
    changed = changed_paths(before, store_snapshot(watch))
    return {**item, "pass": False, "store_changed": changed} if changed else item


# ---------------------------------------------------------------- pool: K0-gold, K0-lines, K0-card (§2.1)
def frac(s: str) -> list[int]:
    ok, n = str(s).split("/")
    return [int(ok), int(n)]


def pool_counts(summary: Mapping[str, Any]) -> dict:
    return {**{k: frac(summary[k]) for k in ("k0_gold", "k0_lines", "k0_card")},
            "max_chars_g": int(summary["max_chars_g"])}


def pool_item(build: Callable[[], dict] = pool_g.build, pool_file: Path = GC.POOL) -> dict:
    """pool_g's K0 recomputed in memory against store pool.json and §2.1's registered values (never adjusted)."""
    files = {rel(GC.HERE / "pool_g.py"): sha_or_none(GC.HERE / "pool_g.py"),
             rel(pool_file): sha_or_none(pool_file), rel(GC.GEN_LAYER): sha_or_none(GC.GEN_LAYER)}
    try:
        doc = build()
    except (SystemExit, OSError):                     # a gen_layer.json that is not stage-0's (§2), or no store
        return {"pass": False, "counts": {}, "built": False, "k_gold_candidate": False, "files_sha256": files}
    stored = GC.read_json(pool_file) if Path(pool_file).is_file() else None
    counts = pool_counts(doc["summary"])
    recorded = pool_counts(stored["summary"]) if stored else None
    rebuild = GC.sha256_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    checks = {"same_as_recorded": counts == recorded, "same_as_registered": counts == REGISTERED,
              "k0_problems_none": not pool_g.k0_problems(doc), "rebuild_is_pool_json": rebuild == GC.POOL_SHA256,
              "pool_json_pinned": files[rel(pool_file)] == GC.POOL_SHA256}
    return {"pass": all(checks.values()), "counts": {**counts, "cap_chars": CAP_CHARS}, "recorded": recorded,
            "registered": REGISTERED, **checks, "built": True,
            "k_gold_candidate": any(ok != n for ok, n in (counts[k] for k in LAYER_CHECKS)),
            "rebuild_sha256": rebuild, "files_sha256": files}


def k_gold_value(pool: Mapping[str, Any]) -> str:
    """The layer checks below their totals, e.g. K0-lines 95/96 (§9's 〈值〉 once a CPU trace puts it on the layer)."""
    c = pool.get("counts") or {}
    return "、".join(f"K0-{k.split('_')[1]} {c[k][0]}/{c[k][1]}" for k in LAYER_CHECKS if k in c and c[k][0] != c[k][1])


# ---------------------------------------------------------------- the pytest selections (stage-0's run_x.k0_tests)
def parse_summary(line: str) -> dict[str, int]:
    """Outcome counts of pytest's last line ("3 passed, 1 deselected in 0.1s"; "no tests ran" gives zeros)."""
    out = dict.fromkeys(OUTCOMES, 0)
    for n, k in SUMMARY.findall(line):
        out["errors" if k.startswith("error") else k] += int(n)
    return out


def failed_tests(lines: Sequence[str]) -> list[str]:
    """The test names of pytest's FAILED and ERROR lines (-rfE), without parameter or message."""
    return sorted({ln.split()[1].split("[")[0] for ln in lines if ln.startswith(("FAILED ", "ERROR ")) and
                   len(ln.split()) > 1})


def pytest_selection(selection: Sequence[str], repo: Path = GC.REPO) -> dict:
    """One selection in a fresh interpreter, PYTHONPATH dropped as in ``probe``; its output is never printed (only
    counts and test names are kept)."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *selection],
                           cwd=repo, env=env, capture_output=True, text=True, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"returncode": None, "counts": dict.fromkeys(OUTCOMES, 0), "failed_tests": ["timeout"]}
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return {"returncode": r.returncode, "counts": parse_summary(lines[-1] if lines else ""),
            "failed_tests": failed_tests(lines)}


def selection_files(selection: Sequence[str], repo: Path = GC.REPO) -> list[str]:
    """The test files a selection runs, the sibling test modules they import, and conftest.py."""
    todo = [a.split("::", 1)[0] for a in selection if not a.startswith("-")]
    seen: set[str] = set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        p = Path(repo) / f
        todo += [f"{TESTS}/{m}.py" for m in SIBLING.findall(p.read_text(encoding="utf-8"))] if p.is_file() else []
    conftest = f"{TESTS}/conftest.py"
    return sorted(seen | ({conftest} if (Path(repo) / conftest).is_file() else set()))


def self_selected(selection: Sequence[str]) -> bool:
    """A selection that would run this file's store check (check() inside check(): no end)."""
    return any(a == K0_TESTS or (a.startswith(K0_TESTS + "::") and a.split("::")[1].split("[")[0] in SELF_TESTS)
               for a in selection)


def selection_item(ref: str, selection: Sequence[str], run: Callable[[Sequence[str]], dict] = pytest_selection) -> dict:
    files = {f: sha_or_none(GC.REPO / f) for f in selection_files(selection)}
    if self_selected(selection):
        return {"pass": False, "prereg": ref, "selection": list(selection), "counts": dict.fromkeys(OUTCOMES, 0),
                "returncode": None, "failed_tests": [], "self_selected": True, "files_sha256": files}
    res = run(selection)
    c = {k: int(res["counts"].get(k, 0)) for k in OUTCOMES}
    ok = res["returncode"] == 0 and c["passed"] > 0 and not any(c[k] for k in BAD_OUTCOMES)
    return {"pass": ok and all(files.values()), "prereg": ref, "selection": list(selection), "counts": c,
            "returncode": res["returncode"], "failed_tests": list(res.get("failed_tests") or ()),
            "files_sha256": files}


# ---------------------------------------------------------------- §3.9: the sys.modules test
def gen_modules(here: Path = GC.HERE) -> list[str]:
    """Every module of this experiment: each .py here, the gencard package and each of its modules."""
    pkg = sorted(p.stem for p in (Path(here) / "gencard").glob("*.py") if p.stem != "__init__")
    return [p.stem for p in sorted(Path(here).glob("*.py"))] + ["gencard"] + [f"gencard.{s}" for s in pkg]


def probe(target: str | None, triggers: Mapping[str, str], extra_path: Sequence[str] = ()) -> dict:
    """One fresh interpreter (``PROBE``): ``target`` first (None: the as-is group alone), then ``triggers``, then the
    as-is group; module names and files only come back. ``extra_path`` (tests) goes right after this folder."""
    cfg = {"here": str(GC.HERE), "repo": str(GC.REPO), "target": target, "triggers": dict(triggers), "as_is": AS_IS,
           "dirs": [str(d) for d in DIRS.values()], "wide": [str(d) for d in WIDE.values()], "ho_dir": str(HO_DIR),
           "never": list(NEVER), "family": list(CONSTANTS_FAMILY), "gc_names": gc_names(),
           "extra_path": [str(p) for p in extra_path]}
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    try:
        r = subprocess.run([sys.executable, "-B", "-c", PROBE, json.dumps(cfg)], cwd=GC.HERE, env=env,
                           capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"probe_error": "timeout"}
    tagged = [ln for ln in r.stdout.splitlines() if ln.startswith(PROBE_TAG)]
    if r.returncode != 0 or not tagged:
        return {"probe_error": f"exit {r.returncode}"}
    return json.loads(tagged[-1][len(PROBE_TAG):])


def folder_of(file: str) -> str:
    """Which folder a repo-relative file lies in: one of the three (ho_a first: it is inside A/confirm), else the rest
    of kg_cards or stage-0's folder, else elsewhere."""
    p = (GC.REPO / file).resolve()
    for key in ("ho_a", "regnal_qset", "A/confirm"):
        if p.is_relative_to(DIRS[key].resolve()):
            return key
    return next((key for key, d in WIDE.items() if p.is_relative_to(Path(d).resolve())), "elsewhere")


def outside(mods: Mapping[str, str] | None) -> dict[str, str]:
    """The modules of a wide snapshot outside the three folders (those are the baseline's own comparison)."""
    return {n: f for n, f in sorted((mods or {}).items()) if folder_of(f) in WIDE}


def set_problems(label: str, got: Mapping[str, str], base: Mapping[str, str], exact: bool) -> list[str]:
    out = [f"{label}: loads {n} ({folder_of(f)})" for n, f in sorted(got.items()) if n not in base]
    out += [f"{label}: {n} resolves to another file" for n, f in sorted(got.items()) if n in base and base[n] != f]
    return out + ([f"{label}: {n} of the baseline is not loaded" for n in sorted(set(base) - set(got))] if exact else [])


def common_problems(label: str, res: Mapping[str, Any]) -> list[str]:
    """The rules every probe shares: it ran, the as-is group loaded, no NEVER module, HO only under its aliases."""
    if "probe_error" in res:
        return [f"{label}: probe {res['probe_error']}"]
    out = [f"{label}: the as-is group raised {res['as_is_error']}"] if res.get("as_is_error") else []
    out += [f"{label}: loads {n}" for n in res.get("never", [])]
    return out + [f"{label}: loads HO module {n}" for n, f in sorted((res.get("ho") or {}).items())
                  if HO_ALIASES.get(n) != f]


def baseline_problems(res: Mapping[str, Any]) -> list[str]:
    out = common_problems("as-is group", res)
    if "probe_error" in res:
        return out
    full, wide, ho = res.get("full") or {}, outside(res.get("wide")), res.get("ho") or {}
    out += [f"as-is group: lacks {n}" for n in BASELINE_HAS if n not in full]
    out += [f"as-is group: lacks {n}" for n in BASELINE_WIDE_HAS if n not in wide]
    out += [f"as-is group: lacks HO's {n}" for n in BASELINE_HO if ho.get(n) != HO_ALIASES[n]]
    return out + [f"as-is group: loads {n} ({folder_of(f)})" for n, f in sorted(full.items())
                  if folder_of(f) in ("ho_a", "regnal_qset")]


def constants_problems(target: str, c: Mapping[str, Any]) -> list[str]:
    """(3): a bound g_common is this folder's; no c_common, hoa_common or q_common; x_common only where allowed;
    every constant g_common defines has g_common's value."""
    out = []
    for name, b in sorted((c.get("binds") or {}).items()):
        if b["stem"] == "g_common" and not b["is_g_common"]:
            out.append(f"{target}.{name}: a g_common other than this folder's")
        elif b["stem"] in FORBIDDEN_BINDS:
            out.append(f"{target}.{name}: binds {b['stem']}")
        elif b["stem"] == "x_common" and name not in X_COMMON_ALLOWED.get(target, ()):
            out.append(f"{target}.{name}: binds stage-0's x_common")
    return out + [f"{target}.{k}: differs from g_common's" for k in c.get("values", [])]


def module_problems(target: str, res: Mapping[str, Any], baseline: Mapping[str, str],
                    baseline_wide: Mapping[str, str]) -> list[str]:
    out = common_problems(target, res)
    if "probe_error" in res:
        return out
    out += [f"{target}: import raised {res['import_error']}"] if res.get("import_error") else []
    out += [f"{target}: trigger {k} raised {e}" for k, e in sorted((res.get("trigger_errors") or {}).items())]
    out += set_problems(f"{target} alone", res.get("own") or {}, baseline, exact=False)
    out += set_problems(target, res.get("full") or {}, baseline, exact=True)
    out += set_problems(f"{target} alone", outside(res.get("own_wide")), baseline_wide, exact=False)
    out += set_problems(target, outside(res.get("wide")), baseline_wide, exact=True)
    return out + (constants_problems(target, res["constants"]) if "constants" in res else
                  [f"{target}: not in sys.modules after its import"])


# ---------------------------------------------------------------- (3), static: imports and x_common reads
def foreign_modules(here: Path = GC.HERE) -> dict[str, str]:
    """{module name: folder} of every module A (its confirm set and ho_a), the qset, HO's tools and stage-0 define;
    this experiment's own module names are left out (the probes check where they resolve)."""
    own = {p.stem for p in Path(here).glob("*.py")} | {"gencard"}
    out: dict[str, str] = {}
    for d in FOREIGN_DIRS:
        for p in sorted(Path(d).glob("*.py")):
            if p.stem not in own:
                out.setdefault(p.stem, rel(d))
    return out


def _is_x(v: ast.AST) -> bool:
    return isinstance(v, ast.Attribute) and v.attr == "x_common" or isinstance(v, ast.Name) and v.id == "x_common"


def x_names(tree: ast.AST) -> set[str]:
    """Names a source binds to stage-0's x_common (import x_common as N; N = <...>.x_common, a tuple pair too)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.asname or a.name for a in node.names if a.name == "x_common"}
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                tup = isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple)
                pairs = zip(t.elts, node.value.elts) if tup else [(t, node.value)]
                out |= {a.id for a, v in pairs if isinstance(a, ast.Name) and _is_x(v)}
    return out


def _callee(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _import_problems(name: str, node: ast.AST, foreign: Mapping[str, str]) -> list[str]:
    if isinstance(node, ast.Import):
        return [f"{name}: imports {a.name}" for a in node.names
                if a.name.split(".")[0] in foreign and a.name not in ALLOWED_IMPORT]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        top = node.module.split(".")[0]
        allowed = ALLOWED_FROM.get(top, ())
        return [f"{name}: imports {top}.{a.name}" for a in node.names
                if top in foreign and allowed is not None and a.name not in allowed]
    if isinstance(node, ast.Call) and _callee(node) in ("import_module", "__import__") and node.args:
        a = node.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.split(".")[0] in foreign:
            return [f"{name}: imports {a.value} by name"]
    return []


def source_problems(path: Path, foreign: Mapping[str, str], consts: Sequence[str]) -> list[str]:
    name, tree = rel(path), ast.parse(Path(path).read_text(encoding="utf-8"))
    xs, out = x_names(tree), []
    for node in ast.walk(tree):
        out += _import_problems(name, node, foreign)
        if isinstance(node, ast.Attribute) and node.attr in consts and (
                isinstance(node.value, ast.Name) and node.value.id in xs or _is_x(node.value)):
            out.append(f"{name}: reads {node.attr} through x_common")
    return out


def static_consts() -> list[str]:
    """The constants no source may read through x_common: g_common's names and those it replaces (X_REPLACED)."""
    return sorted(set(gc_names()) | set(X_REPLACED))


def static_problems(here: Path = GC.HERE) -> list[str]:
    files = sorted(Path(here).glob("*.py")) + sorted((Path(here) / "gencard").glob("*.py"))
    foreign, consts = foreign_modules(here), static_consts()
    return [p for f in files for p in source_problems(f, foreign, consts)]


def modules_item(store: bool = True, run_probe: Callable[[str | None, Mapping[str, str]], dict] = probe,
                 targets: Sequence[str] | None = None, workers: int = PROBE_WORKERS) -> dict:
    """§3.9's sys.modules test; ``store`` False leaves out the triggers that read the store (prod_trigger)."""
    triggers = {k: v for k, v in TRIGGERS.items() if store or k not in STORE_TRIGGERS}
    base = run_probe(None, {})
    baseline, baseline_wide = dict(sorted((base.get("full") or {}).items())), outside(base.get("wide"))
    targets = list(gen_modules() if targets is None else targets)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda t: run_probe(t, triggers), targets))
    problems = baseline_problems(base) + [p for t, r in zip(targets, results)
                                          for p in module_problems(t, r, baseline, baseline_wide)]
    problems += [f"CLI entry {m} is not among the modules found" for m in CLI_ENTRIES if m not in targets]
    static = static_problems()
    skipped = sorted(set(TRIGGERS) - set(triggers))
    return {"pass": not problems and not static and not skipped,
            "counts": {"probed": len(targets), "baseline": len(baseline), "baseline_wide": len(baseline_wide),
                       "problems": len(problems), "static_problems": len(static), "skipped_triggers": len(skipped)},
            "baseline": baseline, "baseline_sha256": {f: sha_or_none(GC.REPO / f) for f in baseline.values()},
            "baseline_wide": baseline_wide, "probed": targets, "triggers": sorted(triggers),
            "skipped_triggers": skipped, "x_common_allowed": {k: list(v) for k, v in X_COMMON_ALLOWED.items()},
            "problems": problems + static}


# ---------------------------------------------------------------- the document, check and run
def git_head() -> str | None:
    r = subprocess.run(["git", "-C", str(GC.REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def build(*, pool: Callable[[], dict] | None = None, run_tests: Callable[[Sequence[str]], dict] | None = None,
          modules: Callable[[], dict] | None = None, pins: Callable[[], dict] | None = None,
          watch: Path | None = None) -> dict:
    """Every item recomputed now, each between two snapshots of ``watch`` (the store's out root); ``pool``,
    ``run_tests`` and ``modules`` replace the real ones in tests."""
    watch = Path(watch or GC.OUT_ROOT)
    items = {"pool": watched(pool or pool_item, watch)}
    for key, ref, selection in TEST_ITEMS:
        items[key] = watched(lambda: selection_item(ref, selection, run_tests or pytest_selection), watch)
    items["modules"] = watched(modules or modules_item, watch)
    return {"schema": SCHEMA, "t": F1.now(), "git_head": git_head(), "harness_sha256": (pins or F1.harness_pins)()["sha256"],
            "pass": all(items[k]["pass"] for k in ITEM_ORDER), "items": {k: items[k] for k in ITEM_ORDER}}


def summary(doc: Mapping[str, Any]) -> dict:
    """What check and run print: per item its pass and counts (numbers and booleans only)."""
    return {"k0": "pass" if doc["pass"] else "fail",
            "items": {k: {"pass": v["pass"], "counts": v.get("counts", {})} for k, v in doc["items"].items()}}


def failed_items(doc: Mapping[str, Any]) -> list[str]:
    return [k for k, v in doc["items"].items() if not v["pass"]]


def k_gold_note(doc: Mapping[str, Any]) -> dict:
    """K0-gold or K0-lines below its total: a K-gold candidate, for a CPU trace (§3.6) to decide."""
    pool = doc["items"]["pool"]
    return {"k_gold_candidate": True, "layer": k_gold_value(pool)} if pool.get("k_gold_candidate") else \
        {"k_gold_candidate": False}


def check(log: Callable[[Any], None] = print, **kw: Any) -> int:
    """Recompute every item and print counts and booleans only; nothing is written (each item is watched)."""
    doc = build(**kw)
    log(json.dumps(summary(doc), ensure_ascii=False))
    log(json.dumps({"failed": failed_items(doc), **k_gold_note(doc)}))
    return 0 if doc["pass"] else 1


def attempts_of(attempts: Path) -> list[Path]:
    return sorted(p for p in Path(attempts).glob("*.json") if p.stem.isdigit())


def write_attempt(doc: Mapping[str, Any], attempts: Path, log: Callable[[Any], None], **why: Any) -> int:
    """A failed K0, kept as k0_attempts/<n>.json (each written once); K0 runs again after the fix."""
    n = 1 + max((int(p.stem) for p in attempts_of(attempts)), default=0)
    path = Path(attempts) / f"{n:03d}.json"
    if path.exists():
        raise SystemExit(f"{path.name} exists: another K0 attempt ran at the same time")
    GC.write_json(path, {**doc, "pass": False, "attempt": n, **why})
    log(json.dumps({"failed": failed_items(doc), "attempt": n, "attempt_sha256": GC.sha256_file(path), **why,
                    **k_gold_note(doc)}))
    return 1


def suite_check(suite: Callable[[], list[str]], watch: Path) -> Callable[[], list[str]]:
    """record_k0's ``tests``: the test_gen_confirm_* suite passes and leaves every file below ``watch`` as it was."""
    def tests() -> list[str]:
        before = store_snapshot(watch)
        bad = list(suite())
        changed = changed_paths(before, store_snapshot(watch))
        return bad + ([f"the test_gen_confirm_* suite changed {len(changed)} store file(s): {changed}"] if changed
                      else [])
    return tests


def run(*, out: Path | None = None, harness_record: Path | None = None, attempts: Path | None = None,
        git: Callable[[], list[str]] | None = None, record: Callable[..., Any] | None = None,
        suite: Callable[[], list[str]] | None = None, watch: Path | None = None,
        log: Callable[[Any], None] = print, **kw: Any) -> int:
    """At the K0 commit: every item; when all pass, the K0 harness record (f1_g.record_k0, its suite watched), then
    k0.json once. A failure of either is a new k0_attempts/<n>.json and leaves the way open for the next K0."""
    out, hr = Path(out or K0_FILE), Path(harness_record or F1.HARNESS_RECORD)
    att, watch, git = Path(attempts or K0_ATTEMPTS), Path(watch or GC.OUT_ROOT), git or F1.git_problems
    bad = list(git())
    bad += [f"{out.name} exists: K0 passed and is made once"] if out.exists() else []
    bad += [f"{hr.name} exists: the K0 harness record is made once"] if hr.exists() else []
    if bad:
        raise SystemExit(f"K0 refused: {bad}")
    doc = build(watch=watch, **kw)
    log(json.dumps(summary(doc), ensure_ascii=False))
    if not doc["pass"]:
        return write_attempt(doc, att, log, harness_record="not made")
    if out.exists() or hr.exists():
        raise SystemExit("k0.json or the K0 harness record appeared while K0 ran: K0 is made once")
    try:
        (record or F1.record_k0)(record=hr, git=git, pins=kw.get("pins"),
                                 tests=suite_check(suite or F1.suite_problems, watch))
    except SystemExit as err:                         # nothing of K0 is kept but the attempt
        return write_attempt(doc, att, log, harness_record="refused", refusal=str(err))
    GC.write_json(out, {**doc, "failed_attempts": len(attempts_of(att))})
    log(json.dumps({"k0_sha256": GC.sha256_file(out), "harness_record_sha256": GC.sha256_file(hr)}))
    return 0


def k0_problems(k0: Path | None = None, harness_record: Path | None = None,
                harness: Callable[..., list[str]] | None = None) -> list[str]:
    """Why a USD step may not start (§8.1-1: K0 before any USD; empty = it may): k0.json is a passing K0, its harness
    is the K0 harness record's, and the harness now is the record's (f1_g.harness_problems)."""
    k0, hr = Path(k0 or K0_FILE), Path(harness_record or F1.HARNESS_RECORD)
    if not k0.is_file():
        return [f"{k0.name} missing: K0 has not passed"]
    doc = GC.read_json(k0)
    out = [] if doc.get("schema") == SCHEMA and doc.get("pass") is True else [f"{k0.name} is not a passing K0"]
    if not hr.is_file():
        return out + [f"{hr.name} missing: no K0 harness record"]
    if (GC.read_json(hr).get("k0") or {}).get("sha256") != doc.get("harness_sha256"):
        out.append(f"{k0.name}'s harness is not the K0 harness record's")
    return out + list((harness or F1.harness_problems)(record=hr))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="K0-合成 (prereg §8.1-1): CPU only, 0 USD")
    ap.add_argument("command", choices=("check", "run"))
    args = ap.parse_args(argv)
    return check() if args.command == "check" else run()


if __name__ == "__main__":
    sys.exit(main())
