"""§10 meta coverage of the GD experiment scripts (experiments/2026-10-14_graph_gd/).

§10 records the sha256 of every script a run executes. In a fresh interpreter each script
is imported and every module it loaded from the experiment directory or evaluation/src
must be among the files its meta hashes (arms.py: SCRIPT_FILES; score.py: script_files();
evaluate.py: SOURCE_FILES; all of them: gd_common.MODULE_FILES), so a helper changed
between two runs always shows up in their meta.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"

PROBE = """
import json, sys
from pathlib import Path
sys.argv = ["probe"]
exp = Path({exp!r})
sys.path.insert(0, str(exp))
import gd_common as gd
import {module} as mod
declared = [str(Path(p).resolve()) for p in ({declared})] + [str(p.resolve()) for p in gd.MODULE_FILES]
src = exp.parents[1] / "src"
loaded = sorted(str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                if getattr(m, "__file__", None) and Path(m.__file__).resolve().parent in (exp, src))
print(json.dumps({{"declared": declared, "loaded": loaded}}))
"""

DECLARED = {
    "arms": "mod.SCRIPT_FILES",
    "score": "[*mod.script_files(mod.RERANK_STDIN).values(), mod.ENCODE_STDIN]",
    "evaluate": "mod.SOURCE_FILES.values()",
    "accept_a": "[mod.HERE, Path(mod.M.__file__), *mod.arms.SCRIPT_FILES]",
}


@pytest.mark.parametrize("module", sorted(DECLARED))
def test_every_loaded_experiment_or_src_module_is_hashed_into_the_meta(module):
    code = PROBE.format(exp=str(_DIR), module=module, declared=DECLARED[module])
    proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                          cwd=_DIR, check=True)
    out = json.loads(proc.stdout)
    missing = sorted(set(out["loaded"]) - set(out["declared"]))
    assert not missing, f"{module}: loaded but not hashed into its meta: {missing}"
