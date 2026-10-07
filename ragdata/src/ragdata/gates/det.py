"""G-DET: two runs of the same stage on the same inputs must write identical files.

The interface compares two stored layer versions file by file (sha256 from
their verified manifests). The dependency versions are a layer file
(``depends_on.json``), so runs built on different inputs differ there. The two
arguments must be two runs: the same directory twice is refused. Vector files
will need a cosine comparison instead (design §4); no layer holds them yet.
"""

from __future__ import annotations

from pathlib import Path

from ragdata.gates.base import GateInputError, GateResult, capped
from ragdata.store import verify_layer

NAME = "G-DET"


def check_det(first: Path | str, second: Path | str) -> GateResult:
    if Path(first).resolve() == Path(second).resolve():
        raise GateInputError(f"G-DET needs two runs; {first} and {second} are the same directory")
    manifest_a, _ = verify_layer(first)
    manifest_b, _ = verify_layer(second)
    files_a, files_b = manifest_a["files"], manifest_b["files"]
    differing = sorted(n for n in files_a.keys() & files_b.keys() if files_a[n] != files_b[n])
    details = [f"{name}: sha256 differs" for name in differing]
    details += [f"{name}: only in the first run" for name in sorted(files_a.keys() - files_b.keys())]
    details += [f"{name}: only in the second run" for name in sorted(files_b.keys() - files_a.keys())]
    observed = {"first": manifest_a["layer_version"], "second": manifest_b["layer_version"],
                "differing_files": len(details)}
    if manifest_a["layer"] != manifest_b["layer"]:
        details.append(f"layers differ: {manifest_a['layer']} vs {manifest_b['layer']}")
    return GateResult(NAME, True, not details, observed, {"differing_files": 0}, capped(details))
