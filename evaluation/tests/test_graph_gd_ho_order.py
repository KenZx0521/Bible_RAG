"""GD experiment §7 HO: what keeps an agent run blind and in §10 order (ho_tools/_ho_claude.py,
_ho_common.py).

A launch refuses a cwd whose Claude Code auto-memory holds anything and a CLI other than the
pinned version; a formal (non-pilot) root needs 附錄 A, both acceptances
(gd.assert_set_allowed, never patched here) and a V1 that did not stop; the V1 half is tested
on its own with synthetic V1 files. Nothing here launches an agent or reads confirmation data.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
for _p in (str(_DIR / "ho_tools"), str(_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = importlib.import_module("_ho_common")
gd = H.gd
C = importlib.import_module("_ho_claude")


def test_launch_refuses_a_cwd_whose_auto_memory_has_content(tmp_path):
    home = tmp_path / "home"
    assert C.memory_dir(Path("/srv"), home) == home / ".claude" / "projects" / "-srv" / "memory"
    assert C.check_memory_dir(Path("/srv"), home) == C.memory_dir(Path("/srv"), home)
    mem = C.memory_dir(Path("/srv"), home)
    mem.mkdir(parents=True)
    assert C.check_memory_dir(Path("/srv"), home) == mem          # empty is fine
    (mem / "MEMORY.md").write_text("Kay 的專案")
    with pytest.raises(H.HoToolError, match="auto-memory"):
        C.check_memory_dir(Path("/srv"), home)


@pytest.mark.parametrize("found", ["2.1.300 (Claude Code)", "2.1.29 (Claude Code)", "", "unknown (OSError)"])
def test_launch_refuses_a_cli_other_than_the_pinned_version(found):
    assert C.check_claude_version(f"{C.CLAUDE_VERSION} (Claude Code)") == f"{C.CLAUDE_VERSION} (Claude Code)"
    with pytest.raises(H.HoToolError, match="pinned"):
        C.check_claude_version(found)


# ---------------------------------------------------------------- §10 順序: formal runs after V1

def test_a_pilot_root_is_always_allowed(tmp_path):
    H.assert_formal_allowed(tmp_path / "pilot", v1_result=tmp_path / "missing.json")


@pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")
def test_a_formal_root_is_refused_before_appendix_a(tmp_path):
    with pytest.raises(gd.ConfirmationLockedError):
        H.assert_formal_allowed(tmp_path / "ho", v1_result=tmp_path / "v1.json")


@pytest.mark.parametrize("doc,ok", [
    (None, False),
    ({"stage": "V1", "set": "old31", "stop": True}, False),
    ({"stage": "V1", "set": "old31"}, False),
    ({"stage": "V1", "set": "new82", "stop": False}, False),
    ({"stage": "V1", "set": "old31", "stop": False}, True)])
def test_a_formal_root_needs_a_v1_that_did_not_stop(tmp_path, doc, ok):
    """The V1 half of assert_formal_allowed, on its own (the guard half is never bypassed)."""
    v1 = tmp_path / "v1.json"
    if doc is not None:
        v1.write_text(json.dumps(doc), encoding="utf-8")
    if ok:
        H.check_v1_result(v1)
    else:
        with pytest.raises(H.HoToolError):
            H.check_v1_result(v1)


@pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")
@pytest.mark.parametrize("argv", [["run_gen.py", "draft"], ["run_audit.py"]])
def test_the_runners_refuse_a_formal_root_with_one_line_and_write_nothing(tmp_path, argv):
    import subprocess
    root = tmp_path / "ho"
    proc = subprocess.run([sys.executable, "-B", str(_DIR / "ho_tools" / argv[0]), *argv[1:],
                           "--root", str(root)], capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 2 and proc.stderr.count("\n") == 1
    assert "ConfirmationLockedError" in proc.stderr and not root.exists()
