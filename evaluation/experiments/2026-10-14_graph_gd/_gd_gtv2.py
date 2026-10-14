"""GT v2 as a question set of the GD experiment (prereg §2, §8; private part of gd_common).

Import through gd_common, which re-exports this module and takes its load_question_set:
the one of _gd_sets.py plus "gtv2". GT v2 is the repo's frozen ground_truth.v2.json
(500 questions, only for the §8 harm check E3). The file must hash to GTV2_SHA256, the
same sha256 that config/gold/gt_v2_freeze.json records (evaluation/src/gt_v2.py checks
the same pair), declare gt_version "v2" and the frozen slot_universe, and give 500
distinct ids whose §2 id sha is GTV2_IDS_SHA256. arms.py needs only the id and the
question: the query is the question text unchanged (§3), the same string
quick_retrieval_eval.py and the collector send to the backend (gt.question of
data_loader.load_gt("v2"); tests/test_graph_gd_e3_gtv2.py compares all 500).

A GT v2 Question has no hops (its gold is the slot ruler of §8, not §4 hop gold) and
carries the GT question_type as its category (not one of _gd_sets.CATEGORIES). Loading
reads questions only: no retrieval of any kind; the guard (gd.assert_set_allowed) runs
in the scripts before any of them loads a set.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from types import MappingProxyType

import _gd_sets
from _gd_sets import Question, QuestionSet
from _gd_store import (EXP_DIR, LAYER_VERSIONS, GdError, IntegrityError, expect, file_sha256,
                       read_pinned)

__all__ = ["GTV2", "REPO_ROOT", "GTV2_PATH", "GTV2_FREEZE_PATH", "GTV2_SHA256", "GTV2_IDS_SHA256",
           "GTV2_SIZE", "GTV2_SLOT_UNIVERSE", "SET_LOADERS", "load_gtv2"]

GTV2 = "gtv2"                                    # the set name (gd.SET_REQUIRES key)
REPO_ROOT = EXP_DIR.parents[2]                   # evaluation/experiments/<exp> -> repo
GTV2_PATH = REPO_ROOT / "ground_truth.v2.json"
GTV2_FREEZE_PATH = REPO_ROOT / "config" / "gold" / "gt_v2_freeze.json"
GTV2_SHA256 = "7280bb42af869ee18d34230b296f302132eb82dbf5203391e07882fd3691b2f1"
GTV2_IDS_SHA256 = "1472f5f8fda8efb7906cd41a02e036b9fdfe3bb2b1966a85f518ba12af7d5f2a"
GTV2_SIZE = 500
GTV2_SLOT_UNIVERSE = LAYER_VERSIONS["text"]      # text@247eafe44b02 (freeze record slot_universe)
SET_LOADERS = ("new82", "old31", "ho", GTV2)


def _check_freeze(freeze_path: Path) -> None:
    """The freeze record must name the same file, sha256 and slot universe as the pins."""
    try:
        freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise IntegrityError(f"cannot read the GT v2 freeze record {freeze_path}: {err}") from None
    got = {k: freeze.get(k) for k in ("gt_path", "sha256", "slot_universe")}
    expect(f"{freeze_path} (GT v2 freeze record)", got,
           {"gt_path": GTV2_PATH.name, "sha256": GTV2_SHA256, "slot_universe": GTV2_SLOT_UNIVERSE})


def _question(row: object, n: int) -> Question:
    if not isinstance(row, dict):
        raise IntegrityError(f"GT v2 question {n} is not an object")
    qid, text, qtype = row.get("question_id"), row.get("question"), row.get("question_type")
    if not (isinstance(qid, str) and qid and isinstance(text, str) and text.strip()
            and isinstance(qtype, str) and qtype):
        raise IntegrityError(f"GT v2 question {n} ({qid!r}) needs question_id, question and "
                             "question_type strings")
    return Question(qid, text, qtype, (), None)


@functools.cache
def load_gtv2(path: Path = GTV2_PATH, freeze_path: Path = GTV2_FREEZE_PATH) -> QuestionSet:
    """§2 GT v2 in file order: each question's id, unchanged question text and question_type."""
    _check_freeze(freeze_path)
    doc = json.loads(read_pinned(path, GTV2_SHA256))
    meta = doc.get("metadata") or {}
    expect("GT v2 metadata (gt_version, slot_universe)",
           (meta.get("gt_version"), meta.get("slot_universe")), ("v2", GTV2_SLOT_UNIVERSE))
    rows = doc.get("questions")
    if not isinstance(rows, list):
        raise IntegrityError(f"{path}: 'questions' is not a list")
    questions = tuple(_question(row, n) for n, row in enumerate(rows))
    qs = QuestionSet(GTV2, questions, MappingProxyType(
        {str(path): GTV2_SHA256, str(freeze_path): file_sha256(freeze_path)}))
    expect("gtv2 size (questions)", len(qs.questions), GTV2_SIZE)
    expect("gtv2 ids sha256", qs.ids_sha256, GTV2_IDS_SHA256)
    return qs


def load_question_set(name: str) -> QuestionSet:
    """'new82' | 'old31' | 'ho' (_gd_sets.load_question_set) | 'gtv2' (load_gtv2). Reads
    questions only; the guard runs first with gd.assert_set_allowed."""
    if name == GTV2:
        return load_gtv2()
    if name not in SET_LOADERS:
        raise GdError(f"unknown question set {name!r}; expected one of {sorted(SET_LOADERS)}")
    return _gd_sets.load_question_set(name)
