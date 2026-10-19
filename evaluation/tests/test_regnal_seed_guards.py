"""Rule-seed regression harness: the runner's and the CLI's guards (prereg.md §4, §6, §10).

Ollama is never called: every chat and /api/ps here is a fake, and the CLI tests replace
``rs_run.real_chat`` and ``rs_run.api_get`` with fakes before ``run_rs.main`` runs. The output
root (rs_common.OUT_ROOT) is a temporary directory in the CLI tests, so nothing is written to
the store. The synthetic layer and questions come from regnal_seed_helpers.
"""

import http.client
import json
import subprocess
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from regnal_seed_helpers import (EXPECTED, RS, CountingChat, fake_api, formal_prereg, make_syn, never,
                                 small_jobs)

import a4_card_check as A4  # noqa: E402
import rs_common as C  # noqa: E402
import rs_jobs as J  # noqa: E402
import rs_run as R  # noqa: E402
import rs_score as S  # noqa: E402
import run_rs  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
QUIET = {"log": lambda *_a: None}


@pytest.fixture
def syn(tmp_path):
    return make_syn(tmp_path)


# ---------------------------------------------------------------- the model digest
def test_digest_check():
    assert R.model_digest(fake_api()) == (EXPECTED, "ps")
    assert R.model_digest(fake_api(ps_has_model=False, tags_digest=EXPECTED)) == (EXPECTED, "tags")
    assert R.model_digest(fake_api(ps_has_model=False)) == (None, None)

    def down(path):
        raise urllib.error.URLError("refused")
    assert R.model_digest(down) == (None, None)
    before, after = {"when": "before", "digest": EXPECTED}, {"when": "after", "digest": EXPECTED}
    other, unknown = dict(after, digest="f" * 64), dict(after, digest=None)
    state = lambda checks, **kw: R.digest_state({"digest_checks": checks, **kw})  # noqa: E731
    assert state([before, after]) == "ok" and R.digest_ok({"digest_checks": [before, after]})
    assert state([]) == "unfinished" and state([before]) == "unfinished"      # never checked after the run
    assert state([before, unknown, before]) == "unfinished"                   # resumed, not finished yet
    assert state([before, other]) == "mismatch" and state([before, other, before, after]) == "mismatch"
    assert state([before, unknown]) == "unknown"                              # Ollama did not answer
    assert state([before, unknown, before, after]) == "ok"                    # resumed: checked again
    fake = [dict(before, fake=True), dict(after, fake=True)]
    assert state(fake) == "fake" and state(fake, dry_run=True) == "ok"
    assert not R.digest_ok({"digest_checks": [before, unknown]})


def test_a_wrong_digest_refuses_before_any_call(tmp_path):
    chat = CountingChat()
    with pytest.raises(SystemExit, match="digest"):
        R.execute(small_jobs(), tmp_path / "o", chat, fake_api(ps_digest="0" * 64), **QUIET)
    with pytest.raises(SystemExit, match="digest"):
        R.execute(small_jobs(), tmp_path / "o", chat, fake_api(ps_has_model=False), **QUIET)
    assert chat.calls == 0 and not (tmp_path / "o" / R.GEN).exists()


# ---------------------------------------------------------------- resume, other jobs, errors
def test_an_interrupted_run_is_unfinished_and_resumed_in_place(tmp_path):
    out, jobs = tmp_path / "o", small_jobs()
    with pytest.raises(KeyboardInterrupt):
        R.execute(jobs, out, CountingChat(fail_after=4), fake_api(), **QUIET)
    assert len(R.done_ids(out / R.GEN)) == 4
    assert R.digest_state(C.read_json(out / R.RUN_META)) == "unfinished"
    with pytest.raises(SystemExit, match="mismatch"):          # not a digest mismatch: no rerun
        R.execute(jobs, tmp_path / "o2", CountingChat(), fake_api(), rerun_of=out, **QUIET)
    chat = CountingChat()
    meta = R.execute(jobs, out, chat, fake_api(), **QUIET)
    assert chat.calls == 2 and meta["n_done"] == 6 and meta["n_errors"] == 0
    assert meta["jobs_sha256"] == J.jobs_sha256(jobs) and meta["options"] == C.OPTIONS
    assert (meta["digest_before"], meta["digest_after"], meta["attempt"]) == (EXPECTED, EXPECTED, 1)
    assert meta["resumed"] and R.digest_state(meta) == "ok"
    again = CountingChat()
    R.execute(jobs, out, again, fake_api(), **QUIET)
    assert again.calls == 0
    recs = [json.loads(line) for line in (out / R.GEN).read_text(encoding="utf-8").splitlines()]
    assert all(r["type"] == "answer" for r in recs) and {r["job_id"] for r in recs} == {j["job_id"] for j in jobs}


def test_other_jobs_in_the_same_directory_are_refused(tmp_path):
    out, jobs = tmp_path / "o", small_jobs()
    R.execute(jobs, out, CountingChat(), fake_api(), **QUIET)
    changed = [dict(jobs[0], user="other")] + jobs[1:]
    with pytest.raises(SystemExit, match="jobs"):
        R.execute(changed, out, CountingChat(), fake_api(), **QUIET)
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / R.GEN).write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="run_meta"):
        R.execute(jobs, bare, CountingChat(), fake_api(), **QUIET)


def test_errors_are_recorded_never_retried_and_three_in_a_row_stop(tmp_path):
    out, jobs = tmp_path / "o", small_jobs()
    chat = CountingChat(error=urllib.error.URLError("refused"))
    with pytest.raises(SystemExit, match="consecutive"):
        R.execute(jobs, out, chat, fake_api(), **QUIET)
    assert chat.calls == R.MAX_CONSECUTIVE_ERRORS
    assert R.digest_state(C.read_json(out / R.RUN_META)) == "unfinished"      # stopped, not void
    ok = CountingChat()
    meta = R.execute(jobs, out, ok, fake_api(), **QUIET)
    assert ok.calls == len(jobs) - R.MAX_CONSECUTIVE_ERRORS      # the errored jobs are not run again
    assert meta["n_errors"] == R.MAX_CONSECUTIVE_ERRORS
    parse, p = CountingChat(error=ValueError("bad json")), tmp_path / "other" / "p"   # another parent: a new run
    with pytest.raises(SystemExit, match="consecutive"):
        R.execute(jobs, p, parse, fake_api(), **QUIET)
    assert len(R.error_lines(p / R.GEN)) == R.MAX_CONSECUTIVE_ERRORS


@pytest.mark.parametrize("error", [http.client.IncompleteRead(b""), http.client.BadStatusLine("x"),
                                   http.client.RemoteDisconnected("x")])
def test_an_http_error_is_an_error_line_and_never_called_again(tmp_path, error):
    out, jobs = tmp_path / "o", small_jobs(4)
    chat = CountingChat(error=error, raise_at=2)
    meta = R.execute(jobs, out, chat, fake_api(), **QUIET)
    assert chat.calls == 4 and meta["n_errors"] == 1 and meta["n_done"] == 3
    assert [e["job_id"] for e in R.error_lines(out / R.GEN)] == [jobs[1]["job_id"]]
    again = CountingChat()
    R.execute(jobs, out, again, fake_api(), **QUIET)
    assert again.calls == 0


# ---------------------------------------------------------------- dry runs, reruns, a second run
def test_a_formal_run_never_takes_a_dry_run_directory_nor_the_reverse(tmp_path):
    jobs = small_jobs()
    dry = tmp_path / "dry"
    R.execute(jobs, dry, CountingChat(), R.fake_get, dry_run=True, **QUIET)
    formal = CountingChat()
    with pytest.raises(SystemExit, match="dry run"):
        R.execute(jobs, dry, formal, fake_api(), **QUIET)
    assert formal.calls == 0 and C.read_json(dry / R.RUN_META)["dry_run"] is True
    real = tmp_path / "real"
    R.execute(jobs, real, CountingChat(), fake_api(), **QUIET)
    with pytest.raises(SystemExit, match="dry run"):
        R.execute(jobs, real, CountingChat(), R.fake_get, dry_run=True, **QUIET)


def test_a_rerun_only_once_and_only_after_a_digest_mismatch(tmp_path):
    jobs = small_jobs()
    calls = {"n": 0}

    def drifting(path):              # the expected digest before the run, another one after it
        calls["n"] += 1
        return fake_api(ps_digest=EXPECTED if calls["n"] == 1 else "f" * 64)(path)
    void, clean = tmp_path / "void", tmp_path / "clean"
    first = R.execute(jobs, void / "r1", CountingChat(), drifting, **QUIET)
    assert first["digest_after"] == "f" * 64 and R.digest_state(first) == "mismatch" and first["attempt"] == 1
    R.execute(jobs, clean / "c1", CountingChat(), fake_api(), **QUIET)
    with pytest.raises(SystemExit, match="mismatch"):        # the clean run may not be redone
        R.execute(jobs, clean / "c2", CountingChat(), fake_api(), rerun_of=clean / "c1", **QUIET)
    with pytest.raises(SystemExit, match="jobs"):            # a rerun is the same jobs
        R.execute(small_jobs(5), void / "x", CountingChat(), fake_api(), rerun_of=void / "r1", **QUIET)
    with pytest.raises(SystemExit, match="void"):            # a void run is not resumed either
        R.execute(jobs, void / "r1", CountingChat(), fake_api(), **QUIET)
    with pytest.raises(SystemExit, match="digest"):          # refused at the digest check: r1 is not marked
        R.execute(jobs, void / "r2x", CountingChat(), fake_api(ps_digest="0" * 64), rerun_of=void / "r1", **QUIET)
    assert "rerun_by" not in C.read_json(void / "r1" / R.RUN_META)
    second = R.execute(jobs, void / "r2", CountingChat(), fake_api(), rerun_of=void / "r1", **QUIET)
    assert (second["attempt"], second["rerun_of"]) == (2, str((void / "r1").resolve()))
    assert R.digest_ok(second)
    assert C.read_json(void / "r1" / R.RUN_META)["rerun_by"] == str((void / "r2").resolve())
    R.execute(jobs, void / "r2", CountingChat(), fake_api(), rerun_of=void / "r1", **QUIET)   # resuming it is fine
    with pytest.raises(SystemExit, match="once"):            # r1 was redone already
        R.execute(jobs, void / "r3", CountingChat(), fake_api(), rerun_of=void / "r1", **QUIET)
    with pytest.raises(SystemExit, match="once"):            # a rerun is never redone
        R.execute(jobs, void / "r4", CountingChat(), fake_api(), rerun_of=void / "r2", **QUIET)


def test_a_second_formal_run_of_the_same_jobs_or_layer_is_refused(tmp_path):
    jobs, pins = small_jobs(), {"layer_sha256": "a" * 64, "lexicon_sha256": "b" * 64}
    R.execute(jobs, tmp_path / "dry", CountingChat(), R.fake_get, dry_run=True, pins=pins, **QUIET)
    R.execute(jobs, tmp_path / "r1", CountingChat(), fake_api(), pins=pins, **QUIET)   # a dry run does not count
    chat = CountingChat()
    with pytest.raises(SystemExit, match="exists"):          # the same jobs again, in a new directory
        R.execute(jobs, tmp_path / "r2", chat, fake_api(), pins=pins, **QUIET)
    with pytest.raises(SystemExit, match="exists"):          # other jobs on the same layer
        R.execute(small_jobs(5), tmp_path / "r3", chat, fake_api(), pins=pins, **QUIET)
    root = tmp_path / "root"                                 # found under the runs root too, at any depth
    R.execute(jobs, root / "a" / "r1", CountingChat(), fake_api(), **QUIET)
    with pytest.raises(SystemExit, match="exists"):
        R.execute(jobs, tmp_path / "elsewhere" / "r", chat, fake_api(), runs_root=root, **QUIET)
    assert chat.calls == 0
    other = {"layer_sha256": "c" * 64, "lexicon_sha256": "b" * 64}
    R.execute(small_jobs(4), tmp_path / "r4", CountingChat(), fake_api(), pins=other, **QUIET)  # another layer: fine


def test_an_unreachable_after_check_is_unknown_and_checked_again_on_resume(tmp_path):
    jobs, calls = small_jobs(), {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] > 1:
            raise urllib.error.URLError("down")
        return fake_api()(path)
    out = tmp_path / "unk"
    meta = R.execute(jobs, out, CountingChat(), flaky, **QUIET)
    assert meta["digest_after"] is None and R.digest_state(meta) == "unknown"
    with pytest.raises(SystemExit, match="mismatch"):        # unknown is no mismatch: no rerun
        R.execute(jobs, tmp_path / "unk_re", CountingChat(), fake_api(), rerun_of=out, **QUIET)
    chat = CountingChat()
    meta = R.execute(jobs, out, chat, fake_api(), **QUIET)  # resume: 0 calls, the digest checked again
    assert chat.calls == 0 and R.digest_state(meta) == "ok"


def test_resuming_with_other_pins_is_refused(tmp_path):
    jobs, pins = small_jobs(), {"layer_sha256": "a" * 64, "lexicon_sha256": "b" * 64}
    with pytest.raises(KeyboardInterrupt):
        R.execute(jobs, tmp_path / "o", CountingChat(fail_after=2), fake_api(), pins=pins, **QUIET)
    with pytest.raises(SystemExit, match="pins"):
        R.execute(jobs, tmp_path / "o", CountingChat(), fake_api(), pins={**pins, "lexicon_sha256": "c" * 64}, **QUIET)


# ---------------------------------------------------------------- where the harness writes
def test_store_writes_only_go_to_the_new_directory(tmp_path):
    assert C.writable(tmp_path / "x") == (tmp_path / "x").resolve()
    assert C.writable(C.OUT_ROOT / "dry_run") == (C.OUT_ROOT / "dry_run").resolve()
    for frozen in (C.STORE / "reports/kg_cards_20261018/A_confirm", C.STORE / "reports/regnal_card_20261019/a4x",
                   C.STORE / "layers/x", C.STORE / "contracts/x", C.STORE / "releases/x", C.STORE / "reports/other"):
        with pytest.raises(SystemExit):
            C.writable(frozen)


def test_nothing_is_written_inside_the_repository():
    for p in (REPO / "evaluation/experiments/2026-10-19_regnal_seed/out", REPO / "x.json", RS / "dry_run"):
        with pytest.raises(SystemExit, match="repository"):
            C.writable(p)


def test_the_command_line_writes_only_under_the_output_root(tmp_path, monkeypatch):
    root = tmp_path / "rs_root"
    monkeypatch.setattr(C, "OUT_ROOT", root)
    assert C.cli_out(root / "run1") == (root / "run1").resolve()
    assert C.cli_out(root / "a" / "b.json") == (root / "a" / "b.json").resolve()
    assert C.cli_out(root, allow_root=True) == root.resolve()
    for bad in (root, tmp_path / "elsewhere", tmp_path):
        with pytest.raises(SystemExit, match="only under"):
            C.cli_out(bad)
    for cmd in (["score", "--out", str(tmp_path / "x")], ["repro", "--out", str(tmp_path / "x")],
                ["build", "--layer", "l", "--lexicon", "x", "--out", str(tmp_path / "x")],
                ["dry-run", "--layer", "l", "--lexicon", "x", "--out", str(tmp_path / "x")]):
        with pytest.raises(SystemExit, match="only under"):
            run_rs.main(cmd)
    with pytest.raises(SystemExit, match="only under"):
        A4.main(["--responses", str(tmp_path / "r.jsonl"), "--layer", "l", "--lexicon", "x",
                 "--out", str(tmp_path / "a4.json")])


# ---------------------------------------------------------------- the prereg gate
def _header(**kw):
    files = {f: str(i) * 64 for i, f in enumerate(C.BACKEND_FILES)}
    return {"layer_sha256": "a" * 64, "lexicon_sha256": "b" * 64, "backend_files_sha256": files, **kw}


def _problems(text, h):
    return C.prereg_problems(text, h["layer_sha256"], lexicon_sha=h["lexicon_sha256"],
                             backend_files=h["backend_files_sha256"])


def test_the_prereg_gate_checks_the_layer_the_lexicon_and_the_backend():
    h = _header()
    assert _problems(formal_prereg(h), h) == []
    draft = f"{C.DRAFT_MARK}\n層 {C.LAYER_SHA_PLACEHOLDER}\n"
    assert _problems(draft + formal_prereg(h), h) == ["draft", "placeholder"]
    assert _problems(formal_prereg(_header(layer_sha256="2" * 64)) + f"§9 {'a' * 64}", h) == ["layer sha"]  # §1 only
    assert _problems(formal_prereg(_header(lexicon_sha256="c" * 64)), h) == ["lexicon sha"]
    files = dict(h["backend_files_sha256"], **{C.BACKEND_FILES[0]: "f" * 64})
    assert _problems(formal_prereg(_header(backend_files_sha256=files)), h) == [f"backend sha {C.BACKEND_FILES[0]}"]
    text = (RS / "prereg.md").read_text(encoding="utf-8")
    assert C.DRAFT_MARK not in text and C.LAYER_SHA_PLACEHOLDER not in text   # the committed formal version
    for line in (C.LAYER_LINE, C.LEXICON_LINE):
        assert sum(row.startswith(line) for row in text.splitlines()) == 1
    assert _problems(text, h)


# the r4 release's contract files (prereg §1, 2026-10-19)
R4 = C.STORE / "contracts/b20261019_a86f2b06"
LAYER, LEXICON = R4 / "regnal_layer.json", R4 / "routing_lexicon.json"


@pytest.mark.skipif(not (LAYER.is_file() and LEXICON.is_file()), reason="the r4 contract files not in the store")
def test_the_prereg_pins_the_r4_layer_the_lexicon_and_this_checkouts_backend():
    """§1's layer and lexicon rows are the r4 release's files, its backend table this checkout's."""
    text = (RS / "prereg.md").read_text(encoding="utf-8")
    here = {"layer_sha256": C.sha256_file(LAYER), "lexicon_sha256": C.sha256_file(LEXICON),
            "backend_files_sha256": C.backend().files_sha256}
    assert here["layer_sha256"] == "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"
    assert _problems(text, here) == []
    assert _problems(text, dict(here, layer_sha256="a" * 64)) == ["layer sha"]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                           "commit.gpgsign=false", *args], check=True, capture_output=True)


def test_the_prereg_and_the_harness_must_be_committed_and_unchanged(tmp_path):
    repo = tmp_path / "repo"
    harness = repo / "exp"
    harness.mkdir(parents=True)
    _git(repo, "init", "-q")
    prereg, code = harness / "prereg.md", harness / "rs_x.py"
    prereg.write_text("正式版\n", encoding="utf-8")
    code.write_text("x = 1\n", encoding="utf-8")
    problems = lambda: C.prereg_git_problems(prereg, harness)  # noqa: E731
    assert "prereg.md not committed" in problems()
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "x")
    assert problems() == []
    code.write_text("x = 2\n", encoding="utf-8")                        # a harness file edited
    assert problems() == ["harness files changed or untracked since the last commit"]
    _git(repo, "checkout", "-q", "--", ".")
    (harness / "new.py").write_text("y = 1\n", encoding="utf-8")         # an untracked harness file
    assert problems() == ["harness files changed or untracked since the last commit"]
    (harness / "new.py").unlink()
    prereg.write_text("改過\n", encoding="utf-8")
    assert "prereg.md changed since the last commit" in problems()


def test_the_harness_pins():
    h = C.harness_pins()
    assert set(h) == {"git_head", "dirty", "files_sha256", "sha256"} and len(h["sha256"]) == 64
    assert {"prereg.md", "rs_run.py", "rs_score.py", "run_rs.py", "a4_card_check.py"} <= set(h["files_sha256"])
    assert h["files_sha256"]["rs_run.py"] == C.sha256_file(RS / "rs_run.py")


# ---------------------------------------------------------------- run_rs run: every gate before Ollama
@pytest.fixture
def cli(tmp_path, monkeypatch, syn):
    _lay, _info, doc, items = syn
    jobs = J.build_jobs(doc, items)
    root = tmp_path / "rs_root"
    prereg = tmp_path / "prereg.md"
    prereg.write_text(formal_prereg(doc["header"]), encoding="utf-8")
    chat = CountingChat()
    monkeypatch.setattr(C, "OUT_ROOT", root)
    monkeypatch.setattr(C, "PREREG", prereg)
    monkeypatch.setattr(C, "frozen_problems", lambda: [])
    monkeypatch.setattr(C, "prereg_git_problems", lambda *a, **k: [])
    monkeypatch.setattr(R, "build", lambda layer, lexicon: (doc, jobs, items))
    monkeypatch.setattr(R, "real_chat", chat)
    monkeypatch.setattr(R, "api_get", fake_api())
    args = ["--layer", str(tmp_path / "regnal_layer.json"), "--lexicon", str(tmp_path / "routing_lexicon.json")]
    return SimpleNamespace(doc=doc, jobs=jobs, root=root, prereg=prereg, chat=chat,
                           run=lambda name: run_rs.main(["run", *args, "--out", str(root / name)]),
                           build=lambda name: run_rs.main(["build", *args, "--out", str(root / name)]))


def test_run_with_every_gate_satisfied_records_the_pins(cli):
    cli.run("r1")
    assert cli.chat.calls == len(cli.jobs)
    meta = C.read_json(cli.root / "r1" / R.RUN_META)
    h = cli.doc["header"]
    assert meta["pins"] == {"layer_sha256": h["layer_sha256"], "lexicon_sha256": h["lexicon_sha256"],
                            "backend_sha256": h["backend_sha256"], "harness_sha256": C.harness_pins()["sha256"]}
    assert set(meta["harness"]) == {"git_head", "dirty", "files_sha256", "sha256"} and meta["dry_run"] is False
    assert J.jobs_sha256(C.read_json(cli.root / "r1" / "jobs.json")) == meta["jobs_sha256"]


@pytest.mark.parametrize("break_gate, match", [
    (lambda cli, mp: cli.prereg.write_text(f"> **{C.DRAFT_MARK}**\n" + cli.prereg.read_text(encoding="utf-8"),
                                           encoding="utf-8"), "draft"),
    (lambda cli, mp: cli.prereg.write_text(formal_prereg({**cli.doc["header"], "lexicon_sha256": "c" * 64}),
                                           encoding="utf-8"), "lexicon sha"),
    (lambda cli, mp: mp.setattr(C, "prereg_git_problems", lambda *a, **k: ["prereg.md not committed"]),
     "not committed"),
    (lambda cli, mp: mp.setattr(C, "frozen_problems", lambda: ["cards_common.py"]), "frozen"),
])
def test_run_refuses_before_any_call(cli, monkeypatch, break_gate, match):
    monkeypatch.setattr(R, "real_chat", never)
    monkeypatch.setattr(R, "api_get", never)
    break_gate(cli, monkeypatch)
    with pytest.raises(SystemExit, match=match):
        cli.run("r1")
    assert not (cli.root / "r1").exists()


def test_run_refuses_another_build_in_its_directory(cli, monkeypatch):
    out = cli.root / "r1"
    C.write_json(out / "jobs.json", cli.jobs[1:])
    monkeypatch.setattr(R, "real_chat", never)
    with pytest.raises(SystemExit, match="jobs.json"):
        cli.run("r1")
    C.write_json(out / "jobs.json", cli.jobs)
    C.write_json(out / "cards.json", {**cli.doc, "header": {**cli.doc["header"], "layer_sha256": "f" * 64}})
    with pytest.raises(SystemExit, match="cards.json"):
        cli.run("r1")
    assert not (out / R.GEN).exists()


def test_run_refuses_a_dry_run_directory_and_a_second_run(cli, monkeypatch):
    R.execute(cli.jobs, cli.root / "dry", CountingChat(), R.fake_get, dry_run=True, **QUIET)
    with pytest.raises(SystemExit, match="dry run"):
        cli.run("dry")
    assert cli.chat.calls == 0
    cli.run("r1")
    n = cli.chat.calls
    with pytest.raises(SystemExit, match="exists"):
        cli.run("r2")
    assert cli.chat.calls == n and not (cli.root / "r2" / R.GEN).exists()


def test_build_refuses_a_directory_that_holds_a_run(cli):
    cli.build("b1")
    assert (cli.root / "b1" / "cards.json").is_file()
    cli.run("b1")                                   # the build's directory, then the run in it
    with pytest.raises(SystemExit, match="holds a run"):
        cli.build("b1")


# ---------------------------------------------------------------- score_run: what it scores
def _finished(jobs, parent, **kw):
    """A finished formal run of the jobs (fake chat) in parent/run."""
    out = parent / "run"
    R.execute(jobs, out, CountingChat(), fake_api(), **QUIET, **kw)
    return out


def test_score_refuses_jobs_or_cards_that_are_not_the_runs(syn, tmp_path, monkeypatch):
    _lay, _info, doc, items = syn
    jobs = J.build_jobs(doc, items)
    out = _finished(jobs, tmp_path)
    monkeypatch.setattr(S, "reproduce", never)          # the consistency checks come first
    with pytest.raises(SystemExit, match="jobs"):
        S.score_run(out, doc, jobs[:-1], items)
    bad = json.loads(json.dumps(doc))
    s = next(s for s in bad["slots"] if s["card"])
    s["text"] = s["text"] + "x"
    with pytest.raises(SystemExit, match="card"):
        S.score_run(out, bad, jobs, items)
    other = json.loads(json.dumps(doc))
    other["header"]["layer_sha256"] = "f" * 64
    pinned = _finished(jobs, tmp_path / "p", pins=R.pins_of(doc))
    with pytest.raises(SystemExit, match="layer"):
        S.score_run(pinned, other, jobs, items)


def test_score_refuses_when_the_scorers_do_not_reproduce(syn, tmp_path, monkeypatch):
    _lay, _info, doc, items = syn
    jobs = J.build_jobs(doc, items)
    out = _finished(jobs, tmp_path)
    monkeypatch.setattr(S, "reproduce", lambda: {"confirm": {"ok": False}, "dev": {"ok": True}})
    with pytest.raises(SystemExit, match="reproduce"):
        S.score_run(out, doc, jobs, items)


def test_score_refuses_fake_checks_in_a_formal_run_and_a_dirty_harness(syn, tmp_path, monkeypatch):
    _lay, _info, doc, items = syn
    jobs = J.build_jobs(doc, items)
    out = _finished(jobs, tmp_path)
    monkeypatch.setattr(S, "reproduce", never)
    meta = C.read_json(out / R.RUN_META)
    C.write_json(out / R.RUN_META, {**meta, "digest_checks": [dict(c, fake=True) for c in meta["digest_checks"]]})
    with pytest.raises(SystemExit, match="fake"):
        S.score_run(out, doc, jobs, items)
    C.write_json(out / R.RUN_META, meta)
    monkeypatch.setattr(C, "harness_pins", lambda: {"git_head": "x", "dirty": True, "files_sha256": {}, "sha256": "0"})
    with pytest.raises(SystemExit, match="uncommitted"):
        S.score_run(out, doc, jobs, items, require_clean=True)
