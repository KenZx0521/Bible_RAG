"""§3 list and pool shape shared by arms.py, score.py and evaluate.py (private part of gd_common).

Import through gd_common. One question's lists entry (arms.py output) is
{"D30": [30 pid], "R20": [pid], "C": [...], "GD": [...], ...}: D30 is the dense ranking's
top 30, R20 the passages of the top-20 dense records in record order (the §4 D5≈ input,
always inside D30[:20]), and each arm holds only its extra (≤10 distinct passages outside
D30[:20]; C's extra is exactly D30[20:30]). The pool of an arm is D30[:20] + its extra.
check_entry() is the one validator of that shape; any break raises IntegrityError.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from _gd_store import EMB_DIM, IntegrityError

__all__ = ["D_KEY", "R20_KEY", "N_DENSE", "N_BASE", "N_EXTRA", "N_SEEDS", "N_D5_RECORDS", "N_D5",
           "ARMS", "LIST_KEYS", "check_entry", "entry_arms", "arm_pool", "pool_union",
           "lists_sha256", "decode_vector_b64"]

D_KEY = "D30"               # dense top 30
R20_KEY = "R20"             # passages of the top-20 dense records (§4 D5≈ input)
N_DENSE = 30
N_BASE = 20                 # D[0:20] is in every pool
N_EXTRA = 10                # at most 10 extra passages per arm (fewer is not padded)
N_SEEDS = 10                # D[0:10] seeds GD / G / LEXPRF
N_D5_RECORDS = 20           # §4 D5≈: record-level cosine top 20 ...
N_D5 = 5                    # ... mapped to passages, then the top 5 by (−score, pid)
ARMS = ("C", "GD", "GD_DEGNORM", "G", "L", "LEXPRF")
LIST_KEYS = (D_KEY, R20_KEY, *ARMS)


def _distinct(values: Any) -> bool:
    return isinstance(values, list) and all(isinstance(v, str) for v in values) \
        and len(set(values)) == len(values)


def check_entry(qid: str, entry: Mapping[str, Any]) -> None:
    """Raise unless `entry` has the §3 shape (see the module docstring)."""
    if not isinstance(entry, Mapping):
        raise IntegrityError(f"{qid}: lists entry is not an object")
    unknown = sorted(set(entry) - set(LIST_KEYS))
    if unknown:
        raise IntegrityError(f"{qid}: unknown list keys {unknown}")
    dense = entry.get(D_KEY)
    if not (_distinct(dense) and len(dense) == N_DENSE):
        raise IntegrityError(f"{qid}: {D_KEY} must hold {N_DENSE} distinct passage ids")
    head = set(dense[:N_BASE])
    r20 = entry.get(R20_KEY)
    if r20 is not None and not (_distinct(r20) and r20 and set(r20) <= head):
        raise IntegrityError(f"{qid}: {R20_KEY} must be distinct passages inside {D_KEY}[:{N_BASE}]")
    for arm in ARMS:
        extra = entry.get(arm)
        if extra is None:
            continue
        if not (_distinct(extra) and len(extra) <= N_EXTRA) or head & set(extra):
            raise IntegrityError(f"{qid}/{arm}: extra must be ≤{N_EXTRA} distinct pids "
                                 f"outside {D_KEY}[:{N_BASE}] (§3)")
        if arm == "C" and extra != dense[N_BASE:]:
            raise IntegrityError(f"{qid}: C extra is not {D_KEY}[{N_BASE}:{N_DENSE}]")


def entry_arms(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """The arms an entry carries, in ARMS order."""
    return tuple(a for a in ARMS if a in entry)


def arm_pool(entry: Mapping[str, Sequence[str]], arm: str) -> tuple[str, ...]:
    """§3 pool of one arm: D30[:20] + its extra."""
    return tuple(entry[D_KEY][:N_BASE]) + tuple(entry[arm])


def pool_union(qid: str, entry: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """D30[:20] ∪ every arm's extra, sorted by pid (what one question needs scored)."""
    check_entry(qid, entry)
    arms = entry_arms(entry)
    if not arms:
        raise IntegrityError(f"{qid}: no arm lists besides {D_KEY}")
    return tuple(sorted(set(entry[D_KEY][:N_BASE]).union(*(entry[a] for a in arms))))


def lists_sha256(lists: Mapping) -> str:
    """Content hash of a lists part: sha256 of its compact JSON in insertion order. Unlike the
    file sha it does not change when the same lists are written again with a new meta."""
    text = json.dumps(lists, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decode_vector_b64(text: str, what: str) -> np.ndarray:
    """A query vector line's float32 bytes; EMB_DIM finite values or IntegrityError."""
    vec = np.frombuffer(base64.b64decode(text), dtype="<f4")
    if vec.shape != (EMB_DIM,) or not np.all(np.isfinite(vec)):
        raise IntegrityError(f"{what}: vector is not {EMB_DIM} finite floats")
    return vec
