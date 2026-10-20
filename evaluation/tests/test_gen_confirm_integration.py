"""GEN confirmation set: the batch-3 integration (prereg §3.3, §3.8, §3.9, §4.3, §4.5, §5.5).

Covered: every amount, attempt or stop count, path and store name of the GEN modules is g_common's object (an
alias ``is`` it) and no module builds its own (§3.9; the F0 values themselves are test_gen_confirm_core's); the
trigger's own files (g_common.trigger_pins) and g_common.py are in the F1 manifest and in every check against it
(§3.9, §4.3, §4.5, D15); the memory markers name every file of this folder, each one is caught in a transcript, and
none hits a compliant transcript, a rendered HO or qset prompt, the bt tool's text or the prompt files (§3.3);
F2's frozen group is the card's files by key (§5.5). Synthetic strings only; the store tests skip when it is not
mounted and print counts and keys, never text. Nothing calls an LLM or Ollama.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

H_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H_DIR) not in sys.path:
    sys.path.insert(0, str(H_DIR))

import banned_g as B  # noqa: E402
import bt_g as BT  # noqa: E402
import claude_g as CL  # noqa: E402
import f1_g as F1  # noqa: E402
import f1a_g as FA  # noqa: E402
import f2_g as F2  # noqa: E402
import freeze_g as FZ  # noqa: E402
import g_common as GC  # noqa: E402
import hog_common as H  # noqa: E402
import kay_g as K  # noqa: E402
import ledger_g as LG  # noqa: E402
import names_g as N  # noqa: E402
import power_g as PG  # noqa: E402
import probe_g as PR  # noqa: E402
import prompt_qg as Q  # noqa: E402
import prompts_g as P  # noqa: E402
import run_g as RG  # noqa: E402
import run_ho_g as RH  # noqa: E402
import run_qg as RQ  # noqa: E402
import runs_g as RU  # noqa: E402
import score_g as SG  # noqa: E402
import spec_qg as SQ  # noqa: E402
import state_g as ST  # noqa: E402
import test_gen_confirm_infra as IT  # noqa: E402
import test_gen_confirm_prompts as TP  # noqa: E402
import transcript_g as TR  # noqa: E402
import void_g as V  # noqa: E402
from test_gen_confirm_qset import specs, syn  # noqa: E402,F401

STORE_OK = GC.R4_LAYER.is_file() and GC.ROUTING_LEXICON.is_file() and GC.GEN_NAMES.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({GC.STORE})")
NEW_MARKERS = ("hog_common", "claude_g", "bt_g", "ledger_g", "transcript_g", "probe_g", "arms_g", "score_g", "f1_g",
               "f2_g", "f1a_g", "freeze_g", "kay_g", "run_ho_g", "runs_g", "state_g", "spec_qg", "prompt_qg",
               "prompts_qg", "mech_qg", "run_qg", "k0_g", "smoke_g", "void_g")

# (module, its alias, the g_common name): every alias is the g_common object (prereg §3.9)
ALIASES = (
    (H, "PROBE_ROOT", "PROBE_ROOT"), (H, "CLI_DIR", "CLI_DIR"), (H, "BT_GUARD", "BT_GUARD"),
    (CL, "AGENT_CWD", "AGENT_CWD"), (CL, "CLI_VERSIONS_DIR", "CLI_VERSIONS_DIR"), (CL, "CLI_DIR", "CLI_DIR"),
    (CL, "PIN_PATH", "CLI_PIN"), (CL, "VERSION_TRIES", "CLI_VERSION_TRIES"),
    (LG, "KIND_JOB_CAP", "KIND_JOB_CAP_USD"), (LG, "SPEND_LIMIT_USD", "SPEND_LIMIT_USD"),
    (LG, "LOCK_NAME", "LEDGER_LOCK"), (LG, "SNAPSHOT_NAME", "LEDGER_SNAPSHOT"),
    (PR, "REPS_BT", "PROBE_REPS_BT"), (PR, "RUN_CAP_USD", "PROBE_RUN_CAP_USD"),
    (PR, "INVOCATION_CAP_USD", "PROBE_INVOCATION_CAP_USD"),
    (B, "HO_BANNED", "HO_BANNED"), (B, "A_BANNED", "A_BANNED"), (B, "GENCARD_DIR", "GENCARD_DIR"),
    (P, "GEN_PROMPT", "GEN_PROMPT"), (P, "AUDIT_PROMPT", "AUDIT_PROMPT"), (Q, "PROMPT_FILE", "QSET_PROMPT"),
    (N, "TEXT_DIR", "TEXT_LAYER"), (N, "LEXICON", "ROUTING_LEXICON"),
    (SQ, "SETS", "QSET_SETS"), (SQ, "SPEC_FILE", "QSET_SPEC"), (SQ, "N_POS", "N_POS"), (SQ, "N_NEAR", "N_NEAR"),
    (SQ, "N_DEV", "N_DEV"), (SQ, "JOB_SIZE", "QSET_JOB_SIZE"),
    (RQ, "DRAFTS", "QSET_DRAFTS"), (RQ, "GEN_DONE", "QSET_GEN_DONE"), (RQ, "REFILL_DONE", "QSET_REFILL_DONE"),
    (RQ, "SCORE_DONE", "QSET_SCORE_DONE"), (RQ, "G1_FILE", "G1_FILE"), (RQ, "NEAR_FILE", "P2_NEAR_FILE"),
    (RQ, "ITEMS_FILE", "QSET_ITEMS"), (RQ, "P1_SCORES", "P1_SCORES"), (RQ, "P1_ROWS", "P1_ROWS"),
    (RQ, "LOCK_FILE", "QSET_LOCK"), (RQ, "G1_N", "G1_N"), (RQ, "GT_FILES", "GT_FILES"),
    (RQ, "P2_RESERVE_USD", "P2_RESERVE_USD"), (RQ, "P1_LIMIT_USD", "P1_LIMIT_USD"),
    (FA, "TESTS_DIR", "TESTS_DIR"), (FA, "GT_FILES", "GT_FILES"),
    (F1, "CLI_PIN", "CLI_PIN"), (F1, "PREREG", "PREREG"), (F1, "HARNESS_RECORD", "HARNESS_RECORD"),
    (F1, "TESTS_DIR", "TESTS_DIR"), (F2, "OUT", "F2_FILE"),
    (FZ, "TRIGGER_FILES", "PROD_TRIGGER_FILES"), (FZ, "LEXICON", "ROUTING_LEXICON"), (FZ, "FREEZE_FILE", "FREEZE_FILE"),
    (K, "K_KAY_STOP", "K_KAY_STOP"), (K, "PAGE", "KAY_PAGE"), (K, "SAMPLE", "KAY_SAMPLE"),
    (ST, "ROOTS", "HO_SUB_ROOTS"), (RU, "UNAVAILABLE_WAVES", "UNAVAILABLE_WAVES"), (RH, "K_GOLD_FILE", "K_GOLD_FILE"),
    (RH, "HO_FILES", "?TOOL_FILES"),
    (SG, "GEN", "RUN_GEN"), (SG, "TRUNC_ARM_MAX", "TRUNC_ARM_MAX"), (SG, "TRUNC_GAP_MAX", "TRUNC_GAP_MAX"),
    (RG, "RUN_ROOT", "RUN_ROOT"), (RG, "F2_FILE", "F2_FILE"), (RG, "P2_RESULT", "P2_NEAR_MISS"), (RG, "P2_N", "N_NEAR"),
    (RG, "STAGE0_RUN_META", "STAGE0_RUN_META"), (RG, "DATA_FILES", "RUN_DATA_FILES"), (RG, "F3_FILE", "RUN_F3"),
    (RG, "SMOKE_FILE", "RUN_SMOKE"), (RG, "CANARY_FILE", "RUN_CANARY"), (RG, "RUN_META", "RUN_META"),
    (RG, "GEN", "RUN_GEN"), (RG, "SMOKE_HISTORY", "SMOKE_HISTORY"), (RG, "SMOKE_SET_ASIDE", "SMOKE_SET_ASIDE"),
    (RG, "TORN", "RUN_TORN"), (RG, "LOCK", "RUN_LOCK"), (RG, "KINDS", "RUN_KINDS"),
    (RG, "SMOKE_PER_ARM", "SMOKE_PER_ARM"), (RG, "CANARY_CALLS", "CANARY_CALLS"), (RG, "EVAL_DIR", "EVAL_DIR"),
    (RG, "PREREG", "PREREG"),
    (V, "VOID_FILE", "VOID_FILE"),
)
# never read g_common: F0's own files (frozen), gencard (moved into the backend as is, stdlib only), bt_g (the
# agents' tool imports nothing of this folder) and k0_g (the K0 builder's)
NOT_SCANNED = {"g_common.py", "pool_g.py", "power_g.py", "order_g.py", "bt_g.py", "k0_g.py"}
_FILE_NAME = re.compile(r"\.(?:json|jsonl|lock|html)$")
_ROOTS = {"OUT_ROOT", "STORE", "REPO", "HERE", "QSET_ROOT", "HO_ROOT", "STAGE0_OUT", "STAGE0_DIR"}


# ---------------------------------------------------------------- §3.9: the constants are g_common's
@pytest.mark.parametrize("mod, alias, name", ALIASES, ids=[f"{m.__name__}.{a}" for m, a, _n in ALIASES])
def test_every_alias_is_the_g_common_object(mod, alias, name):
    want = H.TOOL_FILES if name == "?TOOL_FILES" else getattr(GC, name)
    assert getattr(mod, alias) is want


def _bound_value(path: Path, alias: str) -> ast.expr | None:
    """The expression a module-level assignment binds to ``alias`` (its element of a tuple assignment)."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
            if isinstance(t, ast.Name) and t.id == alias:
                return node.value
            if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(t.elts) == len(node.value.elts):
                hit = [v for e, v in zip(t.elts, node.value.elts) if isinstance(e, ast.Name) and e.id == alias]
                if hit:
                    return hit[0]
    return None


@pytest.mark.parametrize("mod, alias, name", ALIASES, ids=[f"{m.__name__}.{a}" for m, a, _n in ALIASES])
def test_every_alias_is_written_as_g_commons_name(mod, alias, name):
    """§3.9 (review m01): ``is`` cannot tell a literal small int or identifier-like string (cached, interned) from
    g_common's object, so each alias must read GC.<name> in its source, or an alias of it in another listed module."""
    v = _bound_value(Path(mod.__file__), alias)
    assert isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name), f"{mod.__name__}.{alias} is not X.<name>"
    src, listed = getattr(mod, v.value.id, None), {(m, a): n for m, a, n in ALIASES}
    ok = (src is GC and v.attr == name) or (name == "?TOOL_FILES" and src is H and v.attr == "TOOL_FILES") or \
        listed.get((src, v.attr)) == name
    assert ok, f"{mod.__name__}.{alias} reads {v.value.id}.{v.attr}, not GC.{name}"


def test_the_alias_source_check_catches_a_literal(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("A = GC.X\nB, C = GC.Y, 3\nD = 3\n", encoding="utf-8")
    assert [ast.dump(_bound_value(src, n)) for n in "ABCD"] == [
        ast.dump(ast.parse("GC.X", mode="eval").body), ast.dump(ast.parse("GC.Y", mode="eval").body),
        ast.dump(ast.Constant(3)), ast.dump(ast.Constant(3))]


def _constant_problems(path: Path) -> list[str]:
    out = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
        consts = [c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant)]
        amounts = [c for c in consts if isinstance(c, (int, float)) and not isinstance(c, bool)]
        if any("USD" in n for n in names) and amounts:
            out.append(f"{path.name}: {names} sets an amount")
        if any(isinstance(c, str) and _FILE_NAME.search(c) for c in consts):
            out.append(f"{path.name}: {names} names a store or repo file")
        for b in (n for n in ast.walk(node.value) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)):
            if any(isinstance(a, ast.Attribute) and a.attr in _ROOTS for a in ast.walk(b.left)):
                out.append(f"{path.name}: {names} builds a path below a root")
    return out


def test_no_gen_module_builds_its_own_amount_path_or_file_constant():
    files = [p for p in sorted(H_DIR.glob("*.py")) if p.name not in NOT_SCANNED]
    assert len(files) >= 25
    assert [p for f in files for p in _constant_problems(f)] == []


def test_the_run_side_names_the_run_files_by_g_commons_names():
    """§3.9 (review m09): the run side keys and opens the build's and the runs' files by g_common's names
    (GC.RUN_ITEMS, ...), never by a literal of its own, so one name changes them everywhere."""
    names = {*GC.RUN_DATA_FILES, GC.RUN_F3, GC.RUN_META, GC.RUN_GEN, GC.RUN_TORN, GC.RUN_SMOKE, GC.RUN_CANARY,
             GC.SMOKE_HISTORY, GC.RUN_SCORES, GC.RUN_REPORT, GC.RUN_REPORT_MD, GC.DRY_RUN_REPORT}
    files = ("run_g.py", "smoke_g.py", "score_g.py", "analyze_g.py", "void_g.py", "f2_g.py")
    hits = [f"{f}:{c.lineno}" for f in files for c in ast.walk(ast.parse((H_DIR / f).read_text(encoding="utf-8")))
            if isinstance(c, ast.Constant) and c.value in names]
    assert len(names) == 15 and hits == []


def test_the_constant_scan_catches_each_kind(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text('CAP_USD = 2.0\nNAME = "x.json"\nROOT = GC.OUT_ROOT / "x"\nOK_USD = GC.USD_CAP\n', encoding="utf-8")
    assert [p.split(": ", 1)[1] for p in _constant_problems(src)] == [
        "['CAP_USD'] sets an amount", "['NAME'] names a store or repo file", "['ROOT'] builds a path below a root"]


def test_the_batch_3_values():
    assert (GC.SPEND_LIMIT_USD, GC.P2_RESERVE_USD, GC.P1_LIMIT_USD) == (49.0, 1.5, 1.5)
    assert GC.KIND_JOB_CAP_USD == {"probe": GC.PROBE_CAP_USD, "qset": 0.2, "ho": 2.0}
    assert GC.PROBE_INVOCATION_CAP_USD == 0.46 and GC.PROBE_MAX_RUNS * GC.PROBE_INVOCATION_CAP_USD <= GC.PROBE_CAP_USD
    assert (GC.PROBE_REPS_BT, GC.CLI_VERSION_TRIES, GC.UNAVAILABLE_WAVES, GC.K_KAY_STOP) == (3, 2, 3, 3)
    assert (GC.G1_N, GC.N_POS, GC.N_NEAR, GC.N_DEV, GC.QSET_JOB_SIZE) == (PG.N_PLAN, PG.P2_POSITIVES, 20, 14, 3)
    assert (GC.SMOKE_PER_ARM, GC.CANARY_CALLS, GC.TRUNC_ARM_MAX, GC.TRUNC_GAP_MAX) == (2, 30, 2, 2)
    assert GC.OLLAMA_OPTIONS == dict(GC.stage0().x_common.OPTIONS) == RG.OPTIONS
    for p in (GC.PROBE_ROOT, GC.CLI_DIR, GC.CLI_PIN, GC.HARNESS_RECORD, GC.K0_FILE, GC.F2_FILE, GC.VOID_FILE,
              GC.RUN_ROOT):
        assert p.parent == GC.OUT_ROOT, p.name
    assert GC.K0_FILE.name == "k0.json" and (GC.G1_RESULT, GC.P2_NEAR_MISS) == (GC.QSET_ROOT / "g1.json",
                                                                               GC.QSET_ROOT / "p2_near_miss.json")
    assert GC.HO_SUB_ROOTS == ("pilot", "main", "kay") and GC.QSET_SETS == ("p1", "p2")
    assert GC.TEXT_LAYER == BT.TEXT and GC.BT_GUARD.is_file() and GC.HO_BANNED.is_file() and GC.A_BANNED.is_file()
    assert GC.PREREG.is_file() and GC.GEN_PROMPT.is_file() and GC.AUDIT_PROMPT.is_file() and GC.QSET_PROMPT.is_file()
    assert RG.void_file() == GC.VOID_FILE and set(GC.PROD_TRIGGER_FILES) <= set(GC.BACKEND_PIN_FILES)
    assert set(GC.TRIGGER_PIN_FILES) <= set(GC.TRIGGER_PINS_SHA256) and len(GC.TRIGGER_PINS_SHA256) == 6


# ---------------------------------------------------------------- §3.9, §4.3: trigger_pins, g_common, the F1 manifest
def test_g_common_is_one_of_f1s_own_files():
    key = F1.rel(GC.HERE / "g_common.py", GC.REPO)
    assert "g_common.py" in F1.F1_OWN and key in F1.own_paths() and key in F1.frozen_paths()


@needs_store
def test_trigger_pins_have_the_shape_of_backend_pins_and_the_kept_values():
    pins = GC.trigger_pins()
    assert pins == GC.TRIGGER_PINS_SHA256 and not set(pins) & set(GC.backend_pins())
    assert all(isinstance(v, str) and len(v) == 64 for v in pins.values())
    assert F1.prod_pins() == {**GC.backend_pins(), **pins}


def _manifest_args(tmp_path: Path) -> tuple:
    """write_manifest's arguments on a tmp store (a made-up names file and CLI pin), the real prod pins (None)."""
    store, cli = tmp_path / "store", tmp_path / "store/out/cli_pin.json"
    gn = store / "out/gen_names.json"
    GC.write_json(gn, {"syn": 1})
    GC.write_json(cli, {"claude": "9.9.9"})
    group, own = F1.f1a_paths(store=store, gen_names=gn), F1.own_paths(store=store, cli_pin=cli)
    f1a = tmp_path / "f1a_pins.json"
    GC.write_json(f1a, {"files": F1.sha_map(group)})
    return tmp_path / "f1_manifest.json", f1a, group, own, None, GC.REPO, lambda ps: []


@needs_store
def test_the_f1_manifest_holds_the_trigger_pins_and_g_common(tmp_path):
    doc = F1.write_manifest(*_manifest_args(tmp_path))
    files = doc["files"]
    assert set(GC.trigger_pins()) <= set(files) and set(GC.backend_pins()) <= set(files)
    assert files[F1.rel(GC.HERE / "g_common.py", GC.REPO)] == GC.sha256_file(GC.HERE / "g_common.py")


@needs_store
def test_f1_refuses_a_trigger_file_or_layer_that_f2_step_3_would_refuse_for_good(tmp_path, monkeypatch):
    """§4.3 (D15, review M2): F1 written with a trigger file or the r4 layer off its kept sha256 could never pass
    freeze_g.prod_trigger (the file back at its kept sha256 differs from the manifest): F1 refuses it, nothing
    written, and the manifest it writes with the kept files passes F2 step 3's pin check."""
    args = _manifest_args(tmp_path)
    r4 = str(GC.R4_LAYER.relative_to(GC.STORE))
    for attr, key in (("trigger_pins", "packages/ragcommon/routing.py"), ("backend_pins", r4)):
        real = getattr(GC, attr)
        with monkeypatch.context() as m:
            m.setattr(GC, attr, lambda real=real, key=key: {**real(), key: "d" * 64})
            with pytest.raises(SystemExit, match=f"prod pin {re.escape(key)} is not the sha256 g_common keeps"):
                F1.write_manifest(*args)
        assert not args[0].exists()
    assert callable(FZ.prod_trigger(F1.write_manifest(*args)["files"]))


@needs_store
def test_the_ho_runner_checks_the_trigger_pins_and_g_common_against_the_manifest(tmp_path):
    paths = ST.Paths(out_root=tmp_path)
    GC.write_json(paths.cli_pin, {"claude": "9.9.9"})
    files = {**F1.sha_map(F1.frozen_paths()), **F1.prod_pins(), RH.CLI_KEY: GC.sha256_file(paths.cli_pin)}
    GC.write_json(paths.f1_manifest, {"files": files})
    assert RH.f1_problems(paths) == []
    lexicon = str(GC.ROUTING_LEXICON.relative_to(GC.STORE))
    gkey = F1.rel(GC.HERE / "g_common.py", GC.REPO)
    for key in (lexicon, "packages/ragcommon/routing.py", gkey):
        GC.write_json(paths.f1_manifest, {"files": {**files, key: "0" * 64}})
        assert RH.f1_problems(paths) == [f"{key} is not the F1 manifest's"]
    GC.write_json(paths.f1_manifest, {"files": {k: v for k, v in files.items() if k != lexicon}})
    assert RH.f1_problems(paths) == [f"{lexicon} is not the F1 manifest's"]


# ---------------------------------------------------------------- §5.5: F2's frozen group
def test_f2_frozen_group_is_exactly_the_cards_files_of_the_f1a_group_by_key():
    group, f1a = F2.frozen_group(), F1.f1a_paths()
    gencard = {k for k in f1a if "/gencard/" in k and k.endswith(".py")}
    names = F1.rel(GC.GEN_NAMES, GC.STORE)
    assert set(group) == gencard | {names} == set(F1.card_paths()) and len(gencard) >= 5
    assert all(group[k] == f1a[k] for k in group)
    assert {k.rsplit("/", 1)[-1] for k in set(f1a) - set(group)} == {"mech_g.py", "mech_qg.py"}


# ---------------------------------------------------------------- §3.3: the memory markers
def test_every_file_of_this_folder_is_a_memory_marker():
    stems = {p.stem for p in H_DIR.glob("*.py")} | {p.stem for p in H_DIR.glob("*.md")} | {"gencard"}
    assert {"smoke_g", "void_g"} <= stems and stems <= set(B.MEMORY_MARKERS)
    assert set(NEW_MARKERS) <= set(B.G_MEMORY_MARKERS) and len(set(B.G_MEMORY_MARKERS)) == len(B.G_MEMORY_MARKERS)


@pytest.mark.parametrize("marker", NEW_MARKERS)
def test_each_new_marker_is_caught_in_a_transcript(marker):
    said = {"type": "assistant", "message": {"content": [{"type": "text", "text": f"(compare {marker}.py)"}]}}
    vs = TR.check_events(IT._events(extra=[said]), IT._prompts(), IT.OPUS, "bt", Path("/srv"), IT.FAKE_VERSION)
    assert {(v.rule, v.level) for v in vs} == {("t_memory", "error")} and any(repr(marker) in v.detail for v in vs)
    assert marker in {h.term for h in B.transcript_hits(marker.upper())}           # "kay_g" also hits HO's "Kay"


def test_a_marker_never_hits_a_longer_name_that_contains_it():
    for text in ("bt_guard", "ho_bt_guard_for_g", "mech_qg", "run_ho_g", "prompts_qg", "f1a_g", "xstate_g", "kay_gx",
                 "claude_code_version", "smoke_gen", "void_guard"):
        hits = {h.term for h in B.find_terms(text, B.G_MEMORY_MARKERS)}
        assert hits == ({text} if text in B.G_MEMORY_MARKERS else set()), text


def _visible(events, prompts) -> list[str]:
    return [t for _w, t in TR.visible_texts(events, prompts)]


def test_no_marker_hits_a_compliant_transcript_the_bt_tool_the_probe_or_the_prompt_files(tmp_path):
    texts = _visible(IT._events(), IT._prompts())
    texts += _visible(IT._events("none", IT.SONNET), IT._prompts(model=IT.SONNET, tools_mode="none"))
    with B.override_cue_literals(TP.STAND_IN_CUES):
        path, _out = TP._compliant_run(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    texts += _visible(doc["events"], doc["prompts"])
    guard = H.bt_guard()
    texts += [BT.USAGE, *BT._PROBLEM.values(), *(guard.check_command(c) or "" for c in (
        "ls", "bt v ../x", "cat /etc/passwd", "bt x; ls", "bt v gen.5.3", "bt grep '某' gen", "bt books"))]
    texts += [PR.PROBE_SYSTEM, PR.PROBE_USER, PR.NONE_SYSTEM, PR.NONE_USER, json.dumps(PR.PROBE_SCHEMA)]
    texts += [p.read_text(encoding="utf-8") for p in (GC.GEN_PROMPT, GC.AUDIT_PROMPT, GC.QSET_PROMPT)]
    assert len(texts) > 30 and [h.term for t in texts for h in B.find_terms(t, B.G_MEMORY_MARKERS)] == []
    with B.override_cue_literals(TP.STAND_IN_CUES):
        assert TR.blinding(TR.check_events(doc["events"], doc["prompts"], "claude-opus-5-5", "bt")) == []


def test_no_marker_hits_a_rendered_ho_prompt():
    names, texts = TP.fake_names(), []
    with B.override_cue_literals(TP.STAND_IN_CUES):
        for row, q in ((TP.ROW_F1, TP.Q_F1), (TP.ROW_F5, TP.Q_F5), (TP.ROW_MK, TP.Q_MK), (TP.ROW_11, TP.Q_11)):
            item = TP.draft(row, q)
            for r in (P.render_writer(row, names, "Q09"), P.render_audit(q, row, "Q09", names),
                      P.render_fix("audit", row, names, "Q09", item, (P.Issue.tool("make it shorter"),)),
                      P.render_kay_revise(row, names, "Q09", item, "請把問句改短")):
                texts += [r.system, r.user, json.dumps(r.schema, ensure_ascii=False)]
    assert len(texts) == 48 and [h.term for t in texts for h in B.find_terms(t, B.G_MEMORY_MARKERS)] == []


def test_no_marker_hits_a_rendered_qset_prompt(syn, specs):
    texts = []
    for spec in specs.values():
        for job in spec["jobs"]:
            r = Q.render_job(job, syn.names)
            texts += [r.system, r.user, json.dumps(r.schema, ensure_ascii=False), *map(str, r.values.values())]
    assert len(texts) > 100 and [h.term for t in texts for h in B.find_terms(t, B.G_MEMORY_MARKERS)] == []


@needs_store
def test_no_marker_hits_a_store_rendered_qset_or_ho_prompt():
    names, n = P.load_names(), 0
    p1 = SQ.build_from_store("p1")
    for spec in (p1, SQ.build_from_store("p2", p1_spec=p1)):
        for job in spec["jobs"]:
            r = Q.render_job(job, names)
            parts = (r.system, r.user, *map(str, r.values.values()))
            n += sum(bool(B.find_terms(t, B.G_MEMORY_MARKERS)) for t in parts)
    for i, row in enumerate(GC.read_json(GC.POOL)["pool"], 1):
        r = P.render_writer(row, names, ST.qid_of(i))
        n += sum(bool(B.find_terms(t, B.G_MEMORY_MARKERS)) for t in (r.system, r.user))
    assert n == 0


def test_the_tool_files_are_the_ho_and_qset_runners_and_their_prompts():
    tools = set(H.TOOL_FILES)
    assert {"state_g.py", "runs_g.py", "run_ho_g.py", "kay_g.py", "freeze_g.py", "run_qg.py", "spec_qg.py",
            "prompt_qg.py", "prompts_qg.md", "mech_qg.py"} <= tools and RH.HO_FILES is H.TOOL_FILES
    assert all((GC.HERE / n).is_file() for n in tools) and len(tools) == len(H.TOOL_FILES)
    assert set(H.tool_sha()) == tools | {str(GC.BT_GUARD.relative_to(GC.REPO))}
