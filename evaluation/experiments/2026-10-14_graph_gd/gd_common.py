"""Shared pins, store loaders, question sets, §4 gold and §10 meta for the GD experiment.

prereg.md in this directory is the only spec; § numbers refer to it. This is the one
module the experiment scripts import (``import gd_common``). It re-exports
_gd_store.py (store paths, layer versions, pinned reads, layer loaders, §4 gold key
resolution), _gd_sets.py (the Question shape, NEW82 / OLD31 / HO loaders), _gd_gtv2.py
(the GT v2 pins and loader; its load_question_set, which also knows "gtv2", replaces
_gd_sets') and _gd_pool.py (the §3 lists / pool shape), and adds the confirmation-set
guard, the §10 fingerprint and run-setting checks and collect_meta(). Everything reads the
store, never /tmp; any pin, count or fingerprint mismatch raises.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _gd_gtv2  # noqa: E402
import _gd_pool  # noqa: E402
import _gd_sets  # noqa: E402
import _gd_store  # noqa: E402
from _gd_pool import *  # noqa: E402,F401,F403
from _gd_sets import *  # noqa: E402,F401,F403
from _gd_store import *  # noqa: E402,F401,F403
from _gd_gtv2 import *  # noqa: E402,F401,F403
from _gd_gtv2 import load_question_set  # noqa: E402,F401  (gtv2-aware; replaces _gd_sets')
from _gd_store import (ACCEPT_DIR, EXP_DIR, PREREG_PATH, GdError, IntegrityError,  # noqa: E402
                       expect, file_sha256)

BUILD_ID = "b20261008_e05d3e55"
CONTAINER = "bible_rag_backend"
IMAGE_ID = "sha256:c79266296cb0e48be2274c24a3e6744b7b3e8eb420771ef9cc5cb1fd4e8ab912"
CONTAINER_PYTHON = ("docker", "exec", "-i", "-e", "PYTHONDONTWRITEBYTECODE=1",
                    "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1", CONTAINER,
                    "/app/backend/.venv/bin/python", "-B", "-")
REVISIONS = MappingProxyType({"reranker": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
                              "embedder": "5617a9f61b028005a4858fdac845db406aefb181"})
FINGERPRINTS = MappingProxyType({
    "reranker": MappingProxyType({
        "tokenizer_sha": "69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15",
        "probe_ids_sha": "0e7683debf6b3b5061e0c3cad60aea8fb1078d1b742d6e74595e38dfbae86b22",
        "unk_count": 2, "pair_template_ok": True}),
    "embedder": MappingProxyType({
        "tokenizer_sha": "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
        "probe_ids_sha": "a0e8db608c923b243d6909dfa38d915989863349eadb2532dad262c106b8be3a",
        "unk_count": 3, "pair_template_ok": True})})
# what this experiment's container scripts run with (§3: reranker fp32 CPU, batch 16, 12 threads;
# the embedder's 8 threads are encode_stdin.py's). Archived meta lines carry only the device.
RUN_SETTINGS = MappingProxyType({
    "reranker": MappingProxyType({"device": "cpu", "batch": 16, "torch_threads": 12}),
    "embedder": MappingProxyType({"device": "cpu", "torch_threads": 8})})
MODULE_FILES = tuple(EXP_DIR / n for n in ("gd_common.py", "_gd_store.py", "_gd_sets.py",
                                           "_gd_pool.py", "_gd_gtv2.py"))
SET_REQUIRES = MappingProxyType({"new82": (), "old31": ("A",), "gtv2": ("A",), "ho": ("A", "B")})
THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")

DRIFT_TOL = 1e-5            # §10 reference-pair drift and §3 re-encode max|Δ|; above it = 基礎設施失敗
ACCEPT_FILES = ("accept_a.json", "accept_b.json")   # both passed=True before any confirmation set

_APPENDIX = re.compile(r"^#{1,6}\s*附錄\s*([A-Z])(?![A-Za-z])")
_HEADING = re.compile(r"^\s{0,3}#")
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_BULLET = re.compile(r"^\s*(?:[-*+>]|\d+[.)、])\s*")
_DECOR = " \t（）()【】[]「」『』<>*_~`:：。.,，;；!！?？…-"
_PLACEHOLDERS = frozenset({"待追加", "待補", "待填", "待定", "TODO", "TBD", "PENDING"})

__all__ = [*_gd_store.__all__, *_gd_sets.__all__, *_gd_pool.__all__, *_gd_gtv2.__all__,
           "BUILD_ID", "CONTAINER",
           "IMAGE_ID", "RUN_SETTINGS", "DRIFT_TOL", "ACCEPT_FILES",
           "CONTAINER_PYTHON", "REVISIONS", "FINGERPRINTS", "MODULE_FILES", "SET_REQUIRES",
           "THREAD_ENV", "ConfirmationLockedError", "appendix_has_content", "assert_set_allowed",
           "expected_fingerprint", "verify_fingerprint", "verify_container_meta",
           "container_image_id", "blas_info", "collect_meta"]


class ConfirmationLockedError(GdError):
    """A confirmation set was requested before its prereg appendix is filled."""


# ------------------------------------------------------------------ confirmation-set guard

def _is_placeholder(line: str) -> bool:
    """A blank line, or one whose text without bullets, brackets and punctuation is a
    placeholder word (待追加, TODO, ...)."""
    core = _BULLET.sub("", line).strip(_DECOR)
    return not core or core.upper() in _PLACEHOLDERS


def appendix_has_content(label: str, prereg: Path = PREREG_PATH) -> bool:
    """True when prereg.md has a heading line '#… 附錄 <label>…' followed, before the next
    heading, by a line that is not a placeholder (_is_placeholder). Lines inside fenced
    code blocks count neither as headings nor as content; the summary bullets never count."""
    in_fence, section = False, False
    for line in Path(prereg).read_text(encoding="utf-8").splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _HEADING.match(line):
            m = _APPENDIX.match(line.strip())
            section = bool(m and m.group(1) == label)
            continue
        if section and not _is_placeholder(line):
            return True
    return False


def _accept_passed(accept_dir: Path) -> list[str]:
    """Problems of the §3 acceptance files: missing, not passed=True, an unpinned chain check
    (pinned=False), or A and B not on the same lists (their top-level lists_sha256)."""
    docs, bad = {}, []
    for name in ACCEPT_FILES:
        try:
            doc = json.loads((Path(accept_dir) / name).read_text(encoding="utf-8"))
            ok = doc.get("passed") is True and doc.get("pinned", True) is True
        except (OSError, ValueError, AttributeError):
            ok = False
        if ok:
            docs[name] = doc
        else:
            bad.append(name)
    shas = {d.get("lists_sha256") for d in docs.values()}
    if not bad and (len(shas) != 1 or None in shas):
        bad.append("lists_sha256 of " + " vs ".join(ACCEPT_FILES))
    return bad


def assert_set_allowed(name: str, prereg: Path = PREREG_PATH, accept_dir: Path = ACCEPT_DIR) -> None:
    """Refuse arms/scores on a set whose prereg appendices (SET_REQUIRES) are still 待追加, or
    (§3 "A、B 都過之前，不得跑確認資料") before accept_a.json and accept_b.json both passed."""
    if name not in SET_REQUIRES:
        raise ConfirmationLockedError(f"unknown set {name!r}; expected one of {sorted(SET_REQUIRES)}")
    missing = [a for a in SET_REQUIRES[name] if not appendix_has_content(a, prereg)]
    if missing:
        raise ConfirmationLockedError(
            f"set {name!r} is locked: prereg appendix {', '.join(missing)} is still 待追加 "
            f"(§10 順序: 驗收 A、B → 附錄 A → V1 → … → 附錄 B → E2)")
    if SET_REQUIRES[name]:
        failed = _accept_passed(accept_dir)
        if failed:
            raise ConfirmationLockedError(
                f"set {name!r} is locked: {', '.join(failed)} in {accept_dir} missing or not "
                f"passed (§3: A、B 都過之前，不得跑確認資料)")


# ------------------------------------------------------------------ fingerprints (§10)

def expected_fingerprint(kind: str) -> dict[str, Any]:
    """'reranker' | 'embedder': the pinned container fingerprint plus the HF 'revision'."""
    return {**FINGERPRINTS[kind], "revision": REVISIONS[kind]}


def verify_fingerprint(kind: str, observed: Mapping[str, Any]) -> None:
    """Every pinned key must be present and equal; 'revision' is compared when present."""
    want = FINGERPRINTS[kind]
    bad = {k: observed.get(k) for k in want if observed.get(k) != want[k]}
    if "revision" in observed and observed["revision"] != REVISIONS[kind]:
        bad["revision"] = observed["revision"]
    if bad:
        raise IntegrityError(f"{kind} fingerprint differs from §10 on {sorted(bad)}: {bad}")


def verify_container_meta(meta: Mapping[str, Any], kind: str, strict: bool = False) -> None:
    """A container script's meta line: type 'meta', the pinned build, '<kind>_fingerprint'
    and device 'cpu'. strict (lines this experiment's container scripts wrote) also needs
    every RUN_SETTINGS value (batch, torch threads)."""
    expect("container line type", meta.get("type"), "meta")
    expect("container build_id", meta.get("build_id"), BUILD_ID)
    verify_fingerprint(kind, meta.get(f"{kind}_fingerprint") or {})
    want = RUN_SETTINGS[kind] if strict else {"device": RUN_SETTINGS[kind]["device"]}
    expect(f"{kind} run settings", {k: meta.get(k) for k in want}, dict(want))


def container_image_id(container: str = CONTAINER) -> str:
    """Image id of the running container (docker inspect, read-only); raises unless IMAGE_ID."""
    out = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", container],
                         capture_output=True, text=True, check=True).stdout.strip()
    expect("container image", out, IMAGE_ID)
    return out


# ------------------------------------------------------------------ meta (§10)

def blas_info() -> list[dict[str, Any]]:
    """BLAS libraries numpy runs on: name, version, threads (threadpoolctl, else numpy config)."""
    try:
        from threadpoolctl import threadpool_info
    except ImportError:
        cfg = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
        return [{"source": "numpy.show_config", "name": cfg.get("name"),
                 "version": cfg.get("version"), "num_threads": None}]
    return [{"source": "threadpoolctl", "name": i.get("internal_api"), "version": i.get("version"),
             "num_threads": i.get("num_threads")}
            for i in threadpool_info() if i.get("user_api") == "blas"]


def collect_meta(files: Mapping[str, Path | str] | None = None, **extra: Any) -> dict[str, Any]:
    """§10 meta: environment, pins, sha256 of prereg.md, the gd_common modules and `files`."""
    sha = {"prereg.md": file_sha256(PREREG_PATH)}
    sha.update({p.name: file_sha256(p) for p in MODULE_FILES})
    sha.update({label: file_sha256(p) for label, p in (files or {}).items()})
    meta = {"time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "argv": list(sys.argv), "python": platform.python_version(), "numpy": np.__version__,
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"), "blas": blas_info(),
            "thread_env": {k: os.environ.get(k) for k in THREAD_ENV}, "build_id": BUILD_ID,
            "image_id": IMAGE_ID, "layers": dict(_gd_store.LAYER_VERSIONS),
            "vectors_sha256": _gd_store.VECTORS_SHA256,
            "fingerprints": {k: expected_fingerprint(k) for k in FINGERPRINTS}, "sha256": sha}
    clash = sorted(set(meta) & set(extra))
    if clash:
        raise GdError(f"extra meta keys clash with collected ones: {clash}")
    return {**meta, **extra}
