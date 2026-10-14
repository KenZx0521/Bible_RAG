"""Question sets of prereg §2/§7 as one Question shape, and their §4 gold (private part of gd_common).

Import through gd_common. NEW82 and OLD31 come from pinned store files and must give
the pinned sizes and §2 id sha; HO is validated against the §7 format and mechanical
checks. Loading OLD31 or HO reads questions and gold only: no retrieval of any kind.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from _gd_store import (E7, HO_PATH, PN, GdError, HalfVerseKeyError, IntegrityError, VerseIndex,
                       VerseUnits, expect, hop_gold, ids_sha256, is_half_verse_key, read_pinned)

__all__ = [
    "NEW82_FILE", "NEW82_SUMMARY", "OLD31_FILE", "OLD31_API", "FILE_SHA256", "IDS_SHA256",
    "SET_SIZES", "SHORTCUT_TAG", "KIN", "DIS", "TO", "MH", "OTHER", "CATEGORIES", "NEW82_CATEGORY",
    "OLD31_CATEGORY", "HO_CATEGORY", "HO_FIELDS", "HO_HOPS", "HO_MAX_PER_CORE", "HoFormatError",
    "Question", "QuestionSet", "question_gold", "load_new82", "load_old31", "check_ho_items",
    "load_ho", "load_question_set"]

NEW82_FILE = E7 / "newq" / "questions_v5.json"
NEW82_SUMMARY = PN / "question_summary.json"
OLD31_FILE = E7 / "multihop" / "synth" / "usable.json"
OLD31_API = E7 / "reenable" / "api_arms.json"
FILE_SHA256 = MappingProxyType({
    NEW82_FILE: "4b37e5c322de1a4cde4a4cabafb8b5f9c8d3125b0cc4362d3bca1f9d7acde99f",
    NEW82_SUMMARY: "cdd10c1adc41c532853569c55d0a07b88828886cb6e49d4ffa9ff3c5c7e3764b",
    OLD31_FILE: "0ade60b8670a1e71ccc516caad39ce56fd1c5a9af4ab566e09ba87775c75d98b",
    OLD31_API: "7e28ef3b4660976e7b13a47faa75baf5622e951b60f0b4f6864b726ee36b073b"})
IDS_SHA256 = MappingProxyType({
    "new82": "84985f6d2d6cea27834c0116c1d8b0251d2cd04714defd1adc1cf6c5ce4f2946",
    "old31": "868f75d693b598257ac9362c77e5e72d501c4c3aa7c28d7dee98cae98026fa11"})
SET_SIZES = MappingProxyType({"new82": (82, 223), "old31": (31, 101)})  # (questions, hops)

KIN, DIS, TO, MH, OTHER = "親屬", "消歧", "時序", "多跳", "其他"
CATEGORIES = (KIN, DIS, TO, MH, OTHER)
NEW82_CATEGORY = MappingProxyType({"KIN": KIN, "DIS": DIS, "TO": TO, "SUC": MH, "BRP": MH,
                                   "BRL": MH, "OQ": MH, "NULL": OTHER})
OLD31_CATEGORY = MappingProxyType({"KIN": KIN, "DISAMBIG_MH": DIS, "MH_TO": TO, "SUC": MH,
                                   "PRI": MH, "JDG": MH, "MH_BR": MH, "MH_OQ": MH, "NULL_MH": OTHER})
HO_CATEGORY = MappingProxyType({"H_KIN_": KIN, "H_DIS_": DIS, "H_TO_": TO, "H_MH_": MH})
HO_FIELDS = ("id", "category", "subtype", "question", "answer", "key_points", "hop_slots",
             "hop_roles", "bridge", "why_multihop", "shortcut_search", "needs_identity_resolution",
             "change_log", "hops", "n_hops", "core")
HO_HOPS = (2, 5)
HO_MAX_PER_CORE = 2

_HO_SLOT = re.compile(r"[0-9a-z]+\.\d+\.\d+(-\d+)?")


class HoFormatError(GdError):
    """A held-out (HO) question file breaks the §7 format or mechanical checks."""


SHORTCUT_TAG = "[SHORTCUT]"               # §7: change_log mark of a rewritten single-passage shortcut


@dataclass(frozen=True)
class Question:
    qid: str
    question: str
    category: str                        # one of CATEGORIES
    hops: tuple[tuple[str, ...], ...]    # hop_slots keys per hop
    missing_hops: frozenset[int] | None  # 0-based, stored (NEW82 missing_rr); None = from D5≈ (§4)
    core: str | None = None              # HO only
    shortcut: bool | None = None         # HO only: change_log carries SHORTCUT_TAG (§5, §7)
    prod_d5_missing: frozenset[int] | None = None   # OLD31 only: prod D5 hops_hit False (§4 另附)


@dataclass(frozen=True)
class QuestionSet:
    name: str
    questions: tuple[Question, ...]
    sources: Mapping[str, str]           # input file path -> sha256

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(q.qid for q in self.questions)

    @property
    def ids_sha256(self) -> str:
        return ids_sha256(self.ids)

    @property
    def n_hops(self) -> int:
        return sum(len(q.hops) for q in self.questions)

    def by_id(self) -> Mapping[str, Question]:
        return MappingProxyType({q.qid: q for q in self.questions})


def question_gold(q: Question, units: VerseUnits | None = None,
                  vindex: VerseIndex | None = None) -> tuple[frozenset[str], ...]:
    """§4 gold passage set of each hop of `q`, in hop order."""
    return tuple(hop_gold(h, units, vindex) for h in q.hops)


def _lookup(table: Mapping[str, str], key: str, what: str) -> str:
    if key not in table:
        raise IntegrityError(f"{what} {key!r} has no §2 category")
    return table[key]


def _hops(hop_slots: Sequence[Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(h) for h in hop_slots)


def _missing(indices: Iterable[int], n_hops: int, qid: str) -> frozenset[int]:
    out = frozenset(indices)
    if not all(isinstance(i, int) and 0 <= i < n_hops for i in out):
        raise IntegrityError(f"{qid}: missing hops {sorted(out)} outside 0..{n_hops - 1}")
    return out


def _pinned_set(name: str, questions: tuple[Question, ...], files: Iterable[Path]) -> QuestionSet:
    qs = QuestionSet(name, questions, MappingProxyType({str(p): FILE_SHA256[p] for p in files}))
    expect(f"{name} size (questions, hops)", (len(qs.questions), qs.n_hops), SET_SIZES[name])
    expect(f"{name} ids sha256", qs.ids_sha256, IDS_SHA256[name])
    return qs


@functools.cache
def load_new82() -> QuestionSet:
    """§2 NEW82 in file order; missing_hops = PN question_summary.json missing_rr (0-based)."""
    rows = [q for q in json.loads(read_pinned(NEW82_FILE, FILE_SHA256[NEW82_FILE]))["questions"]
            if not (q["status"] == "reject" or q["reject_reason"] or q["dedup_drop"])]
    summary = json.loads(read_pinned(NEW82_SUMMARY, FILE_SHA256[NEW82_SUMMARY]))
    expect("question_summary ids", [s["id"] for s in summary], [q["id"] for q in rows])
    questions = tuple(
        Question(q["id"], q["question"], _lookup(NEW82_CATEGORY, q["category"], "category"),
                 _hops(q["hop_slots"]), _missing(s["missing_rr"], len(q["hop_slots"]), q["id"]))
        for q, s in zip(rows, summary))
    return _pinned_set("new82", questions, (NEW82_FILE, NEW82_SUMMARY))


@functools.cache
def load_old31() -> QuestionSet:
    """§2 OLD31: usable.json questions with prod D5 m > 0, usable order. Its §4 missing hops come
    from D5≈ (missing_hops None); the prod D5 hops_hit False ones are kept as prod_d5_missing."""
    usable = json.loads(read_pinned(OLD31_FILE, FILE_SHA256[OLD31_FILE]))
    api = {r["id"]: r for r in json.loads(read_pinned(OLD31_API, FILE_SHA256[OLD31_API]))}
    questions = []
    for q in usable:
        r = api[q["id"]]
        expect(f"{q['id']} api question", r["question"], q["question"])
        if int(r["m"]) <= 0:
            continue
        hit = r["D5"]["hops_hit"]
        expect(f"{q['id']} hops_hit length", len(hit), len(q["hop_slots"]))
        questions.append(Question(
            q["id"], q["question"], _lookup(OLD31_CATEGORY, q["id"].rsplit("_", 1)[0], "id prefix"),
            _hops(q["hop_slots"]), None,
            prod_d5_missing=_missing((i for i, h in enumerate(hit) if not h), len(hit), q["id"])))
    return _pinned_set("old31", tuple(questions), (OLD31_FILE, OLD31_API))


def _ho_hops(qid: str, hops: Any) -> tuple[tuple[str, ...], ...]:
    lo, hi = HO_HOPS
    if not (isinstance(hops, list) and lo <= len(hops) <= hi):
        raise HoFormatError(f"{qid}: hop_slots needs {lo}-{hi} hops")
    for hop in hops:
        if not (isinstance(hop, list) and hop and all(isinstance(k, str) for k in hop)):
            raise HoFormatError(f"{qid}: each hop must be a non-empty list of slot keys")
        for key in hop:
            if is_half_verse_key(key):
                raise HalfVerseKeyError(f"{qid}: half-verse key {key!r} (§7 forbids it)")
            if not _HO_SLOT.fullmatch(key):
                raise HoFormatError(f"{qid}: slot {key!r} is not a whole or merged verse key")
    return _hops(hops)


def _ho_question(item: Any) -> Question:
    if not isinstance(item, dict):
        raise HoFormatError(f"HO item is not an object: {item!r:.80}")
    qid = str(item.get("id", "?"))
    absent = [f for f in HO_FIELDS if f not in item]
    if absent:
        raise HoFormatError(f"{qid}: missing fields {absent}")
    prefix = next((p for p in HO_CATEGORY if qid.startswith(p)), None)
    if prefix is None:
        raise HoFormatError(f"{qid}: id prefix is not one of {list(HO_CATEGORY)}")
    if NEW82_CATEGORY.get(item["category"]) != HO_CATEGORY[prefix]:
        raise HoFormatError(f"{qid}: category {item['category']!r} does not match prefix {prefix}")
    for name in ("question", "core"):
        if not (isinstance(item[name], str) and item[name].strip()):
            raise HoFormatError(f"{qid}: {name} must be a non-empty string")
    if not isinstance(item["change_log"], str):
        raise HoFormatError(f"{qid}: change_log must be a string (it carries {SHORTCUT_TAG})")
    return Question(qid, item["question"], HO_CATEGORY[prefix], _ho_hops(qid, item["hop_slots"]),
                    None, item["core"], shortcut=SHORTCUT_TAG in item["change_log"])


def _check_disjoint(questions: Sequence[Question], golds: Mapping[str, tuple[frozenset[str], ...]],
                    owner: dict[str, str]) -> None:
    """§7: no two hops of a question, no two HO questions, no HO vs NEW82/OLD31 share gold."""
    for q in questions:
        own: dict[str, int] = {}
        for h, gold in enumerate(golds[q.qid]):
            for pid in gold:
                if own.setdefault(pid, h) != h:
                    raise HoFormatError(f"{q.qid}: hops {own[pid]} and {h} share {pid}")
                if owner.get(pid, q.qid) != q.qid:
                    raise HoFormatError(f"{q.qid}: gold {pid} overlaps {owner[pid]}")
        owner.update({pid: q.qid for pid in own})


def _check_cores(questions: Sequence[Question]) -> None:
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.core] = counts.get(q.core, 0) + 1
    over = sorted(c for c, n in counts.items() if n > HO_MAX_PER_CORE)
    if over:
        raise HoFormatError(f"cores used by more than {HO_MAX_PER_CORE} questions: {over}")


def check_ho_items(items: Sequence[Any]) -> tuple[Question, ...]:
    """§7 mechanical checks on HO items (fields, prefixes, keys, gold, non-overlap, core <= 2)."""
    if not isinstance(items, list) or not items:
        raise HoFormatError("HO needs a non-empty list of question objects")
    questions = tuple(_ho_question(item) for item in items)
    ids_sha256(q.qid for q in questions)
    golds = {q.qid: question_gold(q) for q in questions}
    owner = {pid: f"{s.name}:{q.qid}" for s in (load_new82(), load_old31())
             for q in s.questions for gold in question_gold(q) for pid in gold}
    _check_disjoint(questions, golds, owner)
    _check_cores(questions)
    return questions


def load_ho(path: Path = HO_PATH, expected_sha256: str | None = None) -> QuestionSet:
    """§7 HO file {"questions": [...]} after check_ho_items; optional frozen sha256 (附錄 B)."""
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise IntegrityError(f"{path}: sha256 {sha} is not the frozen {expected_sha256}")
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise HoFormatError(f"{path}: top level must be an object with a 'questions' list")
    return QuestionSet("ho", check_ho_items(doc.get("questions")), MappingProxyType({str(path): sha}))


def load_question_set(name: str) -> QuestionSet:
    """'new82' | 'old31' | 'ho' (HO_PATH). Reads questions only; guard runs with assert_set_allowed."""
    loaders = {"new82": load_new82, "old31": load_old31, "ho": load_ho}
    if name not in loaders:
        raise GdError(f"unknown question set {name!r}; expected one of {sorted(loaders)}")
    return loaders[name]()
