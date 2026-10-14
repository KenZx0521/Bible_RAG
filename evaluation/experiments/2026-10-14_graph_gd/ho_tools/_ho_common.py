"""Shared paths, pins and errors of the §7 HO tools (prereg.md §7 盲出題).

Importing this module puts this directory and the experiment directory on sys.path, so
every ho_tools script imports gd_common through here. Run roots: the formal one is HO_ROOT
(store reports/graph_gd_20261014/ho/), the pilot one PILOT_ROOT (ho/pilot/, results
discarded). Nothing here reads /tmp.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

HO_DIR = Path(__file__).resolve().parent
_EXP = HO_DIR.parent
for _p in (str(HO_DIR), str(_EXP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gd_common as gd  # noqa: E402

__all__ = ["gd", "HO_DIR", "EXP_DIR", "REPO_ROOT", "EVAL_PYTHON", "HO_ROOT", "PILOT_ROOT",
           "GEN_PROMPT", "AUDIT_PROMPT", "PAGE_TEMPLATE", "GT_V2_PATH", "GT_V2_SHA256",
           "SEED", "V1_RESULT", "HoToolError", "is_pilot_root", "under", "files_sha", "ho_meta",
           "assert_formal_allowed", "check_v1_result",
           "CATEGORY_ORDER", "MH_SUBTYPES", "MH_QUOTA", "PER_CATEGORY", "MAX_DRAFTS",
           "PREFIX", "CATEGORY_NAME", "SUBTYPE_NAME", "Violation"]

EXP_DIR = _EXP
REPO_ROOT = EXP_DIR.parents[2]                       # .../Bible_RAG
EVAL_PYTHON = EXP_DIR.parents[1] / ".venv" / "bin" / "python"
HO_ROOT = gd.OUT_ROOT / "ho"
PILOT_ROOT = HO_ROOT / "pilot"
GEN_PROMPT = HO_DIR / "gen_prompt.md"
AUDIT_PROMPT = HO_DIR / "audit_prompt.md"
PAGE_TEMPLATE = HO_DIR / "page_template.html"
GT_V2_PATH = REPO_ROOT / "ground_truth.v2.json"
GT_V2_SHA256 = "7280bb42af869ee18d34230b296f302132eb82dbf5203391e07882fd3691b2f1"  # config/gold/gt_v2_freeze.json
SEED = 20261014                                      # §7 Kay sample
V1_RESULT = EXP_DIR / "v1_old31.json"                # evaluate.py v1 (§6), default --out

# §7 生成順序與配額: four categories in rotation, the multi-hop one by sub-type 8/7/8/7
CATEGORY_ORDER = ("KIN", "DIS", "TO", "MH")
PREFIX = {"KIN": "H_KIN_", "DIS": "H_DIS_", "TO": "H_TO_", "MH": "H_MH_"}
CATEGORY_NAME = {"KIN": "親屬", "DIS": "消歧", "TO": "時序", "MH": "多跳"}
MH_SUBTYPES = ("SUC", "BRP", "BRL", "OQ")
MH_QUOTA = {"SUC": 8, "BRP": 7, "BRL": 8, "OQ": 7}
SUBTYPE_NAME = {"SUC": "承繼與職分鏈", "BRP": "人物橋接", "BRL": "地點、物件、事件橋接",
                "OQ": "引文與典故溯源"}
PER_CATEGORY = 30                                    # 每類取前 30 個通過稽核的題
MAX_DRAFTS = 60                                      # 草稿達 60 題仍不足 30 → 以實際數凍結


class HoToolError(gd.GdError):
    """An HO tool refused its input (bad state, pilot root, unfinished selection, ...)."""


@dataclass(frozen=True)
class Violation:
    """One failed mechanical-audit rule (mech_check.py); level 'error' blocks, 'warn' is noted."""
    rule: str
    detail: str
    level: str = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def under(path: Path | str, root: Path | str) -> bool:
    """True when `path` is `root` or inside it (both resolved)."""
    p, r = Path(path).resolve(), Path(root).resolve()
    return p == r or r in p.parents


def is_pilot_root(root: Path | str) -> bool:
    """A pilot run root: PILOT_ROOT or below it, or any path with a 'pilot' component."""
    return under(root, PILOT_ROOT) or "pilot" in Path(root).resolve().parts


def assert_formal_allowed(root: Path | str, v1_result: Path = V1_RESULT) -> None:
    """§10 順序 (附錄 A → V1 →（未停損）HO 出題): a formal (non-pilot) root needs
    gd.assert_set_allowed("old31") (附錄 A filled, 驗收 A/B passed) and the V1 result of
    evaluate.py v1 with stop false (check_v1_result). Pilot roots are always allowed
    (results discarded)."""
    if is_pilot_root(root):
        return
    gd.assert_set_allowed("old31")
    check_v1_result(v1_result)


def check_v1_result(v1_result: Path = V1_RESULT) -> None:
    """The evaluate.py v1 output must be a V1 on old31 with stop false (§6 停損 → 不出 HO)."""
    try:
        doc = json.loads(Path(v1_result).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise HoToolError(f"formal HO runs need the V1 result {v1_result} "
                          f"(§10: 附錄 A → V1 → HO): {type(err).__name__}") from err
    if not (isinstance(doc, dict) and doc.get("stage") == "V1" and doc.get("set") == "old31"
            and doc.get("stop") is False):
        raise HoToolError(f"{v1_result}: no V1 pass on old31 (stop must be false; §6 停損 → 不出 HO)")


def _label(path: Path) -> str:
    p = Path(path).resolve()
    return str(p.relative_to(EXP_DIR)) if under(p, EXP_DIR) else str(p)


def files_sha(paths: Iterable[Path]) -> dict[str, str]:
    """sha256 of each file, keyed by its path relative to the experiment directory."""
    return {_label(p): gd.file_sha256(p) for p in paths}


def ho_meta(script: str, files: Iterable[Path], **extra: Any) -> dict[str, Any]:
    """§10 meta of an HO tool run: gd.collect_meta (prereg, gd_common modules, environment)
    plus the sha256 of every module and prompt file the script loaded (`files`)."""
    return gd.collect_meta({_label(p): Path(p) for p in files}, script=script, **extra)
