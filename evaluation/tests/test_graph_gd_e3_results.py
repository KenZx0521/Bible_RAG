"""GD experiment §8 E3: results_quick never keeps a file, gates check metric_version, CLI errors.

score_raw on a stand-in quick_retrieval_eval (it writes <label>.json into a scratch
results directory, and may fail or write a second file as a concurrent run would): this
run's output always leaves the directory (to dest/failed/ unless it is accepted), the
directory lists as before, and an exclusive flock on its parent serializes E3 runs. gates
refuses an in-process metric_version other than 4d0826bb8d14 before reading any run, and
the CLI turns every error (also a malformed run record) into one line with exit 2, so
exit 1 only ever means FAIL. Nothing here retrieves, scores or encodes anything.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
import _e3_gates as G  # noqa: E402
import _e3_run as R  # noqa: E402
import e3_raw  # noqa: E402

LOCK_PROBE = ("import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDONLY)\n"
              "try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\n"
              "except BlockingIOError:\n    print('busy')\n")


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A results directory holding old.json, and score_raw's metric probe stubbed."""
    rq = tmp_path / "rq"
    rq.mkdir()
    (rq / "old.json").write_text("{}")
    monkeypatch.setattr(R, "metric_version_now", lambda: R.METRIC_VERSION)
    return rq


def fake_quick(rq, *, fail=False, stray=None, write=True):
    def run_quick(raw_path, k, label):
        if write:
            (rq / f"{label}.json").write_text('{"x": 1}')
        if stray:
            (rq / stray).write_text("{}")
        if fail:
            raise gd.GdError("quick_retrieval_eval.py exited 1: boom")
        return "ok\n"
    return run_quick


def score(rq, dest):
    return R.score_raw(Path("/raw"), [], {}, 5, "GD", dest, directory=rq)


def failed_files(dest):
    return sorted(p.name for p in (dest / R.FAILED_DIR).iterdir()) if (dest / R.FAILED_DIR).is_dir() else []


def test_a_failed_quick_retrieval_eval_leaves_nothing_in_results_quick(scratch, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "run_quick", fake_quick(scratch, fail=True))
    with pytest.raises(gd.GdError, match="boom"):
        score(scratch, tmp_path / "dest")
    assert R.listing(scratch) == (True, ("old.json",))
    assert len(failed_files(tmp_path / "dest")) == 1 and not (tmp_path / "dest" / R.QUICK_NAME).exists()


def test_a_concurrent_file_stops_the_run_but_this_runs_output_still_leaves(scratch, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "run_quick", fake_quick(scratch, stray="gd_e3_C_k5_OTHER_1.json"))
    with pytest.raises(gd.IntegrityError, match="OTHER"):
        score(scratch, tmp_path / "dest")
    assert R.listing(scratch) == (True, ("gd_e3_C_k5_OTHER_1.json", "old.json"))
    assert len(failed_files(tmp_path / "dest")) == 1 and not (tmp_path / "dest" / R.QUICK_NAME).exists()


def test_a_run_that_wrote_nothing_is_an_error(scratch, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "run_quick", fake_quick(scratch, write=False))
    with pytest.raises(gd.GdError, match="wrote no"):
        score(scratch, tmp_path / "dest")
    assert R.listing(scratch) == (True, ("old.json",)) and failed_files(tmp_path / "dest") == []


def test_an_accepted_output_is_promoted_and_failed_is_not_left_behind(scratch, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "run_quick", fake_quick(scratch))
    monkeypatch.setattr(R, "verify_quick", lambda *a: {"n": 0})
    out = score(scratch, tmp_path / "dest")
    assert out["results_quick_unchanged"] is True and Path(out["quick_eval"]).name == R.QUICK_NAME
    assert json.loads((tmp_path / "dest" / R.QUICK_NAME).read_text()) == {"x": 1}
    assert not (tmp_path / "dest" / R.FAILED_DIR).exists()
    assert R.listing(scratch) == (True, ("old.json",))


def probe_lock(path):
    return subprocess.run([sys.executable, "-c", LOCK_PROBE, str(path)], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_the_results_lock_is_exclusive_while_held_and_released_after(scratch):
    with R.results_lock(scratch):
        assert probe_lock(scratch.parent) == "busy"
    assert probe_lock(scratch.parent) == "free"
    assert list(scratch.parent.iterdir()) == [scratch]                  # no lock file


def test_gates_refuse_another_in_process_metric_version_before_reading_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(G.qre, "metric_version", lambda: "000000000000")
    with pytest.raises(gd.IntegrityError, match="in-process"):
        e3_raw.gates({5: (tmp_path / "C", tmp_path / "GD")}, tmp_path / "g.json", allow_unpinned=True)


def test_a_run_record_without_its_keys_is_an_integrity_error_with_exit_2(tmp_path, capsys):
    for name in ("C", "GD"):
        (tmp_path / name).mkdir()
        (tmp_path / name / R.RECORD_NAME).write_text(json.dumps({"k": 5}))
    code = e3_raw.main(["gates", "--c5", str(tmp_path / "C"), "--gd5", str(tmp_path / "GD"),
                        "--out", str(tmp_path / "g.json"), "--allow-unpinned"])
    err = capsys.readouterr().err
    assert code == 2 and "IntegrityError" in err and "lacks" in err and len(err.strip().splitlines()) == 1
    assert not (tmp_path / "g.json").exists()


@pytest.mark.parametrize("exc", [KeyError("arm"), TypeError("x"), AttributeError("y")])
def test_any_other_error_is_one_line_with_exit_2_never_a_traceback(exc, tmp_path, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise exc
    monkeypatch.setattr(e3_raw, "gates", boom)
    code = e3_raw.main(["gates", "--c5", "a", "--gd5", "b", "--out", str(tmp_path / "g.json"),
                        "--allow-unpinned"])
    err = capsys.readouterr().err
    assert code == 2 and type(exc).__name__ in err and len(err.strip().splitlines()) == 1
