"""G-DET: two runs of the same stage on the same inputs must write identical files.

The interface compares two stored layer versions file by file (sha256 from
their verified manifests). The dependency versions are a layer file
(``depends_on.json``), so runs built on different inputs differ there. The two
arguments must be two runs: the same directory twice is refused.

Vectors are compared with a tolerance instead (design §4, §6): for two emb
layers the ``vectors`` attachments must hold the same records, every row pair
with cosine >= 0.99999, the same top-20 neighbours for 200 sampled rows, and
probe vectors with cosine >= 0.99999 (``gates.vectors``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ragdata.gates.base import GateInputError, GateResult, capped
from ragdata.gates.vectors import compare_sets
from ragdata.store import StoreError, attach, vectors, verify_layer

NAME = "G-DET"


def _vectors(first: Path, second: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        runs = [vectors.decode_vectors(attach.read_attachment(p, vectors.NAME)[1])
                for p in (first, second)]
    except StoreError as exc:
        return {"compared": False}, [f"vectors: {exc}"]
    observed, violations = compare_sets(*runs)
    return observed, [f"vectors: {v}" for v in violations]


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
    observed: dict[str, Any] = {"first": manifest_a["layer_version"],
                                "second": manifest_b["layer_version"],
                                "differing_files": len(details)}
    if manifest_a["layer"] != manifest_b["layer"]:
        details.append(f"layers differ: {manifest_a['layer']} vs {manifest_b['layer']}")
    elif manifest_a["layer"] == "emb":
        observed["vectors"], found = _vectors(Path(first), Path(second))
        details += found
    return GateResult(NAME, True, not details, observed, {"differing_files": 0}, capped(details))
