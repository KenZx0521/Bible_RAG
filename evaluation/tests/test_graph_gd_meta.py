"""§10 meta coverage of the GD experiment scripts (experiments/2026-10-14_graph_gd/).

§10 records the sha256 of every script a run executes. In a fresh interpreter each script
is imported and every module it loaded from the experiment directory, ho_tools/,
evaluation/ itself or evaluation/src (any depth) must be among the files its meta hashes
(arms.py: SCRIPT_FILES; score.py: script_files(); evaluate.py, e3_raw.py, v1_power.py:
SOURCE_FILES; the ho_tools runners: SCRIPT_FILES; all of them: gd_common.MODULE_FILES), so
a helper changed between two runs always shows up in their meta. bt.py and bt_guard.py run inside
the agents' sessions, so they must be covered by the runners' AGENT_FILES.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
_HO = _DIR / "ho_tools"

PROBE = """
import json, sys
from pathlib import Path
sys.argv = ["probe"]
exp = Path({exp!r}); ho = exp / "ho_tools"; ev = exp.parents[1]
sys.path.insert(0, str(exp))
sys.path.insert(0, {home!r})
import gd_common as gd
import {module} as mod
declared = {{str(Path(p).resolve()) for p in [*({declared}), *gd.MODULE_FILES]}}
mine = lambda p: p.parent in (exp, ho, ev) or p.is_relative_to(ev / "src")
loaded = sorted(str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                if getattr(m, "__file__", None) and mine(Path(m.__file__).resolve()))
print(json.dumps({{"declared": sorted(declared), "loaded": loaded}}))
"""

_AGENT = "__import__('_ho_runs').AGENT_FILES"
# module -> (directory it is run from, expression for the files its meta hashes)
DECLARED = {
    "arms": (_DIR, "mod.SCRIPT_FILES"),
    "score": (_DIR, "[*mod.script_files(mod.RERANK_STDIN).values(), mod.ENCODE_STDIN]"),
    "evaluate": (_DIR, "mod.SOURCE_FILES.values()"),
    "accept_a": (_DIR, "[mod.HERE, Path(mod.M.__file__), *mod.arms.SCRIPT_FILES]"),
    "e3_raw": (_DIR, "mod.SOURCE_FILES.values()"),
    "v1_power": (_DIR, "mod.SOURCE_FILES.values()"),
    "run_gen": (_HO, "mod.SCRIPT_FILES"),
    "run_audit": (_HO, "mod.SCRIPT_FILES"),
    "mech_check": (_HO, "mod.SCRIPT_FILES"),
    "sample_kay": (_HO, "mod.SCRIPT_FILES"),
    "freeze": (_HO, "mod.SCRIPT_FILES"),
    "bt": (_HO, _AGENT),
    "bt_guard": (_HO, _AGENT),
}


def _probe(module: str) -> dict:
    home, declared = DECLARED[module]
    code = PROBE.format(exp=str(_DIR), home=str(home), module=module, declared=declared)
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                          cwd=home, check=True)
    return json.loads(proc.stdout)


@pytest.mark.parametrize("module", sorted(DECLARED))
def test_every_loaded_experiment_or_src_module_is_hashed_into_the_meta(module):
    out = _probe(module)
    missing = sorted(set(out["loaded"]) - set(out["declared"]))
    assert not missing, f"{module}: loaded but not hashed into its meta: {missing}"


@pytest.mark.parametrize("module", sorted(DECLARED))
def test_the_probe_sees_the_module_itself(module):
    """Guards the probe: the imported script is among the loaded modules it checks."""
    home, _ = DECLARED[module]
    assert str((home / f"{module}.py").resolve()) in _probe(module)["loaded"]


def test_the_runners_hash_the_agent_tools_and_both_prompts():
    """run_gen.py / run_audit.py metas cover what the agents execute and read (§7 盲化)."""
    for module in ("run_gen", "run_audit"):
        names = {Path(p).name for p in _probe(module)["declared"]}
        assert {"bt.py", "bt_guard.py", "gen_prompt.md", "audit_prompt.md"} <= names, module
