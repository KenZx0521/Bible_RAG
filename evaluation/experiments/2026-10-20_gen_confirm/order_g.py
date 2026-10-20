"""The writing order of the 58 pool slots (prereg §2.3). Stdlib only; writes store order.json only.

The seed is derived from the F1 manifest's file → sha256 map (the frozen rule, prompt and check files;
canonical JSON, no timestamps), so the order cannot exist before the rules freeze, and rewriting the manifest
with the same files gives the same order. order.json is written once: a second run refuses.
Each stratum is shuffled with one ``random.Random(seed)`` in stratum order; the strata are merged by the key
(rank + 0.5) / N_h ascending, ties broken by stratum order, so every prefix is close to proportional.
Pilot = positions 1–12; K-P's n_target truncates the order.
"""
from __future__ import annotations

import json
import random
import sys

import g_common as GC

STRATA = ("F1c5", "F1c11", "F5c5", "F5c11")
PILOT = GC.PILOT
F1_MANIFEST = GC.F1_MANIFEST
ORDER = GC.ORDER


def files_digest(manifest: dict) -> str:
    """sha256 of the canonical JSON of the manifest's ``files`` map (name → sha256)."""
    return GC.sha256_text(json.dumps(manifest["files"], sort_keys=True, ensure_ascii=False))


def seed_from(digest: str) -> int:
    return int(digest[:16], 16)


def order(slots: list[dict], seed: int) -> list[str]:
    """Slot ids in writing order."""
    rng = random.Random(seed)
    keyed = []
    for si, st in enumerate(STRATA):
        ids = sorted(s["sid"] for s in slots if s["stratum"] == st)
        rng.shuffle(ids)
        keyed += [((r + 0.5) / len(ids), si, sid) for r, sid in enumerate(ids)]
    return [sid for _, _, sid in sorted(keyed)]


def main() -> int:
    if not F1_MANIFEST.is_file():
        raise SystemExit(f"{F1_MANIFEST} does not exist: the order is drawn only after F1 (prereg §2.3)")
    if ORDER.exists():
        raise SystemExit(f"{ORDER} already exists: the order is drawn once (prereg §2.3)")
    if GC.sha256_file(GC.POOL) != GC.POOL_SHA256:
        raise SystemExit(f"{GC.POOL}: sha256 is not {GC.POOL_SHA256[:12]} (prereg §2.1)")
    digest = files_digest(GC.read_json(F1_MANIFEST))
    slots = GC.read_json(GC.POOL)["pool"]
    ids = order(slots, seed_from(digest))
    GC.write_json(ORDER, {"schema": "gen_confirm.order.v1", "f1_files_digest": digest,
                          "f1_manifest_sha256": GC.sha256_file(F1_MANIFEST),
                          "pool_sha256": GC.POOL_SHA256, "pilot": PILOT, "order": ids})
    print("order.json sha256", GC.sha256_file(ORDER))
    return 0


if __name__ == "__main__":
    sys.exit(main())
