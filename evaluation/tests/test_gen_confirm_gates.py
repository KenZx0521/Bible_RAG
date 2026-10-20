"""GEN confirmation set: §4.5's gates, the build (F3), the dry run, the formal run, score and analyze, the F1 manifest
and F2 (run_g, f1_g, f2_g, void_g; prereg §3.8, §4.3, §4.5, §5.5, §8.1-10, §9).

Moved out of test_gen_confirm_run, whose synthetic layer, pool, questions, fakes and fixtures (the autouse
``later_store_files_in_tmp`` with them: every later store path points into tmp) these tests import. Ollama and
every LLM are never called: chats are fakes, every /api answer comes from a fake ``get``, the K-a gate is a fake
except in the store test. Everything is written to temporary directories only. The store tests (skipped when it
is not mounted) build questions at run time from the layer's names on real pool slots, assert counts, ids and
booleans only and never print a question. Covered: every gate of §4.5 with fakes (the F1 manifest's files with the
prod pins, the P2 record, f2.json); the build and its refusals; a dry run end to end; the canary and the formal
run; score and analyze, their refusals and HO's freeze.json beside the run root (D24); the command line; the F1
manifest and its refusals (the prod pins g_common keeps, D15); F2 (its refusals, its void record and command) on a
synthetic and on the real pool. Every negative case is one rule of the prereg (named by its section, or the review
id it closes).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import f2_g as F2  # noqa: E402
import order_g as O  # noqa: E402
import smoke_g as SM  # noqa: E402
import void_g as V  # noqa: E402
from test_gen_confirm_run import (ABST, GEN, L, NAME, NO_CUE, ORDER, POOL, QUIET, T, A, Api, Chat, F1, GC,  # noqa: E402,F401
                                  R, SG, built, cc, fake_jobs, frozen_doc, gencard, later_store_files_in_tmp, logged,
                                  needs_store, pick, root, slot, src_of, syn_item)

F2_OLD = "2026-10-21 凍結之前的一行紀錄"                    # before the frozen questions' sha line
F2_VOID = "2026-10-23 對等不過：只能改共用的提示檔"


# ---------------------------------------------------------------- §4.5 pins and the whole gate, with fakes
@pytest.fixture
def f2ok(tmp_path, monkeypatch, built):
    """questions_frozen.json, the F1 manifest (its files: a made-up rule file and names file, a backend pin),
    order.json drawn from it and a passed f2.json of the built set, in tmp."""
    return frozen_env(tmp_path, monkeypatch, *built)


def frozen_env(tmp_path: Path, monkeypatch, doc: dict, b: dict) -> SimpleNamespace:
    """f2ok's files for the frozen set ``doc`` and its build ``b``."""
    qf, man, order, f2, gn, rule = (tmp_path / n for n in ("questions_frozen.json", "f1_manifest.json", "order.json",
                                                          "f2.json", "gen_names.json", "rule.py"))
    GC.write_json(qf, doc)
    GC.write_json(gn, {"syn": 1})
    rule.write_text("x = 1\n", encoding="utf-8")
    group, backend = {"out/gen_names.json": gn, "syn/gencard/a.py": rule}, {"backend/x.py": "b" * 64}
    trigger = {"packages/syn/x.py": "t" * 64}                      # a made-up trigger_pins() item (D15)
    GC.write_json(man, {"files": {**F1.sha_map(group), **backend, **trigger}})
    GC.write_json(order, {"f1_manifest_sha256": GC.sha256_file(man), "order": ORDER})
    GC.write_json(f2, {"questions_frozen_sha256": GC.sha256_file(qf), "f1_manifest_sha256": GC.sha256_file(man),
                       "K_a": {"pass": True, "sentence": None}, "parity": {"pass": True},
                       "prompts_sha256": A.prompts_sha256(b["jobs"]), "measures": A.rule_measures(b["meta"])})
    for k, v in (("QUESTIONS_FROZEN", qf), ("ORDER", order), ("F1_MANIFEST", man)):
        monkeypatch.setattr(GC, k, v)
    monkeypatch.setattr(R, "F2_FILE", f2)
    return SimpleNamespace(qf=qf, man=man, order=order, f2=f2, gn=gn, rule=rule, group=group, backend=backend,
                           trigger=trigger)


def p2_file(tmp_path: Path, fired: int = 1) -> Path:
    p = tmp_path / "p2_near_miss.json"
    GC.write_json(p, {"fired": fired, "n": 20})
    return p


@pytest.fixture
def pinned(tmp_path, monkeypatch, f2ok):
    """f2ok plus the P2 record, the backend pins and a tmp prereg whose log holds every sha256 §4.5 names."""
    p2 = p2_file(tmp_path)
    monkeypatch.setattr(R, "P2_RESULT", p2)
    monkeypatch.setattr(GC, "backend_pins", lambda: dict(f2ok.backend))
    monkeypatch.setattr(GC, "trigger_pins", lambda: dict(f2ok.trigger))
    pre = tmp_path / "prereg.md"
    pre.write_text("# 規格\n\n## 執行紀錄\n\n" + "\n".join(f"- {GC.sha256_file(p)}" for p in (f2ok.qf, f2ok.order, f2ok.man, p2))
                   + "\n", encoding="utf-8")
    return SimpleNamespace(**vars(f2ok), pre=pre, p2=p2)


@needs_store
def test_pin_problems_pass_and_name_each_broken_pin(pinned, monkeypatch):
    """§4.5 (RUN-2 R7, R17, R36; RUN-9a; RUN-1): each broken pin is named alone."""
    def got():
        return R.pin_problems(pinned.pre, group=pinned.group)
    assert got() == []
    monkeypatch.setattr(GC, "backend_pins", lambda: {"backend/x.py": "c" * 64})
    assert got() == ["F1 manifest: backend/x.py is not the F1 manifest's"]
    monkeypatch.setattr(GC, "backend_pins", lambda: dict(pinned.backend))
    monkeypatch.setattr(GC, "trigger_pins", lambda: {"packages/syn/x.py": "u" * 64})   # D15: the trigger's files too
    assert got() == ["F1 manifest: packages/syn/x.py is not the F1 manifest's"]
    monkeypatch.setattr(GC, "trigger_pins", lambda: {})
    assert got() == ["F1 manifest: packages/syn/x.py is in the F1 manifest, not among the frozen files now"]
    monkeypatch.setattr(GC, "trigger_pins", lambda: dict(pinned.trigger))
    pinned.rule.write_text("x = 2\n", encoding="utf-8")                          # a rule file changed after F1
    assert got() == ["F1 manifest: syn/gencard/a.py is not the F1 manifest's"]
    pinned.rule.write_text("x = 1\n", encoding="utf-8")
    GC.write_json(pinned.gn, {"syn": 2})
    assert got() == ["F1 manifest: out/gen_names.json is not the F1 manifest's"]
    GC.write_json(pinned.gn, {"syn": 1})
    pool_sha = GC.POOL_SHA256
    monkeypatch.setattr(GC, "POOL_SHA256", "0" * 64)
    assert got() == ["pool.json is not the pinned one"]
    monkeypatch.setattr(GC, "POOL_SHA256", pool_sha)
    assert got() == []
    GC.write_json(pinned.order, {"f1_manifest_sha256": "0" * 64, "order": ORDER})
    with pinned.pre.open("a", encoding="utf-8") as f:
        f.write(f"- {GC.sha256_file(pinned.order)}\n")
    assert got() == ["order.json was drawn from another F1 manifest"]
    GC.write_json(pinned.p2, {"fired": 1, "n": 19})
    assert got()[1:] == ["the P2 near-miss record is not {fired: k, n: 20}",
                         "the P2 near-miss record's sha256 is not in the log"]
    pinned.pre.write_text("# 規格\n\n## 執行紀錄\n", encoding="utf-8")
    out = got()
    assert "the F1 manifest's sha256 is not in the log" in out
    assert {"order.json missing or its sha256 not in the log", "questions_frozen.json missing or its sha256 not in the log"} <= set(out)


def test_f2_problems_name_each_broken_f2(f2ok, built):
    """§8.1-10 (RUN-2 R34, R35): f2.json of these questions and this manifest, K-a and parity passed, the build's prompts."""
    _doc, b = built
    sha = A.prompts_sha256(b["jobs"])
    assert R.f2_problems(prompts_sha=sha) == [] and R.f2_problems() == []
    assert R.f2_problems(prompts_sha="0" * 64) == ["the build's prompts are not the ones F2's parity checked"]
    f2 = GC.read_json(f2ok.f2)
    for change, why in (({"questions_frozen_sha256": "0" * 64}, "f2.json is of other questions"),
                        ({"f1_manifest_sha256": "0" * 64}, "f2.json names another F1 manifest"),
                        ({"K_a": {"pass": False, "sentence": "停"}}, "K-a stopped the line: 停"),
                        ({"parity": {"pass": False}}, "prompt parity failed")):
        GC.write_json(f2ok.f2, {**f2, **change})
        assert R.f2_problems(prompts_sha=sha) == [why]
    f2ok.f2.unlink()
    assert R.f2_problems() == ["no f2.json (F2 steps 5–7)"]


def test_the_p2_record_is_read_from_the_store_only(tmp_path):
    """§8.1-5, §9 release clause (RUN-1): {fired: k, n: 20}, its sha256 in the log; no command-line override."""
    pre, p2 = tmp_path / "prereg.md", tmp_path / "p2_near_miss.json"
    pre.write_text("# 規格\n\n## 執行紀錄\n", encoding="utf-8")
    assert R.p2_problems(p2, pre) == ["no P2 near-miss record (store qset/p2_near_miss.json, §8.1-5)"]
    GC.write_json(p2, {"fired": 2, "n": 20})
    assert R.p2_problems(p2, pre) == ["the P2 near-miss record's sha256 is not in the log"]
    with pytest.raises(SystemExit, match="P2"):
        R.p2_near_miss(p2, pre)
    pre.write_text(f"# 規格\n\n## 執行紀錄\n\n- P2 {GC.sha256_file(p2)}\n", encoding="utf-8")
    assert R.p2_problems(p2, pre) == [] and R.p2_near_miss(p2, pre) == (2, 20)
    for bad in ({"fired": 1, "n": 1000}, {"fired": 21, "n": 20}, {"fired": "1", "n": 20}, {"fired": True, "n": 20},
                {"n": 20}, [1, 20]):
        GC.write_json(p2, bad)
        pre.write_text(f"# 規格\n\n## 執行紀錄\n\n- P2 {GC.sha256_file(p2)}\n", encoding="utf-8")
        assert R.p2_problems(p2, pre) == ["the P2 near-miss record is not {fired: k, n: 20}"]
    for argv in (["analyze", "--p2-near-miss", "1/20"], ["analyze", "--p2-near-miss=0/1000"]):
        with pytest.raises(SystemExit):
            R.main(argv)


def test_gate_problems_collects_every_section(built, pinned, root, tmp_path, monkeypatch):
    doc, _b = built
    R.build(src=src_of(doc), **QUIET)
    monkeypatch.setattr(R, "load_sources", lambda: src_of(doc))
    monkeypatch.setattr(R, "inputs_sha", lambda: {n: GC.sha256_file(R.store(n)) for n in (*R.DATA_FILES, R.F3_FILE)})
    hp = {"v": {"files_sha256": {"a.py": "1"}, "sha256": "h1"}}
    monkeypatch.setattr(F1, "harness_pins", lambda *a, **k: hp["v"])
    monkeypatch.setattr(F1, "HARNESS_RECORD", tmp_path / "harness_record.json")
    F1.record_k0(prereg=pinned.pre, git=lambda: [], tests=lambda: [])
    stubs = ((F1, "git_problems"), (R, "stage0_problems"), (R, "pin_problems"))
    for mod, name in stubs:
        monkeypatch.setattr(mod, name, lambda *a, **k: [])
    monkeypatch.setattr(R.X.c_common, "frozen_mismatches", lambda: [])
    monkeypatch.setattr(R, "metric_version", lambda: GC.METRIC_VERSION)
    assert R.gate_problems(prereg=pinned.pre) == []
    monkeypatch.setattr(R, "metric_version", lambda: "000000000000")
    assert R.gate_problems(prereg=pinned.pre) == ["metric_version 000000000000 is not 4d0826bb8d14"]
    monkeypatch.setattr(R, "metric_version", lambda: GC.METRIC_VERSION)
    for mod, name in stubs:
        monkeypatch.setattr(mod, name, lambda *a, _n=name, **k: [f"{_n} failed"])
        assert R.gate_problems(prereg=pinned.pre) == [f"{name} failed"]
        monkeypatch.setattr(mod, name, lambda *a, **k: [])
    monkeypatch.setattr(R.X.c_common, "frozen_mismatches", lambda: ["cards_common.py"])
    assert R.gate_problems(prereg=pinned.pre) == ["experiment A frozen: cards_common.py"]
    monkeypatch.setattr(R.X.c_common, "frozen_mismatches", lambda: [])
    hp["v"] = {"files_sha256": {"a.py": "2"}, "sha256": "h2"}                        # RUN-2 R22: the real record
    assert R.gate_problems(prereg=pinned.pre) == ["the harness differs from its record (K0 or the last logged change)"]
    hp["v"] = {"files_sha256": {"a.py": "1"}, "sha256": "h1"}
    f2 = GC.read_json(pinned.f2)
    GC.write_json(pinned.f2, {**f2, "prompts_sha256": "0" * 64})
    assert R.gate_problems(prereg=pinned.pre) == ["the build's prompts are not the ones F2's parity checked"]
    GC.write_json(pinned.f2, f2)
    assert R.gate_problems("2026-10-22 未記錄的修正說明", prereg=pinned.pre) == [
        "--infra-fix: the anchor is not the harness record's last change (harness-change --anchor first)",
        "--infra-fix resumes a formal run and there is none"]
    card_problems = A.card_problems
    monkeypatch.setattr(R.A, "card_problems", lambda *a, **k: {"S00": ["x"]})            # RUN-2 R25
    assert R.gate_problems(prereg=pinned.pre) == ["the F3 checks fail on a fresh build"]
    monkeypatch.setattr(R.A, "card_problems", card_problems)
    assert R.gate_problems(prereg=pinned.pre) == []
    other = frozen_doc(override={ABST: NO_CUE.format(x=NAME["G05.00"], y=NAME["G05.02"])})
    monkeypatch.setattr(R, "load_sources", lambda: src_of(other))
    assert any("a fresh build differs" in p for p in R.gate_problems(prereg=pinned.pre))


@needs_store
def test_stage0_problems_and_metric_version_hold_now():
    assert R.stage0_problems() == []
    assert R.metric_version() == GC.METRIC_VERSION
    assert R.stage0_problems(Path("/nonexistent/run_meta.json")) == ["stage-0's formal run_meta.json missing"]


def test_stage0_problems_name_a_failing_pin_and_a_changed_harness(tmp_path, monkeypatch):
    """§4.5 (RUN-2 R20): stage-0's input pins and its harness against its formal run's record."""
    rec = tmp_path / "run_meta.json"
    GC.write_json(rec, {"harness": {"files_sha256": R.X.harness_files_sha256()}})
    monkeypatch.setattr(R.X, "check_pins", lambda: ["missing syn.json"])
    assert R.stage0_problems(rec) == ["stage-0 pin: missing syn.json"]
    GC.write_json(rec, {"harness": {"files_sha256": {**R.X.harness_files_sha256(), "x.py": "0"}}})
    assert R.stage0_problems(rec)[1:] == ["stage-0 harness differs from its formal run: ['x.py']"]


# ---------------------------------------------------------------- build, the smoke and the dry run, end to end
def test_build_writes_f3_and_refuses_a_differing_rebuild_or_a_formal_run(built, f2ok, root):
    doc, _b = built
    f3 = R.build(src=src_of(doc), **QUIET)
    assert f3["pass"] and set(f3["sha256"]) == set(R.DATA_FILES) and f3["measures"]["n"] == len(doc["questions"])
    assert R.load_inputs()[R.F3_FILE] == f3
    R.build(src=src_of(doc), **QUIET)                                        # the same build: rewritten as is
    other = frozen_doc(skip=("S04",))
    with pytest.raises(SystemExit, match="differ"):
        R.build(src=src_of(other), **QUIET)
    (root / "formal").mkdir()
    (root / "formal" / R.RUN_META).write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="formal run exists"):
        R.build(src=src_of(doc), **QUIET)
    (root / "items.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not the file f3.json names"):
        R.load_inputs()


def test_build_refuses_before_f2_or_on_failing_f3_checks_and_writes_nothing(built, f2ok, root, monkeypatch):
    """§5.5 (RUN-9b): gencard first runs on frozen questions in F2; F3 (RUN-2 R28): a failing check writes nothing."""
    doc, _b = built
    f2 = GC.read_json(f2ok.f2)
    seen = []
    monkeypatch.setattr(R, "build_docs", lambda src, _f=R.build_docs: seen.append(1) or _f(src))
    f2ok.f2.unlink()
    with pytest.raises(SystemExit, match="no f2.json"):
        R.build(src=src_of(doc), **QUIET)
    assert seen == [] and list(root.iterdir()) == []                        # the rule never ran on the questions
    for change, why in (({"K_a": {"pass": False, "sentence": "停"}}, "K-a stopped"),
                        ({"prompts_sha256": "0" * 64}, "prompts are not the ones")):
        GC.write_json(f2ok.f2, {**f2, **change})
        with pytest.raises(SystemExit, match=why):
            R.build(src=src_of(doc), **QUIET)
        assert list(root.iterdir()) == []
    GC.write_json(f2ok.f2, f2)
    monkeypatch.setattr(R.A, "card_problems", lambda *a, **k: {"S00": ["x"]})
    with pytest.raises(SystemExit, match="F3 checks failed"):
        R.build(src=src_of(doc), **QUIET)
    assert list(root.iterdir()) == []


def test_dry_run_end_to_end_on_a_synthetic_frozen_set(built, f2ok, tmp_path, monkeypatch):
    doc, b = built
    run = tmp_path / "run"
    monkeypatch.setattr(R, "RUN_ROOT", run)
    R.build(src=src_of(doc), **QUIET)
    rep = R.dry_run(**QUIET)
    assert rep["fake_expectation"] and rep["missing_jobs"] == 0 and rep["fake_calls"] == len(b["jobs"])
    assert rep["analyze"]["dry_run"] and rep["analyze"]["result"] == "dry_run:H1、H2 皆過"
    r = GC.read_json(run / "dry_run" / "report.json")
    assert r["verdict"]["sentence"].startswith(R.AG.DRY_RUN) and f"寫到第 {len(POOL)} 位" in r["verdict"]["facts"]
    assert r["sequence"]["H1"]["n"] == len(doc["questions"]) and r["sequence"]["H2"]["tested"]
    assert r["measurements"]["rule"]["abstained"] == [ABST] and (run / "dry_run" / "report.md").is_file()
    sc = GC.read_json(run / "dry_run" / "scores.json")
    assert SG.frac(sc["items"][ABST]["mean"]["G"]) == SG.frac(sc["items"][ABST]["mean"]["B0"]) == 0
    assert R.dry_run(**QUIET)["fake_expectation"]                          # replaced each time
    GC.write_json(run / "smoke" / R.RUN_META, {"kind": "smoke"})
    with pytest.raises(SystemExit, match="smoke is never scored"):
        R.scored_dir(run / "smoke")


def test_analyze_splits_the_failed_slots_by_the_freeze_json_beside_its_run_root(tmp_path, monkeypatch):
    """§9 (D24, review M1): analyze reads HO's freeze.json beside its run root (OUT_ROOT/ho/freeze.json for the
    store's run root): 「3 次都失敗」 only for why attempts, the other failed whys by their labels, one 「沒寫成」 count
    without it; a freeze.json of other questions refuses, and one in the store's place never reaches a tmp run."""
    skip = (pick("F1", 2), pick("F5", 0))
    doc = frozen_doc(skip=skip)
    frozen_env(tmp_path, monkeypatch, doc, A.build(doc, POOL, L, GEN, syn_item, order=ORDER))
    run = tmp_path / "run"
    monkeypatch.setattr(R, "RUN_ROOT", run)
    R.build(src=src_of(doc), **QUIET)

    def facts() -> str:
        R.dry_run(**QUIET)
        return GC.read_json(run / "dry_run" / GC.RUN_REPORT)["verdict"]["facts"]
    other = {"questions_frozen_sha256": "f" * 64, "counts": {"failed_by_why": {"attempts": 2}}}
    GC.write_json(GC.HO_ROOT / GC.FREEZE_FILE, other)                 # the store's place (tmp here, the autouse fixture)
    f = facts()
    assert "沒寫成 2" in f and "3 次都失敗" not in f
    assert R.freeze_file() == run.parent / "ho" / "freeze.json" and R.freeze_file() != GC.HO_ROOT / GC.FREEZE_FILE
    sha = R.load_inputs()[GC.RUN_ITEMS]["questions_frozen_sha256"]
    GC.write_json(R.freeze_file(), {"questions_frozen_sha256": sha, "counts": {"failed_by_why": {"attempts": 1, "post_kay": 1}}})
    f = facts()
    assert "3 次都失敗 1" in f and "Kay 之後沒過 1" in f and "沒寫成" not in f and "爭議後沒過" not in f
    GC.write_json(R.freeze_file(), other)
    with pytest.raises(SystemExit, match="other questions"):
        R.dry_run(**QUIET)


class Flaky:
    """The fake chat of the dry run, raising for one user text while ``fail`` is set."""

    def __init__(self, inner, user: str | None = None):
        self.inner, self.user, self.calls = inner, user, 0

    def __call__(self, system, user, options=None):
        self.calls += 1
        if user == self.user:
            raise urllib.error.URLError("connection reset")
        return self.inner(system, user, options)


def test_run_does_the_canary_then_the_formal_run_and_scores_it(built, f2ok, tmp_path, monkeypatch):
    doc, b = built
    monkeypatch.setattr(R, "RUN_ROOT", tmp_path / "run")
    R.build(src=src_of(doc), **QUIET)
    for mod, name in ((R, "gate_problems"), (SM, "smoke_problems"), (F1, "git_problems"), (F1, "harness_problems")):
        monkeypatch.setattr(mod, name, lambda *a, **k: [])
    monkeypatch.setattr(SM, "smoke_version", lambda: GC.OLLAMA_VERSION)
    jobs = R.load_inputs()["jobs.json"]
    chat = R.FakeChat(jobs, b["items"], b["meta"])
    args = SimpleNamespace(infra_fix=None, canary_fixed=None)
    flaky = Flaky(chat, jobs[4]["user"])
    with pytest.raises(SystemExit, match="canary not passed"):
        R.run(args, get=Api(), chat=flaky, **QUIET)
    d = R.store("formal")
    st = GC.read_json(d / R.CANARY_FILE)
    assert not st["pass"] and st["errors"] == 3 and st["missing"] == [jobs[4]["job_id"]] and flaky.calls == 32
    with pytest.raises(SystemExit, match="canary not passed"):                    # the old error lines still count
        R.run(args, get=Api(), chat=chat, **QUIET)
    meta = R.run(SimpleNamespace(infra_fix=None, canary_fixed="已重啟 Ollama"), get=Api(), chat=chat, **QUIET)
    st = GC.read_json(d / R.CANARY_FILE)
    assert st["pass"] and st["ignored_errors"] == 3 and len(st["history"]) == 3 and st["note"] == "已重啟 Ollama"
    assert meta["state"] == "ok" and meta["missing"] == [] and meta["n_done"] == len(jobs)
    assert len(meta["checks"]) == 6           # 3 sessions: the fixed canary had nothing left to run, then the rest
    with pytest.raises(SystemExit, match="canary has passed"):
        R.run(SimpleNamespace(infra_fix=None, canary_fixed="x"), get=Api(), chat=chat, **QUIET)
    sc = R.score(SimpleNamespace(out=None, jobs_unrecoverable=False))
    assert sc["missing_jobs"] == [] and sc["run"]["kind"] == "formal"
    assert sc["run"]["harness"]["changed_since_run"] == []
    pre = tmp_path / "prereg.md"
    pre.write_text("# 規格\n\n## 執行紀錄\n", encoding="utf-8")
    monkeypatch.setattr(F1, "PREREG", pre)
    monkeypatch.setattr(R, "P2_RESULT", p2_file(tmp_path, fired=2))
    with pytest.raises(SystemExit, match="P2"):                              # RUN-1: the store record, logged
        R.analyze(SimpleNamespace(out=None, jobs_unrecoverable=False))
    pre.write_text(f"# 規格\n\n## 執行紀錄\n\n- P2 {GC.sha256_file(R.P2_RESULT)}\n", encoding="utf-8")
    rep = R.analyze(SimpleNamespace(out=None, jobs_unrecoverable=False))
    assert rep["verdict"]["result"] == "H1、H2 皆過" and not rep["dry_run"] and (d / "report.md").is_file()
    assert rep["measurements"]["f2_agrees"] is True and rep["inputs"]["gen_checked"] and rep["p2_near_miss"] == [2, 20]
    assert rep["verdict"]["release_clause"] and rep["verdict"]["sentence"].endswith("不談 prod 接線")
    f2 = GC.read_json(f2ok.f2)
    GC.write_json(f2ok.f2, {**f2, "K_a": {"pass": False, "sentence": "停"}})
    with pytest.raises(SystemExit, match="K-a stopped"):
        R.analyze(SimpleNamespace(out=None, jobs_unrecoverable=False))
    GC.write_json(f2ok.f2, f2)
    monkeypatch.setattr(F1, "harness_problems", lambda *a, **k: ["the harness differs from its record"])   # RUN-5
    for cmd in (R.score, R.analyze):
        with pytest.raises(SystemExit, match="harness"):
            cmd(SimpleNamespace(out=None, jobs_unrecoverable=False))
    monkeypatch.setattr(F1, "harness_problems", lambda *a, **k: [])
    monkeypatch.setattr(F1, "git_problems", lambda *a, **k: ["harness files changed or untracked since the last commit"])
    with pytest.raises(SystemExit, match="harness"):
        R.score(SimpleNamespace(out=None, jobs_unrecoverable=False))


def test_score_and_analyze_refuse_another_build_missing_jobs_or_other_scores(root, monkeypatch):
    """§4.5 (RUN-2 R31, RUN-3 R9, R30)."""
    d, js = root / "dry_run", fake_jobs(3)
    R.execute(d, js, "dry_run", chat=Chat(fail_users={"假問題1"}), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="jobs missing"):
        R.scored_dir(d)
    assert R.scored_dir(d, jobs_unrecoverable=True)[0] == d
    monkeypatch.setattr(R, "inputs_sha", lambda: {"items.json": "y"})
    with pytest.raises(SystemExit, match="not the one this run used"):
        R.scored_dir(d, jobs_unrecoverable=True)
    monkeypatch.setattr(R, "inputs_sha", lambda: {"items.json": "x"})
    GC.write_json(d / "scores.json", {"run": {"jobs_sha256": "0" * 64}})
    with pytest.raises(SystemExit, match="not this run's"):
        R.analyze(SimpleNamespace(out=d, jobs_unrecoverable=True))


def test_cli_flags(monkeypatch, capsys):
    """Each flag is its commands' only, and --redo and --void-truncated exclude each other (review m05): argparse
    refuses with its message before any command runs."""
    for cmd in R.CMDS:
        monkeypatch.setitem(R.CMDS, cmd, lambda _a: pytest.fail("a refused command line ran its command"))
    cases = {("build", "--out", "x"): "--out is for score and analyze only",
             ("run", "--anchor", "x"): "--anchor is for harness-change only",
             ("smoke", "--infra-fix", "x"): "--infra-fix is for run only",
             ("score", "--canary-fixed", "x"): "--canary-fixed is for run only",
             ("build", "--jobs-unrecoverable"): "--jobs-unrecoverable is for score and analyze only",
             ("run", "--redo", "x"): "--redo is for smoke only", ("analyze", "--p2-near-miss", "1/20"): "unrecognized",
             ("run", "--void-truncated", "x"): "--void-truncated is for smoke only",
             ("smoke", "--redo", "x", "--void-truncated", "y"): "--redo and --void-truncated exclude each other"}
    for argv, why in cases.items():
        with pytest.raises(SystemExit) as e:
            R.main(list(argv))
        assert e.value.code == 2 and why in capsys.readouterr().err, argv


# ---------------------------------------------------------------- F1 manifest
@pytest.fixture
def f1(tmp_path):
    store, repo = tmp_path / "store", GC.REPO
    gn, cli = store / "out/gen_names.json", store / "out/cli_pin.json"
    GC.write_json(gn, {"syn": 1})
    GC.write_json(cli, {"claude": "9.9.9"})
    group = F1.f1a_paths(store=store, gen_names=gn)
    own = F1.own_paths(store=store, cli_pin=cli)
    f1a = tmp_path / "f1a_pins.json"
    GC.write_json(f1a, {"files": F1.sha_map(group)})
    return SimpleNamespace(store=store, group=group, own=own, f1a=f1a, out=tmp_path / "f1_manifest.json", gn=gn,
                           backend={"backend/x.py": "b" * 64, **F1.kept_pins()}, git=lambda ps: [], repo=repo)


def test_f1_manifest_holds_the_groups_and_seeds_the_order_without_a_timestamp(f1):
    doc = F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, f1.backend, f1.repo, f1.git)
    keys = set(doc["files"])
    assert keys == set(f1.group) | set(f1.own) | set(f1.backend)
    assert {"out/gen_names.json", "out/cli_pin.json", "backend/x.py"} <= keys
    assert any(k.endswith("/gencard/card.py") for k in keys) and any(k.endswith("/mech_g.py") for k in keys)
    assert any(k.endswith("/gen_g.md") for k in keys) and any(k.endswith("/banned_g.py") for k in keys)
    assert all(isinstance(v, str) and len(v) == 64 for v in doc["files"].values())
    assert O.files_digest(GC.read_json(f1.out)) == doc["files_digest"] and "t" in doc and "t" not in doc["files"]
    assert F1.manifest_problems(doc["files"], {**F1.sha_map({**f1.group, **f1.own}), **f1.backend}) == []
    with pytest.raises(SystemExit, match="written once"):
        F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, f1.backend, f1.repo, f1.git)


def test_f1_manifest_is_refused_when_the_f1a_pins_differ(f1):
    pins = GC.read_json(f1.f1a)["files"]
    cases = {"sha256 differs": {**pins, "out/gen_names.json": "0" * 64},
             "not in f1a_pins.json": {k: v for k, v in pins.items() if not k.endswith("/mech_g.py")},
             "not in the F1a group now": {**pins, "extra/gencard/x.py": "1" * 64}}
    for why, files in cases.items():
        GC.write_json(f1.f1a, {"files": files})
        with pytest.raises(SystemExit, match=why):
            F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, f1.backend, f1.repo, f1.git)
        assert not f1.out.exists()
    GC.write_json(f1.f1a, {"nofiles": 1})
    with pytest.raises(SystemExit, match="no files map"):
        F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, f1.backend, f1.repo, f1.git)
    GC.write_json(f1.f1a, {"files": pins})
    with pytest.raises(SystemExit, match="not committed"):
        F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, f1.backend, f1.repo, lambda ps: ["x.py"])
    with pytest.raises(SystemExit, match="clash"):
        F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, {"out/cli_pin.json": "0" * 64}, f1.repo, f1.git)
    with pytest.raises(SystemExit, match="missing"):
        F1.write_manifest(f1.out, f1.f1a, f1.group, {**f1.own, "extra.md": f1.store / "none.md"}, f1.backend, f1.repo, f1.git)


def test_f1_manifest_refuses_a_prod_pin_g_common_keeps_at_another_value(f1):
    """§4.3, §4.5 (D15, review M2): F2 step 3 (freeze_g.prod_trigger) needs the manifest's r4 layer and trigger files
    at the sha256 g_common keeps, so a manifest of another or no value could never pass it: F1 refuses it."""
    kept = F1.kept_pins()
    assert set(kept) == {str(GC.R4_LAYER.relative_to(GC.STORE)), *GC.TRIGGER_PINS_SHA256} and len(kept) == 7
    for key in kept:
        for backend in ({**f1.backend, key: "d" * 64}, {k: v for k, v in f1.backend.items() if k != key}):
            with pytest.raises(SystemExit, match=f"prod pin {re.escape(key)} is not the sha256 g_common keeps"):
                F1.write_manifest(f1.out, f1.f1a, f1.group, f1.own, backend, f1.repo, f1.git)
            assert not f1.out.exists()


def test_manifest_problems_name_each_changed_missing_or_extra_file():
    files = {"a.py": "1", "b.json": "2"}
    assert F1.manifest_problems(files, {"a.py": "1", "b.json": "2"}) == []
    assert F1.manifest_problems(files, {"a.py": "9", "b.json": None, "c.py": "3"}) == [
        "a.py is not the F1 manifest's", "b.json is not the F1 manifest's", "c.py is not the F1 manifest's"]
    assert F1.manifest_problems(files, {"a.py": "1"}) == ["b.json is in the F1 manifest, not among the frozen files now"]
    assert set(F1.frozen_paths()) == set(F1.f1a_paths()) | set(F1.own_paths())


# ---------------------------------------------------------------- F2 steps 5–7
@pytest.fixture
def f2env(tmp_path, built):
    doc, b = built
    qf, man, out, pre = (tmp_path / n for n in ("questions_frozen.json", "f1_manifest.json", "f2.json", "prereg.md"))
    GC.write_json(qf, doc)
    group = {"syn/gencard/a.py": tmp_path / "a.py"}
    group["syn/gencard/a.py"].write_text("x = 1\n", encoding="utf-8")
    pins = {F2.GENERATOR: GC.sha256_file(GC.REPO / F2.GENERATOR), "backend/y.py": "y" * 64}
    GC.write_json(man, {"files": {**F1.sha_map(group), **pins}})
    pre.write_text(f"# 規格\n\n## 執行紀錄\n\n### {F2_OLD}\n\n- questions_frozen.json {GC.sha256_file(qf)}\n",
                   encoding="utf-8")
    calls = []

    def gate(a, w, idx):
        calls.append((a, w, idx))
        return {"pow_H1_and_H2": 0.81, "pass": True}
    kw = dict(out=out, frozen_path=qf, manifest_path=man, prereg=pre, src=src_of(doc), gate=gate, pins=lambda: dict(pins),
              group=group)
    return SimpleNamespace(kw=kw, calls=calls, out=out, b=b, doc=doc, pre=pre, pins=pins, man=man, group=group, qf=qf)


def broken_messages(q, c, aux):
    return [{"role": "system", "content": "別的"}, {"role": "user", "content": ""}]


def test_f2_measures_gates_checks_parity_and_writes_once(f2env):
    doc = F2.run_f2(**f2env.kw)
    n = len(f2env.doc["questions"])
    m = doc["measures"]
    assert (m["n"], m["a_meas"]["k"], m["w_meas"]["k"], m["R_trig"]["k"], m["R_seed"]["k"]) == (n, n - 2, 1, n - 1, n - 2)
    assert m["abstained"] == [ABST] and len(doc["per_question"]) == n
    (a, w, idx), = f2env.calls
    index = {s["sid"]: i for i, s in enumerate(POOL)}
    assert (a, w) == ((n - 2) / n, 1 / n) and idx == sorted(index[q["sid"]] for q in f2env.doc["questions"])
    assert doc["K_a"]["pass"] and doc["K_a"]["sentence"] is None and doc.get("void") is None
    par = doc["parity"]
    assert par["pass"] and par["n_checked"] == sum(j["arm"] in ("G", "T-rows") for j in f2env.b["jobs"])
    assert doc["prompts_sha256"] == A.prompts_sha256(f2env.b["jobs"]) and f2env.out.is_file()
    assert set(F2.counts(doc)) >= {"a_meas", "w_meas", "R_trig", "R_seed", "K_a_pass"}
    with pytest.raises(SystemExit, match="recorded once"):
        F2.run_f2(**f2env.kw)


def test_f2_k_a_stop_is_written_with_its_sentence_on_the_frozen_n(f2env):
    """§5.6 K-a (RUN-3 X5): n is the frozen questions', a strict subset of the pool here."""
    sub = frozen_doc(skip=(pick("F1", 0), pick("F5", 0)))
    GC.write_json(f2env.qf, sub)
    f2env.pre.write_text(f"# 規格\n\n## 執行紀錄\n\n- {GC.sha256_file(f2env.qf)}\n", encoding="utf-8")
    kw = dict(f2env.kw, src=src_of(sub), gate=lambda a, w, idx: {"pow_H1_and_H2": 0.612, "pass": False})
    doc = F2.run_f2(**kw)
    n, a = len(sub["questions"]), doc["measures"]["a_meas"]["float"]
    assert n == len(POOL) - 2 and doc["measures"]["n"] == n
    assert not doc["K_a"]["pass"] and doc["K_a"]["sentence"] == (
        f"依事先規則停止（K-a：a＝{a:.3f}，n＝{n}，檢定力＝0.612），不構成無效證據；盲集未跑")


def test_f2_refusals_write_nothing(f2env):
    f2env.pre.write_text("# 規格\n\n## 執行紀錄\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="執行紀錄"):
        F2.run_f2(**f2env.kw)
    f2env.pre.write_text("x\n\n## 執行紀錄\n- " + GC.sha256_file(f2env.kw["frozen_path"]) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="backend pin"):
        F2.run_f2(**dict(f2env.kw, pins=lambda: {**f2env.pins, "backend/y.py": "z" * 64}))
    calls = []

    def drifting():                                   # RUN-2 F2b: backend_pins() checked again after parity
        calls.append(1)
        return dict(f2env.pins) if len(calls) == 1 else {**f2env.pins, "backend/y.py": "z" * 64}
    with pytest.raises(SystemExit, match="backend pins"):
        F2.run_f2(**dict(f2env.kw, pins=drifting, build_messages=cc_messages))
    f2env.group["syn/gencard/a.py"].write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="differs from the F1 manifest"):
        F2.run_f2(**f2env.kw)
    f2env.group["syn/gencard/a.py"].write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="parity mismatches"):
        F2.run_f2(**dict(f2env.kw, build_messages=broken_messages))

    def system_only(q, c, aux):                       # RUN-2 X9: the right user message under another system prompt
        return [{"role": "system", "content": "別的系統提示"}, {"role": "user", "content": cc.build_user(c, q, aux)}]
    with pytest.raises(SystemExit, match="parity mismatches"):
        F2.run_f2(**dict(f2env.kw, build_messages=system_only))
    with pytest.raises(SystemExit, match="missing"):
        F2.run_f2(**dict(f2env.kw, frozen_path=f2env.out.parent / "none.json"))
    with pytest.raises(SystemExit, match=r"missing \(F1\)"):                         # RUN-3 X12
        F2.run_f2(**dict(f2env.kw, manifest_path=f2env.out.parent / "none.json"))
    assert not f2env.out.exists()


def cc_messages(q, c, aux):
    return [{"role": "system", "content": cc.SYSTEM_PROMPT}, {"role": "user", "content": cc.build_user(c, q, aux)}]


def test_f2_writes_a_void_only_for_a_parity_failure_under_a_new_logged_anchor(f2env, monkeypatch):
    """§8.1-10.7 (RUN-10, D6): a parity failure only cards_common or prod could fix is 作廢 before any Ollama call:
    f2.json with parity failed, then void_g's one record beside it, the record run_g checks (D5: the same file)."""
    kw, void = dict(f2env.kw, build_messages=broken_messages), F2.void_path(f2env.out)
    assert void == f2env.out.parent / "void.json" and F2.void_path(F2.OUT) == GC.VOID_FILE
    for bad in (F2_OLD, "不在紀錄裡的一行錨點文字", "2026"):
        with pytest.raises(SystemExit, match="anchor"):
            F2.run_f2(**kw, void_anchor=bad)
    with f2env.pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {F2_VOID}\n")
    with pytest.raises(SystemExit, match="parity passes"):
        F2.run_f2(**dict(f2env.kw, build_messages=cc_messages), void_anchor=F2_VOID)
    assert not f2env.out.exists() and not void.exists()
    doc = F2.run_f2(**kw, void_anchor=F2_VOID)
    assert not doc["parity"]["pass"] and doc["parity"]["mismatch"] and "void" not in doc and GC.read_json(f2env.out) == doc
    rec = V.read(void)
    assert (rec["why"], rec["anchor"], rec["label"]) == ("parity", F2_VOID, "prompt 對等")
    assert rec["sentence"] == "作廢（prompt 對等），不構成任何方向的證據" and rec["detail"]["f2_sha256"] == GC.sha256_file(f2env.out)
    with pytest.raises(SystemExit, match="recorded once"):
        F2.run_f2(**kw, void_anchor=F2_VOID)
    f2env.out.unlink()
    again = "2026-10-24 再一次對等不過的紀錄行"
    with f2env.pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {again}\n")
    with pytest.raises(SystemExit, match="the line is void"):                    # a void is recorded once
        F2.run_f2(**kw, void_anchor=again)
    monkeypatch.setattr(R, "RUN_ROOT", f2env.out.parent / "run")                  # run_g reads the same record
    assert R.void_file() == void
    assert V.problems(R.void_file()) == [f"the line is void (prompt 對等; void.json): {rec['sentence']}"]


def add_void_line(f2env) -> str:
    with f2env.pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {F2_VOID}\n")
    return F2_VOID


def test_f2_writes_the_void_first_and_a_failed_write_leaves_nothing_or_a_void_line(f2env, monkeypatch):
    """§8.1-10.7 (review m08): both paths are checked writable, then the void record is written before f2.json: a
    refused or failed void write leaves nothing (F2 can run again), a failed f2.json write after it a void line."""
    kw, void = dict(f2env.kw, build_messages=broken_messages, void_anchor=add_void_line(f2env)), F2.void_path(f2env.out)
    real_writable, real_write = GC.writable, GC.write_json

    def refuse(name):
        def writable(p):
            if Path(p).name == name:
                raise SystemExit(f"{name}: refused (test)")
            return real_writable(p)
        return writable

    def fail_on(name):
        def write_json(p, obj):
            if Path(p).name == name:
                raise OSError("disk full (test)")
            return real_write(p, obj)
        return write_json
    for attr, fake, err in (("writable", refuse(void.name), SystemExit), ("writable", refuse(f2env.out.name), SystemExit),
                            ("write_json", fail_on(void.name), OSError)):
        with monkeypatch.context() as m:
            m.setattr(GC, attr, fake)
            with pytest.raises(err):
                F2.run_f2(**kw)
        assert not f2env.out.exists() and not void.exists(), attr
    with monkeypatch.context() as m:
        m.setattr(GC, "write_json", fail_on(f2env.out.name))
        with pytest.raises(OSError):
            F2.run_f2(**kw)
    assert not f2env.out.exists() and V.read(void)["why"] == "parity" and V.problems(void)        # void: fail closed


def test_f2_main_prints_the_void_sentence_and_exits_1(f2env, monkeypatch, capsys):
    """§8.1-10.7 (review m06): ``f2_g.py`` prints the counts and exits 0 after a passing F2; ``--void-anchor A``
    records the void, prints its sentence (read back from the record beside f2.json) and exits 1."""
    real = F2.run_f2
    monkeypatch.setattr(F2, "OUT", f2env.out)
    monkeypatch.setattr(F2, "run_f2", lambda **k: real(**{**f2env.kw, **k}))
    assert F2.main([]) == 0 and "作廢" not in capsys.readouterr().out
    f2env.out.unlink()
    monkeypatch.setattr(F2, "run_f2", lambda **k: real(**{**f2env.kw, "build_messages": broken_messages, **k}))
    assert F2.main(["--void-anchor", add_void_line(f2env)]) == 1
    assert V.sentence("parity") in capsys.readouterr().out.splitlines()
    assert V.read(F2.void_path(f2env.out))["anchor"] == F2_VOID


@needs_store
def test_f2_compares_the_prod_pins_with_the_manifest_by_default(f2env):
    """§4.3, §4.5 (D15, review m02): without ``pins`` F2 compares f1_g.prod_pins() (backend_pins() and the
    trigger's trigger_pins()) with the F1 manifest: a manifest whose trigger file or lexicon differs refuses."""
    pins = F1.prod_pins()
    kw = {k: v for k, v in f2env.kw.items() if k != "pins"}
    for key in ("packages/ragcommon/routing.py", str(GC.ROUTING_LEXICON.relative_to(GC.STORE))):
        GC.write_json(f2env.man, {"files": {**F1.sha_map(f2env.group), **pins, key: "0" * 64}})
        with pytest.raises(SystemExit, match=f"backend pin {re.escape(key)} differs from the F1 manifest"):
            F2.run_f2(**kw)
        assert not f2env.out.exists()


def test_backend_build_messages_is_the_aux_prompt_of_cards_common():
    bm = F2.backend_build_messages(want_sha=GC.sha256_file(GC.REPO / F2.GENERATOR))
    ctx, q, aux = "[1] 某書 第5章\n假經文", "依創世記，某甲幾歲？", "某甲：九十歲生某乙"
    assert bm(q, ctx, aux) == cc_messages(q, ctx, aux)
    assert bm(q, ctx, None)[0]["content"] != cc.SYSTEM_PROMPT                # no card: prod's ordinary prompt
    with pytest.raises(SystemExit, match="pinned"):
        F2.backend_build_messages(want_sha="0" * 64)


@needs_store
def test_f2_on_the_real_pool_with_questions_built_from_the_layer_names(tmp_path):
    """Code-built template questions on every real slot without a required marker; the real gate and parity. An
    exception is reported by its type and message only: a long traceback would print frame arguments that hold
    the questions built from real names."""
    try:
        _real_pool_f2(tmp_path)
    except AssertionError:
        raise
    except (Exception, SystemExit) as e:
        pytest.fail(f"{type(e).__name__}: {e}", pytrace=False)


def _real_pool_f2(tmp_path: Path) -> None:
    pool = GC.read_json(GC.POOL)["pool"]
    Lr = gencard.parse(GC.read_json(GC.GEN_LAYER), GC.read_json(GC.GEN_NAMES))
    keep = [s for s in pool if not s["marker_required"]]
    qs = [{"sid": s["sid"], "question": T[s["qtype"]].format(x=Lr.name[s["x"]], y=Lr.name[s["y"]])} for s in keep]
    att = {c: [] for c in A.ATTRITION}
    att["failed"] = [s["sid"] for s in pool if s["marker_required"]]
    doc = {"schema": A.FROZEN_SCHEMA, "n_target": len(pool), "questions": qs, "attrition": att}
    order = [s["sid"] for s in pool][::-1]
    qf, man, out, pre = (tmp_path / n for n in ("questions_frozen.json", "f1_manifest.json", "f2.json", "prereg.md"))
    GC.write_json(qf, doc)
    GC.write_json(man, {"files": {**F1.sha_map(F2.frozen_group()), **F1.prod_pins()}})
    pre.write_text(f"# 規格\n\n## 執行紀錄\n- {GC.sha256_file(qf)}\n", encoding="utf-8")
    src = SimpleNamespace(frozen=doc, pool=pool, gen=A.S.gen_layer.load(), L=Lr, item_of=A.stage0_item, order=order)
    res = F2.run_f2(out=out, frozen_path=qf, manifest_path=man, prereg=pre, src=src)
    m, n = res["measures"], len(keep)
    assert n == len(pool) - 6 and (m["a_meas"]["k"], m["w_meas"]["k"], m["R_seed"]["k"]) == (n, 0, n)
    assert res["parity"]["pass"] and res["parity"]["n_items"] == n and res["K_a"]["pass"]
    assert res["K_a"]["slot_idx"] == [i for i, s in enumerate(pool) if not s["marker_required"]]
    contexts = {mm for mm in (q["context_from"] for q in A.build(doc, pool, Lr, src.gen, order=order)["items"])}
    assert contexts == {"ps:gen.5.1", "ps:gen.11.10"}
