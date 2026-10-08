"""The R2 evaluation's frozen question sets (experiments/2026-10-09_r2/prereg.md).

``experiments/2026-10-09_r2/freeze_r2.py`` derives ``frozen_r2.json`` by an
offline route simulation of every GT v2 question under the R1 build's
contracts and code (commit e7b1173) and the R2 build's (the R2 commit): the
route-change slice C3 scores, split by cause into sub-slices, the
disambiguation family and the excluded ids listed beside it, and the G-ANS
subset copied from frozen_r1.json. It is run once the R2 build exists and
before any R2 result; then :data:`FROZEN_R2_SHA256` pins its bytes.

Until that pin is set, :func:`load_frozen` refuses every file. Reading is
r1_frozen.read_frozen's, so the checks are R1's (schema, GT v2 sha256 and
slot_universe, counts, union = ∪ sub-slices, sha256 last).
"""

from __future__ import annotations

from pathlib import Path

from .r1_frozen import FreezeFormat, FrozenR1, read_frozen

SCHEMA = "evaluation.r2_frozen.v1"
SLICE_KEY = "route_change_slice"
# Why a question's retrieval can change between R1 and R2 (freeze_r2.py RULES):
# its route handler, its detected books, or its event lane's anchor preference.
SUB_SLICES = ("route", "books", "lane")
FROZEN_R2_PATH = (Path(__file__).resolve().parent.parent
                  / "experiments" / "2026-10-09_r2" / "frozen_r2.json")
# sha256 of the pre-registered frozen_r2.json bytes. Set once freeze_r2.py has written it,
# before any R2 result exists; None refuses every read.
FROZEN_R2_SHA256: str | None = "7289bd01b94b4557c20cb07743de6331eecfe572b0bf4c59afaa09d120c0e527"


def load_frozen(path: Path | str = FROZEN_R2_PATH) -> FrozenR1:
    """Read frozen_r2.json → ``FrozenR1(route-change slice, sub_slices, gans_subset)``.

    ``damaged_union`` holds C3's set, the route-change slice (route ∪ books ∪
    lane); ``sub_slices`` maps each cause to its questions; ``gans_subset`` is
    frozen_r1.json's 200. Raises FrozenR1Error as r1_frozen.load_frozen does,
    and while FROZEN_R2_SHA256 is None.
    """
    fmt = FreezeFormat(SCHEMA, SLICE_KEY, "route-change", SUB_SLICES, FROZEN_R2_SHA256,
                       "src/r2_frozen.py FROZEN_R2_SHA256")
    return read_frozen(path, fmt)
