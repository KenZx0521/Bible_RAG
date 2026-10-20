"""Ordered-chain arithmetic stage-0 driver (run_x.py; prereg §1 跑前跑後、重做與缺漏、截斷 smoke, §6 K0, §11).

Ollama is never called: every chat is a fake (passed to ``execute`` or put in place of cards_common.chat
with monkeypatch) and every /api/ps, /api/tags, /api/version answer comes from a fake ``get``. The output
root (x_common.OUT_ROOT) is a temporary directory in every test, so nothing is written to the store or the
repository. The synthetic jobs and items are made up; the store-backed tests (the whole build → dry run →
smoke → formal run → score → analyze flow, with the Ollama gate replaced) build the real items in memory
from the read-only store and skip when it is not mounted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import run_x as R  # noqa: E402
import x_common as X  # noqa: E402

EXPECTED = X.EXPECTED_DIGEST
STORE_OK = X.REF_V2.is_file() and X.R4_LAYER.is_file() and (X.TEXT / "verse_units.jsonl").is_file() and \
    (X.STORE / "reports/kg_cards_20261018/A_confirm/scores.json").is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({X.STORE})")
QUIET = {"log": lambda *_a: None}
TESTS_STUB = {"files": [], "returncode": 0, "summary": "stub", "pass": True}


class Api:
    """A fake Ollama: /api/ps, /api/tags, /api/version; change its fields to change its answers."""

    def __init__(self, digest=EXPECTED, version="0.1.0", loaded=True, others=(), down=False):
        self.digest, self.version, self.loaded, self.others, self.down = digest, version, loaded, list(others), down

    def __call__(self, path: str) -> dict:
        if self.down:
            raise urllib.error.URLError("refused")
        if path == "/api/version":
            return {"version": self.version} if self.version else {}
        mine = [{"name": X.MODEL, "model": X.MODEL, "digest": self.digest}]
        if path == "/api/ps":
            return {"models": (mine if self.loaded else []) + [{"name": o, "digest": "f" * 64} for o in self.others]}
        return {"models": mine}


class Chat:
    """Counts calls; raises URLError for a user text while its fail count lasts; on_call(n) runs before answering."""

    def __init__(self, fail=None, on_call=None, done_reason="stop"):
        self.calls, self.fail, self.on_call, self.done_reason = 0, dict(fail or {}), on_call, done_reason

    def __call__(self, system, user, options=None):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls)
        if self.fail.get(user, 0) > 0:
            self.fail[user] -= 1
            raise urllib.error.URLError("connection reset")
        return {"content": "推理略。\n答案：1年", "thinking_chars": 0, "prompt_eval_count": 10, "eval_count": 5,
                "done_reason": self.done_reason, "elapsed_s": 0.0}


def jobs(n: int = 3, tag: str = "") -> list[dict]:
    return [{"job_id": f"X|I{i}|G|1", "exp": "X", "item": f"I{i}", "family": "DYN", "arm": "G", "rep": 1,
             "kind": "gen", "system": "系統甲", "user": f"假問題{tag}{i}"} for i in range(n)]


@pytest.fixture
def root(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(X, "OUT_ROOT", out)
    for n in (*R.DATA_FILES, R.K0_FILE):
        (out / n).write_text("{}\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- Ollama checks
def test_ollama_check_reads_ps_then_tags_and_the_version():
    c = R.ollama_check(Api(), "before")
    assert (c["digest"], c["where"], c["version"], c["others"]) == (EXPECTED, "ps", "0.1.0", [])
    c = R.ollama_check(Api(loaded=False), "before")
    assert (c["digest"], c["where"]) == (EXPECTED, "tags")
    assert R.ollama_check(Api(others=["other:7b"]), "before")["others"] == ["other:7b"]
    c = R.ollama_check(Api(down=True), "after")
    assert (c["digest"], c["version"], c["others"]) == (None, None, None)
    assert R.ollama_check(Api(version=None), "before")["version"] is None


def test_before_problems():
    assert R.before_problems(R.ollama_check(Api(), "before")) == []
    assert R.before_problems(R.ollama_check(Api(loaded=False), "before")) == []          # §9: empty /api/ps is fine
    assert any("digest" in p for p in R.before_problems(R.ollama_check(Api(digest="0" * 64), "before")))
    assert any("version" in p for p in R.before_problems(R.ollama_check(Api(version=None), "before")))
    assert any("not ours alone" in p for p in R.before_problems(R.ollama_check(Api(others=["x:1b"]), "before")))
    assert len(R.before_problems(R.ollama_check(Api(down=True), "before"))) == 3


def test_run_state():
    b = {"when": "before", "t": "t0", "digest": EXPECTED, "version": "1"}
    a = dict(b, when="after", t="t1")
    assert R.run_state({"checks": [b, a]}) == ("ok", [])
    assert R.run_state({"checks": []})[0] == "unfinished" and R.run_state({"checks": [b]})[0] == "unfinished"
    assert R.run_state({"checks": [b, dict(a, digest=None)]})[0] == "unknown"
    assert R.run_state({"checks": [b, dict(a, digest=None), b, a]})[0] == "ok"           # resumed and checked again
    assert R.run_state({"checks": [b, dict(a, digest="f" * 64), b, a]})[0] == "void"
    state, why = R.run_state({"checks": [b, dict(a, version="2")]})
    assert state == "void" and "version" in why[0]


def test_report_segments_pair_each_start_with_the_next_observation():
    b = {"when": "before", "t": "t0", "digest": EXPECTED, "version": "1"}
    a = dict(b, when="after", t="t1")
    segs = R.report_segments({"kind": "formal", "checks": [b, dict(b, t="t2", version="2"), a]})
    assert [(s["version_before"], s["version_after"]) for s in segs] == [("1", "2"), ("2", "1")]
    lost = dict(a, digest=None, version=None)                     # Ollama did not answer the after-check
    segs = R.report_segments({"kind": "formal", "checks": [b, lost, dict(b, t="t3"), dict(a, t="t4")]})
    assert [(s["digest_after"], s["version_after"], s["t_after"]) for s in segs] == [(EXPECTED, "1", "t3"),
                                                                                      (EXPECTED, "1", "t4")]
    assert R.report_segments({"kind": "formal", "checks": [b, lost]})[0]["digest_after"] is None
    assert R.report_segments({"kind": "dry_run", "checks": [b, a]}) == [
        {"digest_before": EXPECTED, "digest_after": EXPECTED, "version_before": "1", "version_after": "1",
         "t_before": "t0", "t_after": "t1", "dry_run": True}]


# ---------------------------------------------------------------- execute: resume, guards, retries, void
def test_execute_runs_resumes_and_guards(root):
    d, js, chat = root / "dry_run", jobs(), Chat()
    meta = R.execute(d, js, "dry_run", chat=chat, get=Api(), **QUIET)
    assert chat.calls == 3 and meta["state"] == "ok" and meta["missing"] == [] and meta["n_done"] == 3
    assert X.read_json(d / "jobs.json") == js and meta["options"] == X.OPTIONS and meta["model"] == X.MODEL
    again = Chat()
    meta = R.execute(d, js, "dry_run", chat=again, get=Api(), **QUIET)
    assert again.calls == 0 and meta["resumed"] == [] and len(meta["checks"]) == 2     # nothing to do: no session
    assert meta == X.read_json(d / R.RUN_META)
    with pytest.raises(SystemExit, match="not smoke"):
        R.execute(d, js, "smoke", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="differ"):
        R.execute(d, jobs(tag="乙"), "dry_run", chat=Chat(), get=Api(), **QUIET)
    (root / "items.json").write_text('{"changed": 1}\n', encoding="utf-8")       # the store build changed
    with pytest.raises(SystemExit, match="differ"):
        R.execute(d, js, "dry_run", chat=Chat(), get=Api(), **QUIET)
    (root / "smoke").mkdir()
    (root / "smoke" / R.GEN).write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="without"):
        R.execute(root / "smoke", js, "smoke", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="writes only under"):
        R.execute(root.parent / "elsewhere", js, "dry_run", chat=Chat(), get=Api(), **QUIET)


def test_formal_uses_cards_common_chat_and_pins_the_harness(root, monkeypatch):
    chat = Chat()
    monkeypatch.setattr(X.cc, "chat", chat)
    meta = R.execute(root / "formal", jobs(), "formal", get=Api(), **QUIET)
    assert chat.calls == 3 and meta["kind"] == "formal" and meta["harness"] == R.harness_pins()
    monkeypatch.setattr(R, "harness_pins", lambda: {"files_sha256": {}, "sha256": "other"})
    with pytest.raises(SystemExit, match="harness"):
        R.execute(root / "formal", jobs(), "formal", get=Api(), **QUIET)


def test_an_ollama_exception_is_retried_in_a_later_round(root):
    js = jobs()
    chat = Chat(fail={js[1]["user"]: 1})
    meta = R.execute(root / "dry_run", js, "dry_run", chat=chat, get=Api(), **QUIET)
    assert chat.calls == 4 and meta["missing"] == [] and meta["error_lines"] == 1 and meta["state"] == "ok"
    recs = X.jsonl(root / "dry_run" / R.GEN)
    assert [r["round"] for r in recs if r["type"] == "answer" and r["job_id"] == js[1]["job_id"]] == [1]


def test_jobs_missing_after_three_rounds_are_reported_and_resumed(root):
    js = jobs()
    chat = Chat(fail={js[2]["user"]: 5})
    meta = R.execute(root / "dry_run", js, "dry_run", chat=chat, get=Api(), **QUIET)
    assert meta["missing"] == [js[2]["job_id"]] and meta["error_lines"] == 3 and meta["n_done"] == 2
    again = Chat()
    meta = R.execute(root / "dry_run", js, "dry_run", chat=again, get=Api(), **QUIET)     # after the infra fix
    assert again.calls == 1 and meta["missing"] == []


def test_a_digest_or_version_change_voids_the_run_and_blocks_resume(root):
    api = Api()
    chat = Chat(on_call=lambda n: setattr(api, "version", "0.2.0") if n == 2 else None)
    meta = R.execute(root / "dry_run", jobs(), "dry_run", chat=chat, get=api, **QUIET)
    assert meta["state"] == "void" and "version" in meta["void"][0]
    with pytest.raises(SystemExit, match="void"):
        R.execute(root / "dry_run", jobs(), "dry_run", chat=Chat(), get=Api(version="0.2.0"), **QUIET)
    api2 = Api()
    chat2 = Chat(on_call=lambda n: setattr(api2, "digest", "e" * 64))
    meta = R.execute(root / "other", jobs(), "dry_run", chat=chat2, get=api2, **QUIET)
    assert meta["state"] == "void" and "digest" in meta["void"][0]


@pytest.mark.parametrize("api", [Api(digest="0" * 64), Api(others=["other:1b"]), Api(version=None), Api(down=True)])
def test_refused_before_any_call(root, api):
    chat = Chat()
    with pytest.raises(SystemExit, match="refused before any call"):
        R.execute(root / "dry_run", jobs(), "dry_run", chat=chat, get=api, **QUIET)
    assert chat.calls == 0 and not (root / "dry_run" / R.GEN).exists() and not (root / "dry_run" / R.RUN_META).exists()


def _crash_at(n: int):
    """A Chat on_call that kills the session (KeyboardInterrupt, not an Ollama error) at call n."""
    def on_call(k):
        if k == n:
            raise KeyboardInterrupt
    return on_call


def test_a_no_op_rerun_opens_no_session_even_on_another_ollama_version(root):
    d, js = root / "smoke", jobs()
    R.execute(d, js, "smoke", chat=Chat(), get=Api(), **QUIET)
    done = X.read_json(d / R.RUN_META)
    again = Chat()
    meta = R.execute(d, js, "smoke", chat=again, get=Api(version="0.9.9"), **QUIET)    # Ollama updated afterwards
    assert again.calls == 0 and meta == done == X.read_json(d / R.RUN_META) and R.run_state(meta) == ("ok", [])


def test_a_crashed_session_resumes_and_its_after_check_is_the_next_one(root):
    d, js = root / "smoke", jobs()
    with pytest.raises(KeyboardInterrupt):
        R.execute(d, js, "smoke", chat=Chat(on_call=_crash_at(2)), get=Api(), **QUIET)
    assert [c["when"] for c in X.read_json(d / R.RUN_META)["checks"]] == ["before"]
    chat = Chat()
    meta = R.execute(d, js, "smoke", chat=chat, get=Api(), **QUIET)
    assert chat.calls == 2 and meta["missing"] == [] and meta["state"] == "ok"
    assert [c["when"] for c in meta["checks"]] == ["before", "before", "after"]


@pytest.mark.parametrize("api", [Api(version="0.2.0"), Api(digest="e" * 64)])
def test_a_differing_check_after_a_closed_session_is_refused_and_not_recorded(root, api):
    d, js = root / "smoke", jobs()
    meta = R.execute(d, js, "smoke", chat=Chat(fail={js[2]["user"]: 5}), get=Api(), **QUIET)
    assert meta["missing"] == [js[2]["job_id"]] and meta["state"] == "ok"
    chat = Chat()
    with pytest.raises(SystemExit, match="refused before any call.*restore"):
        R.execute(d, js, "smoke", chat=chat, get=api, **QUIET)
    assert chat.calls == 0 and X.read_json(d / R.RUN_META) == meta
    meta = R.execute(d, js, "smoke", chat=chat, get=Api(), **QUIET)                   # model and version restored
    assert chat.calls == 1 and meta["missing"] == [] and meta["state"] == "ok" and len(meta["checks"]) == 4


def _unclosed(root, d, js):
    with pytest.raises(KeyboardInterrupt):                                            # killed during call 2
        R.execute(d, js, "smoke", chat=Chat(on_call=_crash_at(2)), get=Api(), **QUIET)


def _unknown(root, d, js):
    api = Api()
    meta = R.execute(d, js, "smoke", chat=Chat(on_call=lambda n: setattr(api, "down", n == 3)), get=api, **QUIET)
    assert R.run_state(meta)[0] == "unknown"                                          # the after-check got no answer


@pytest.mark.parametrize("make", [_unclosed, _unknown])
@pytest.mark.parametrize("api", [Api(version="0.2.0"), Api(digest="e" * 64)])
def test_a_differing_check_standing_in_for_a_missing_after_check_voids_the_run(root, make, api):
    d, js = root / "smoke", jobs()
    make(root, d, js)
    n = len(X.read_json(d / R.RUN_META)["checks"])
    chat = Chat()
    with pytest.raises(SystemExit, match="stands in"):
        R.execute(d, js, "smoke", chat=chat, get=api, **QUIET)
    meta = X.read_json(d / R.RUN_META)
    assert chat.calls == 0 and meta["state"] == "void" and len(meta["checks"]) == n + 1
    assert R.run_state(meta)[0] == "void" and meta["void"]
    with pytest.raises(SystemExit, match="void"):
        R.execute(d, js, "smoke", chat=chat, get=Api(), **QUIET)                      # never resumed
    assert chat.calls == 0


def test_the_formal_run_needs_the_smokes_version(root):
    chat = Chat()
    with pytest.raises(SystemExit, match="not the smoke's 0.0.9"):
        R.execute(root / "formal", jobs(), "formal", chat=chat, get=Api(), want_version="0.0.9", **QUIET)
    assert chat.calls == 0 and not (root / "formal" / R.RUN_META).exists()
    meta = R.execute(root / "formal", jobs(), "formal", chat=chat, get=Api(), want_version="0.1.0", **QUIET)
    assert chat.calls == 3 and meta["state"] == "ok"


def test_a_second_run_on_the_same_directory_is_refused(root):
    import fcntl
    d = root / "smoke"
    d.mkdir()
    with open(d / R.LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)                               # another session holds it
        chat = Chat()
        with pytest.raises(SystemExit, match="another run"):
            R.execute(d, jobs(), "smoke", chat=chat, get=Api(), **QUIET)
        assert chat.calls == 0 and not (d / R.RUN_META).exists()
    held = []

    def probe(_n):
        with open(d / R.LOCK, "a") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)
    assert R.execute(d, jobs(), "smoke", chat=Chat(on_call=probe), get=Api(), **QUIET)["state"] == "ok"
    assert held == [True, True, True]                                                 # held during the session


def test_repair_tail(root):
    p, side = root / "g.jsonl", root / "side.jsonl"
    assert R.repair_tail(p, side) is None
    for raw, fix, kept, moved in [
            (b'{"a": 1}\n', None, b'{"a": 1}\n', b""),
            (b'{"a": 1}\n{"b": 2}', {"action": "newline_added", "bytes": 8}, b'{"a": 1}\n{"b": 2}\n', b""),
            (b'{"a": 1}\n{"b": ', {"action": "moved_to_side", "bytes": 6}, b'{"a": 1}\n', b'{"b": \n'),
            (b'{"b": ', {"action": "moved_to_side", "bytes": 6}, b"", b'{"b": \n'),
            (b'{"a": 1}\n\xe7\xad', {"action": "moved_to_side", "bytes": 2}, b'{"a": 1}\n', b"\xe7\xad\n")]:
        p.write_bytes(raw)
        side.unlink(missing_ok=True)
        assert R.repair_tail(p, side) == fix
        assert p.read_bytes() == kept and (side.read_bytes() if side.exists() else b"") == moved


def test_a_torn_last_line_is_moved_aside_and_its_job_redone(root):
    d, js = root / "smoke", jobs()
    with pytest.raises(KeyboardInterrupt):
        R.execute(d, js, "smoke", chat=Chat(on_call=_crash_at(3)), get=Api(), **QUIET)
    with (d / R.GEN).open("a", encoding="utf-8") as f:
        f.write('{"type": "answer", "job_id": "' + js[2]["job_id"] + '", "content": "推')   # cut by the kill
    chat = Chat()
    meta = R.execute(d, js, "smoke", chat=chat, get=Api(), **QUIET)
    assert chat.calls == 1 and meta["missing"] == [] and meta["state"] == "ok" and len(X.jsonl(d / R.GEN)) == 3
    assert [t["action"] for t in meta["torn"]] == ["moved_to_side"] == \
        [t["action"] for t in X.read_json(d / R.RUN_META)["torn"]]
    assert (d / R.TORN).read_text(encoding="utf-8").startswith('{"type": "answer"')


def test_infra_fix_resumes_a_formal_run_on_changed_harness_files(root, monkeypatch):
    d, js = root / "formal", jobs()
    meta = R.execute(d, js, "formal", chat=Chat(fail={js[2]["user"]: 5}), get=Api(), **QUIET)
    old = meta["harness"]
    files = dict(old["files_sha256"], **{"run_x.py": "0" * 64})
    new = {"files_sha256": files, "sha256": X.sha256_text(json.dumps(files, sort_keys=True))}
    monkeypatch.setattr(R, "harness_pins", lambda: new)
    chat = Chat()
    with pytest.raises(SystemExit, match="--infra-fix"):
        R.execute(d, js, "formal", chat=chat, get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="does not exist"):
        R.execute(root / "formal_b", js, "formal", chat=chat, get=Api(), infra_fix="x", **QUIET)
    with pytest.raises(SystemExit, match="formal run only"):
        R.execute(root / "dry_run", js, "dry_run", chat=chat, get=Api(), infra_fix="x", **QUIET)
    assert chat.calls == 0 and X.read_json(d / R.RUN_META) == meta
    meta = R.execute(d, js, "formal", chat=chat, get=Api(), infra_fix="10-21 修逾時", **QUIET)
    assert chat.calls == 1 and meta["missing"] == [] and meta["state"] == "ok" and meta["harness"] == new
    (h,) = meta["harness_history"]
    assert (h["from"], h["to"], h["files"], h["note"]) == (old["sha256"], new["sha256"], ["run_x.py"], "10-21 修逾時")
    assert h["git_head"] and h["t"]
    with pytest.raises(SystemExit, match="are the run's"):
        R.execute(d, js, "formal", chat=chat, get=Api(), infra_fix="again", **QUIET)
    (root / "items.json").write_text('{"changed": 1}\n', encoding="utf-8")            # inputs still pinned
    monkeypatch.setattr(R, "harness_pins", lambda: old)
    with pytest.raises(SystemExit, match="inputs differ"):
        R.execute(d, js, "formal", chat=chat, get=Api(), infra_fix="x", **QUIET)


def test_infra_fix_problems(root, tmp_path, monkeypatch):
    pre = tmp_path / "prereg.md"
    pre.write_text("# 規格\n\n## 執行紀錄\n\n- 10-21 修逾時：只改 run_x 的逾時。\n", encoding="utf-8")
    k0 = {"sha256": {"items.json": "a"}}
    sections = ("K0_1", "K0_2", "K0_3", "K0_4", "K0_6", "items")
    good = {"pass": True, "sha256": {"items.json": "a"}, "pins": [], "frozen": [], **{s: {"pass": True} for s in sections}}
    monkeypatch.setattr(R, "k0_checks", lambda *a, **k: good)
    assert R.infra_fix_problems(pre, "10-21 修逾時", k0, {}) == [
        "--infra-fix resumes a formal run and there is none (before it starts, rerun build)"]
    (root / "formal").mkdir()
    X.write_json(root / "formal" / R.RUN_META, {"kind": "formal"})
    assert R.infra_fix_problems(pre, "10-21 修逾時", k0, {}) == []
    assert R.infra_fix_problems(pre, "規格", k0, {}) == ["--infra-fix: the anchor is not in prereg.md's 執行紀錄"]
    assert R.infra_fix_problems(pre, "  ", k0, {}) == ["--infra-fix: the anchor is not in prereg.md's 執行紀錄"]
    monkeypatch.setattr(R, "k0_checks", lambda *a, **k: {**good, "sha256": {"items.json": "b"}})
    assert R.infra_fix_problems(pre, "10-21 修逾時", k0, {}) == ["--infra-fix: a fresh K0 names other store files than k0.json"]
    monkeypatch.setattr(R, "k0_checks", lambda *a, **k: {**good, "pass": False, "K0_4": {"pass": False}})
    assert "fails ['K0_4']" in R.infra_fix_problems(pre, "10-21 修逾時", k0, {})[0]


def test_chat_as_restores_cards_common_chat():
    real = X.cc.chat
    with pytest.raises(RuntimeError):
        with R.chat_as(Chat()):
            assert X.cc.chat is not real
            raise RuntimeError
    assert X.cc.chat is real
    with R.chat_as(None):
        assert X.cc.chat is real


# ---------------------------------------------------------------- smoke
def syn_items():
    fams = {"DYN": 3, "S6": 2, "SYNC": 3, "GEN": 3}
    items, meta = [], {}
    for f, n in fams.items():
        for i in range(n):
            iid = f"{f}_{i}"
            items.append({"id": iid, "family": f})
            meta[iid] = {"user_chars": {"G": 100 + (i * 37) % 5 * 10}}
    return items, meta


def test_smoke_jobs_take_the_two_longest_g_prompts_per_family_rep_1_every_arm():
    import arms_x as A
    items, meta = syn_items()
    js = [{"job_id": A.job_id(it["id"], a, r), "item": it["id"], "arm": a, "rep": r} for it in items
          for a in A.arm_order(it["family"]) for r in range(1, X.REPS_BY_ARM[a] + 1)]
    sm = R.smoke_jobs(items, js, meta)
    picked = sorted({j["item"] for j in sm})
    assert picked == ["DYN_1", "DYN_2", "GEN_1", "GEN_2", "S6_0", "S6_1", "SYNC_1", "SYNC_2"]
    assert all(j["rep"] == 1 for j in sm) and len(sm) == 2 * (4 + 4 + 4 + 4)        # GEN: G, T-rows, B0, B0p


def test_smoke_status_and_problems(root):
    js = jobs(2)
    meta = R.execute(root / "smoke", js, "smoke", chat=Chat(), get=Api(), **QUIET)
    st = R.smoke_status(root / "smoke", js, meta)
    assert st["pass"] and not st["void"] and set(st["tokens"]) == {j["job_id"] for j in js}
    assert "content" not in json.dumps(st)                                            # token counts only
    items = [{"id": f"I{i}", "family": "DYN"} for i in range(2)]
    meta_items = {f"I{i}": {"user_chars": {"G": 10}} for i in range(2)}
    assert R.smoke_problems(items, js, meta_items) == ["no smoke yet (K0-5)"]
    X.write_json(root / "smoke" / R.SMOKE_FILE, st)
    assert R.smoke_problems(items, js, meta_items) == []
    assert R.smoke_problems(items, jobs(tag="乙"), meta_items) == ["the smoke ran other jobs"]
    X.write_json(root / "smoke" / R.SMOKE_FILE, {**st, "pass": False})
    assert "resume smoke" in R.smoke_problems(items, js, meta_items)[0]
    long = R.execute(root / "dry_run", js, "dry_run", chat=Chat(done_reason="length"), get=Api(), **QUIET)
    st2 = R.smoke_status(root / "dry_run", js, long)
    assert st2["void"] and not st2["pass"] and st2["truncated"] == sorted(j["job_id"] for j in js)
    X.write_json(root / "smoke" / R.SMOKE_FILE, st2)
    assert "voided" in R.smoke_problems(items, js, meta_items)[0]


# ---------------------------------------------------------------- gates
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True)


def test_git_problems(tmp_path):
    repo = tmp_path / "repo"
    h, t = repo / "h", repo / "t"
    h.mkdir(parents=True)
    t.mkdir()
    _git(repo, "init", "-q")
    pre = h / "prereg.md"
    pre.write_text("正式版\n", encoding="utf-8")
    (h / "a.py").write_text("x = 1\n", encoding="utf-8")
    (t / "test_arith_stage0_a.py").write_text("x = 1\n", encoding="utf-8")
    assert "prereg.md not committed" in R.git_problems(pre, h, t)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "t")
    assert R.git_problems(pre, h, t) == []
    (t / "test_other.py").write_text("y = 1\n", encoding="utf-8")                 # another experiment's test
    assert R.git_problems(pre, h, t) == []
    (t / "test_arith_stage0_b.py").write_text("y = 1\n", encoding="utf-8")        # untracked K0-4-style test
    assert R.git_problems(pre, h, t) == ["test files changed or untracked since the last commit"]
    (t / "test_arith_stage0_b.py").unlink()
    (t / "test_arith_stage0_a.py").write_text("x = 2\n", encoding="utf-8")        # edited after the commit
    assert R.git_problems(pre, h, t) == ["test files changed or untracked since the last commit"]
    _git(repo, "checkout", "-q", "--", "t/test_arith_stage0_a.py")
    (h / "b.py").write_text("y = 1\n", encoding="utf-8")
    assert R.git_problems(pre, h, t) == ["harness files changed or untracked since the last commit"]
    (h / "b.py").unlink()
    pre.write_text("改過\n", encoding="utf-8")
    assert "prereg.md changed since the last commit" in R.git_problems(pre, h, t)


def test_harness_pins_cover_the_tests_and_prereg_above_its_log(tmp_path):
    h, t = tmp_path / "h", tmp_path / "t"
    h.mkdir()
    t.mkdir()
    pre = h / "prereg.md"
    pre.write_text("# 規格\n內文\n\n## 執行紀錄\n", encoding="utf-8")
    (h / "a.py").write_text("x = 1\n", encoding="utf-8")
    (t / "test_arith_stage0_a.py").write_text("y = 1\n", encoding="utf-8")
    (t / "test_other.py").write_text("z = 1\n", encoding="utf-8")
    pins = X.harness_files_sha256(h, t)
    assert set(pins) == {"a.py", "prereg.md", "tests/test_arith_stage0_a.py"}
    assert pins["prereg.md"] == X.sha256_text("# 規格\n內文\n")
    pre.write_text("# 規格\n內文\n\n## 執行紀錄\n\n- 修了 a.py 的逾時。\n", encoding="utf-8")     # the log grows
    assert X.harness_files_sha256(h, t) == pins
    assert X.prereg_log_text(pre.read_text(encoding="utf-8")).endswith("- 修了 a.py 的逾時。\n")
    pre.write_text("# 規格\n內文改了\n\n## 執行紀錄\n", encoding="utf-8")                      # the spec changes
    assert X.harness_files_sha256(h, t)["prereg.md"] != pins["prereg.md"]
    (t / "test_arith_stage0_a.py").write_text("y = 2\n", encoding="utf-8")
    assert X.harness_files_sha256(h, t)["tests/test_arith_stage0_a.py"] != pins["tests/test_arith_stage0_a.py"]
    real = X.harness_files_sha256()
    assert {f"tests/{Path(f).name}" for f in R.K0_TESTS} <= set(real) and "tests/test_arith_stage0_run.py" in real
    assert set(R.code_sha256()) == set(real) - {"appendix.md"}


def test_k0_tests_record_the_sha256_of_the_files_run(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="....\n== 12 passed in 3.21s ==\n", stderr="")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    out = R.k0_tests()
    assert out["pass"] and out["summary"] == "12 passed" and out["files"] == list(R.K0_TESTS)
    assert out["files_sha256"] == {f: X.sha256_file(X.REPO / f) for f in R.K0_TESTS}
    assert all(f in seen["cmd"] for f in R.K0_TESTS)


def test_gate_problems_draft_mark_and_no_build(root, tmp_path):
    pre = tmp_path / "prereg.md"
    pre.write_text(f"# {X.DRAFT_MARK}\n", encoding="utf-8")
    bad = R.gate_problems(pre)
    assert bad[0] == "prereg.md carries the draft mark" and "prereg.md not committed" in bad
    assert any("does not pass" in p for p in bad)                            # the dummy k0.json


def test_load_inputs_checks_every_file_against_k0(root):
    X.write_json(root / R.K0_FILE, {"pass": False, "sha256": {}})
    with pytest.raises(SystemExit, match="does not pass"):
        R.load_inputs()
    with pytest.raises(SystemExit, match="not the file"):
        R.load_inputs(require_pass=False)
    sha = {n: X.sha256_file(root / n) for n in R.DATA_FILES}
    X.write_json(root / R.K0_FILE, {"pass": True, "sha256": sha})
    assert set(R.load_inputs()) == {*R.DATA_FILES, R.K0_FILE}
    (root / "cards.json").write_text('{"x": 1}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="cards.json"):
        R.load_inputs()


def test_build_is_refused_while_a_formal_run_exists(root):
    (root / "formal").mkdir()
    X.write_json(root / "formal" / R.RUN_META, {"kind": "formal"})
    with pytest.raises(SystemExit, match="formal run exists"):
        R.build(run_tests=lambda: TESTS_STUB, **QUIET)


def test_scored_dir_refuses_the_smoke_an_unfinished_run_and_another_build(root):
    meta = R.execute(root / "smoke", jobs(), "smoke", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="never scored"):
        R.scored_dir(root / "smoke")
    X.write_json(root / "dry_run" / R.RUN_META, dict(meta, kind="dry_run", checks=meta["checks"][:1]))
    with pytest.raises(SystemExit, match="unfinished"):
        R.scored_dir(root / "dry_run")
    lost = [meta["checks"][0], dict(meta["checks"][1], digest=None)]                  # the after-check got no answer
    X.write_json(root / "dry_run" / R.RUN_META, dict(meta, kind="dry_run", checks=lost))
    with pytest.raises(SystemExit, match="unknown"):
        R.scored_dir(root / "dry_run", jobs_unrecoverable=True)
    X.write_json(root / "dry_run" / R.RUN_META, dict(meta, kind="dry_run", missing=["X|I0|G|1"]))
    with pytest.raises(SystemExit, match="1 jobs missing.*--jobs-unrecoverable"):
        R.scored_dir(root / "dry_run")
    assert R.scored_dir(root / "dry_run", jobs_unrecoverable=True)[1]["missing"] == ["X|I0|G|1"]
    X.write_json(root / "dry_run" / R.RUN_META, dict(meta, kind="dry_run"))
    with pytest.raises(SystemExit, match="no job is missing"):
        R.scored_dir(root / "dry_run", jobs_unrecoverable=True)
    assert R.scored_dir(root / "dry_run")[1]["kind"] == "dry_run"
    (root / "jobs.json").write_text("[]\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not the one"):
        R.scored_dir(root / "dry_run")
    with pytest.raises(SystemExit, match="not a run directory"):
        R.scored_dir(root / "nothing")


def test_k0_for_report_and_pilot_args():
    k0 = {f"K0_{n}": {"pass": True} for n in (1, 2, 4, 6)}
    k0["K0_3"] = {"pass": False, "dynasty": {"pass": True}, "genesis": {"pass": False}}
    out = R.k0_for_report(k0, None, "formal")
    assert out["K0-3"] == {"pass": True, "dyn": True, "gen": False} and out["K0-5"]["pass"] is False
    import analyze_x
    assert analyze_x.k0_voids(out) == {"DYN": ["K0-5"], "S6": ["K0-5"], "SYNC": ["K0-5"], "GEN": ["K0-3", "K0-5"]}
    assert R.k0_for_report(k0, None, "dry_run")["K0-5"]["pass"] is True
    assert R.k0_for_report(k0, {"pass": True, "void": False}, "formal")["K0-5"] == {"pass": True}
    assert R.k0_for_report(k0, {"pass": False, "void": True}, "formal")["K0-5"] == {"pass": False}
    assert R.pilot_args(None, None) == (None, None)
    assert R.pilot_args("DYN=yes,GEN=no", None)[0] == {"DYN": True, "GEN": False}
    with pytest.raises(SystemExit):
        R.pilot_args("S6=yes", None)


def test_cli_flags_and_paths(root):
    with pytest.raises(SystemExit):
        R.main(["build", "--out", str(root / "x")])
    with pytest.raises(SystemExit):
        R.main(["score", "--pilot-authorized", "DYN=yes"])
    with pytest.raises(SystemExit, match="writes only under"):
        R.main(["score", "--out", str(root.parent / "elsewhere")])
    for argv in (["run", "--jobs-unrecoverable"], ["smoke", "--jobs-unrecoverable"], ["score", "--infra-fix", "x"],
                 ["smoke", "--infra-fix", "x"]):
        with pytest.raises(SystemExit) as e:
            R.main(argv)
        assert e.value.code == 2, argv                                                 # argparse refuses the flag


# ---------------------------------------------------------------- the fake chat
def test_fake_chat_answers_the_covering_line_for_g_and_a_wrong_value_otherwise():
    import engine_x as E
    it = {"id": "S5_x", "gold": 76, "keys": [{"type": "arith", "value": 76, "classes": ["Y"]}],
          "distractors": [{"value": 41, "kind": "component"}]}
    card = {"lines": [["", "王甲到王丙之間王位交接2次"], ["王甲到王丙合計", "76年"]],
            "tags": [{"kind": "handover", "value": 2, "unit": "C"}, {"kind": "sum", "value": 76, "unit": "Y"}]}
    assert R.covering_line(it, card) == E.line_text("王甲到王丙合計", "76年")
    assert R.wrong_answer(it) == "41年" and R.wrong_answer(dict(it, distractors=[])) == "77年"
    age = dict(it, keys=[{"type": "arith", "value": 76, "classes": ["A", "Y"]}])
    assert R.wrong_answer(age) == "41歲"
    js = [{"item": "S5_x", "arm": "G", "user": "甲"}, {"item": "S5_x", "arm": "T-rows", "user": "乙"}]
    chat = R.FakeChat(js, [it], {"S5_x": card})
    assert chat("s", "甲")["content"].endswith("答案：王甲到王丙合計：76年")
    assert chat("s", "乙")["content"].endswith("答案：41年") and chat("s", "丙")["content"].endswith("無法判斷")
    assert chat.calls == 3


# ---------------------------------------------------------------- the store build, end to end (fakes)
@pytest.fixture
def built(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(X, "OUT_ROOT", out)
    k0 = R.build(run_tests=lambda: TESTS_STUB, **QUIET)
    return out, k0


@needs_store
def test_store_build_and_its_refusals(built):
    out, k0 = built
    assert k0["pass"] and k0["K0_3"]["dynasty"]["a"] == "34/34" and k0["K0_3"]["genesis"]["a"] == "18/18"
    assert k0["K0_4"]["regress_a"]["gained_items"] == R.K0_4_GAINED and k0["K0_4"]["copy_cases"]["mismatch"] == {}
    assert k0["K0_6"]["block_chars_max"]["G"] <= X.CAP_CHARS and k0["K0_6"]["job_problems"] == []
    inp = R.load_inputs()
    assert len(inp["jobs.json"]) == 588 and inp["items.json"]["n_items"] == 52
    assert R.build(run_tests=lambda: TESTS_STUB, **QUIET)["sha256"] == k0["sha256"]         # same build: no-op
    doc = X.read_json(out / "items.json")
    X.write_json(out / "items.json", dict(doc, seed=1))
    with pytest.raises(SystemExit, match="differ from this build"):
        R.build(run_tests=lambda: TESTS_STUB, **QUIET)
    X.write_json(out / "items.json", doc)
    failing = dict(TESTS_STUB, **{"pass": False})
    with pytest.raises(SystemExit, match="K0 failed"):
        R.build(run_tests=lambda: failing, **QUIET)
    assert X.read_json(out / R.K0_FILE)["pass"] is False                                       # k0.json records it


@needs_store
def test_store_dry_run_smoke_formal_score_analyze(built, monkeypatch):
    out, _ = built
    rep = R.dry_run(nsim=10, **QUIET)
    assert rep["fake_expectation"] and rep["fake_calls"] == 588 and rep["missing_jobs"] == 0
    assert rep["analyze"]["dry_run"] is True and set(rep["analyze"]["sentences"]) == {"DYN", "GEN"}
    assert {"report.json", "report.md", "scores.json", "dry_run_report.json"} <= {p.name for p in (out / "dry_run").iterdir()}
    with pytest.raises(SystemExit, match="refused"):
        R.smoke(get=R.fake_get, **QUIET)                         # the real gate: uncommitted harness, no appendix …
    monkeypatch.setattr(R, "gate_problems", lambda *a, **k: [])
    inp = R.load_inputs()
    chat = R.FakeChat(inp["jobs.json"], inp["items.json"]["items"], inp["cards.json"]["cards"])
    monkeypatch.setattr(X.cc, "chat", chat)
    with pytest.raises(SystemExit, match="no smoke yet"):
        R.run(get=R.fake_get, **QUIET)
    st = R.smoke(get=R.fake_get, **QUIET)
    assert st["pass"] and st["n_jobs"] == 32 and chat.calls == 32
    with pytest.raises(SystemExit, match="never scored"):
        R.score(argparse.Namespace(out=out / "smoke"))
    with pytest.raises(SystemExit, match="not the smoke's fake"):
        R.run(get=Api(version="0.9.9"), **QUIET)                                       # Ollama updated after the smoke
    assert chat.calls == 32 and not (out / "formal" / R.RUN_META).exists()
    meta = R.run(get=R.fake_get, **QUIET)
    assert meta["n_done"] == 588 and meta["state"] == "ok" and chat.calls == 32 + 588
    assert R.run(get=Api(version="0.9.9"), **QUIET) == meta                            # nothing to do: no session
    assert chat.calls == 620
    sc = R.score(argparse.Namespace(out=None))
    assert sc["run"]["kind"] == "formal" and sc["n_records"] == 588
    assert sc["run"]["gen_sha256"] == X.sha256_file(out / "formal" / R.GEN) and sc["run"]["jobs_unrecoverable"] is False
    an = argparse.Namespace(out=None, pilot_authorized=None, pilot=None)
    gen = out / "formal" / R.GEN
    keep = gen.read_bytes()
    gen.write_bytes(keep + keep.splitlines(keepends=True)[-1])                       # generations changed after score
    with pytest.raises(SystemExit, match="not this run's"):
        R.analyze(an, nsim=10)
    gen.write_bytes(keep)
    rr = R.analyze(an, nsim=10)
    assert rr["dry_run"] is False and rr["run"]["kind"] == "formal"
    assert (out / "formal" / "report.md").is_file()
    with pytest.raises(SystemExit, match="formal run exists"):
        R.build(run_tests=lambda: TESTS_STUB, **QUIET)


@needs_store
def test_store_infra_fix_gate_runs_a_fresh_k0_in_place_of_the_harness_pin(built, tmp_path, monkeypatch):
    out, k0 = built
    pre = tmp_path / "prereg.md"
    pre.write_text("# 規格\n\n## 執行紀錄\n\n- 10-21 修逾時。\n", encoding="utf-8")
    docs = R.build_docs()
    stub = {"run_tests": lambda: TESTS_STUB}
    assert R.infra_fix_problems(pre, "10-21 修逾時", k0, docs, **stub) == [
        "--infra-fix resumes a formal run and there is none (before it starts, rerun build)"]   # same store files
    monkeypatch.setattr(R, "code_sha256", lambda: {"run_x.py": "0" * 64})              # the harness was fixed
    plain = R.gate_problems(pre, **stub)
    assert "k0.json was built with other harness files: rerun build" in plain
    fixed = R.gate_problems(pre, "10-21 修逾時", **stub)
    assert "k0.json was built with other harness files: rerun build" not in fixed
    assert "--infra-fix resumes a formal run and there is none (before it starts, rerun build)" in fixed
    failing = dict(TESTS_STUB, **{"pass": False})
    assert any("fresh K0" in p for p in R.gate_problems(pre, "10-21 修逾時", run_tests=lambda: failing))


@needs_store
def test_store_smoke_truncation_voids_the_experiment(built, monkeypatch):
    out, _ = built
    monkeypatch.setattr(R, "gate_problems", lambda *a, **k: [])
    monkeypatch.setattr(X.cc, "chat", Chat(done_reason="length"))
    st = R.smoke(get=R.fake_get, **QUIET)
    assert st["void"] and not st["pass"] and len(st["truncated"]) == 32
    with pytest.raises(SystemExit, match="voided"):
        R.smoke(get=R.fake_get, **QUIET)
    with pytest.raises(SystemExit, match="voided"):
        R.run(get=R.fake_get, **QUIET)
