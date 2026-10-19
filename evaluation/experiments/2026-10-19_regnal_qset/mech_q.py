"""Mechanical checks of the writers' questions and of the labeller's reading (qset.md §4).

Validity (an invalid question is dropped and its slot refilled once; it never enters a denominator):
  v_slot        the job's output has exactly its slot labels, one non-empty question each (≤ MAX_CHARS)
  v_simplified  no simplified-only character (the set's questions are Traditional Chinese)
  v_duplicate   the same question text (NFKC, spaces dropped) as an earlier item of the set
  v_answer      a positive question names its answer king (S1a, S1c, S4); a name the start king
                shares, or an alias that is another chain king's name, does not count
Flags (recorded, the item stays in every denominator: a reader may well phrase a question so):
  f_start_unnamed  no name of the start king (or, S1b, of either end) in the question
  f_between        a king strictly between the start and the answer is named (S1a, S1b, S1c)
Label consistency (labeller vs spec; inconsistent items stay in the denominator and are reported
apart, never dropped): positives need the same intent, the start king, the kingdom (or 不明), k for
offset, n for usurper_n, the other end for handovers; a near miss is consistent when the labeller did
not read it as one of the four positive intents.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from q_common import KD, POS_INTENTS, Violation
from spec_q import Chains

MAX_CHARS = 200
# characters that exist only in simplified Chinese (each traditional form differs)
SIMPLIFIED = frozenset("这们说时国为过对来见问门长东车书经实关会犹亚约罗吗让还从与亲谁该应开")
# non-king words that contain a king's name (押沙龍 ⊃ 沙龍, 亞哈隨魯 ⊃ 亞哈, 以利亞撒 ⊃ 亞撒, …)
BLOCKERS = ("押沙龍", "亞哈隨魯", "以利亞撒", "亞撒黑", "亞比雅他", "約哈難", "約雅大")


class NameFinder:
    """Chain-king names in a text, longest first, none inside one already taken (trigger._kings rule),
    with BLOCKERS taken first so that their inner names are not read as kings."""

    def __init__(self, ch: Chains):
        self.ch = ch
        names = {n for x in ch.on_chain() for n in ch.names(x)}
        self.terms = sorted(names | set(BLOCKERS), key=lambda n: (-len(n), n))
        self.owners = {n: [x for x in ch.on_chain() if n in ch.names(x)] for n in names}

    def names(self, text: str) -> list[str]:
        q = unicodedata.normalize("NFKC", text or "")
        taken: list[tuple[int, int, str]] = []
        for term in self.terms:
            for m in re.finditer(re.escape(term), q):
                if not any(m.start() < e and s < m.end() for s, e, _ in taken):
                    taken.append((m.start(), m.end(), term))
        return [t for _, _, t in sorted(taken) if t not in BLOCKERS]

    def kings(self, text: str) -> set[str]:
        """Every chain king one of whose names occurs (a shared name gives all its owners)."""
        return {x for n in self.names(text) for x in self.owners[n]}

    def names_king(self, text: str, x: str) -> bool:
        return any(n in self.ch.names(x) for n in self.names(text))


def norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def slot_violations(job: Mapping[str, Any], output: Mapping[str, Any] | None) -> tuple[dict[str, str], list[Violation]]:
    """({slot label: question}, v_slot violations) of a writer job's structured output."""
    want = [s["slot"] for s in job["slots"]]
    got: dict[str, str] = {}
    bad = []
    for it in (output or {}).get("items") or []:
        lab, q = it.get("slot"), it.get("question")
        if lab not in want or lab in got:
            bad.append(Violation("v_slot", f"unexpected or repeated slot {lab!r}"))
            continue
        if not isinstance(q, str) or not q.strip() or len(q) > MAX_CHARS:
            bad.append(Violation("v_slot", f"{lab}: empty or longer than {MAX_CHARS}"))
            continue
        got[lab] = q.strip()
    bad += [Violation("v_slot", f"{lab}: no question") for lab in want if lab not in got and
            not any(v.detail.startswith(f"{lab}:") for v in bad)]
    return got, bad


def between(ch: Chains, slot: Mapping[str, Any]) -> list[str]:
    """Kings strictly between the start and the answer (S1b: between the two ends)."""
    ids = ch.chain[slot["kingdom"]]
    if slot["qtype"] == "S1b":
        a, b = ch.idx(slot["start"]), ch.idx(slot["other"])
    elif slot["qtype"] in ("S1a", "S1c"):
        a, b = ch.idx(slot["start"]), ch.idx(slot["gold"])
    else:
        return []
    lo, hi = sorted((a, b))
    return [ids[i] for i in range(lo + 1, hi)]


def item_checks(ch: Chains, finder: NameFinder, slot: Mapping[str, Any], question: str
                ) -> tuple[list[Violation], list[str]]:
    """(validity violations, flags) of one question (duplicates are checked over the set, ``dedupe``)."""
    bad, flags = [], []
    if SIMPLIFIED & set(question):
        bad.append(Violation("v_simplified", "".join(sorted(SIMPLIFIED & set(question)))))
    named = finder.kings(question)
    ends = {slot["start"]} | ({slot["other"]} if slot.get("other") else set())
    shared = {n for e in ends for n in ch.names(e)}
    if slot["kind"] == "pos" and slot["qtype"] != "S1b":
        # the answer's own names: an alias that is another king's name (亞哈謝 also called 約哈斯) is no leak
        gold_names = [n for n in ch.safe_names(slot["gold"]) if n not in shared]
        if any(n in finder.names(question) for n in gold_names):
            bad.append(Violation("v_answer", f"names the answer king {ch.name(slot['gold'])}"))
    need = [slot["start"]] + ([slot["other"]] if slot["qtype"] == "S1b" else [])
    if not all(finder.names_king(question, e) for e in need):
        flags.append("f_start_unnamed")
    if slot["kind"] == "pos" and set(between(ch, slot)) & named - ends:
        flags.append("f_between")
    return bad, flags


def dedupe(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """v_duplicate on later copies (items in set order); returns new item dicts."""
    seen: set[str] = set()
    out = []
    for it in items:
        it = dict(it)
        key = norm(it.get("question") or "")
        if it.get("valid") and key in seen:
            it["valid"] = False
            it["violations"] = list(it.get("violations") or []) + [Violation("v_duplicate", "same text").as_dict()]
        elif it.get("valid"):
            seen.add(key)
        out.append(it)
    return out


def label_consistent(ch: Chains, finder: NameFinder, slot: Mapping[str, Any],
                     label: Mapping[str, Any] | None) -> tuple[bool | None, list[str]]:
    """(consistent, reasons); None when there is no label."""
    if label is None:
        return None, ["no label"]
    intent = label.get("intent")
    if slot["kind"] == "near":
        return (intent not in POS_INTENTS), ([] if intent not in POS_INTENTS else [f"intent {intent}"])
    why = []
    if intent != slot["intent"]:
        why.append(f"intent {intent}")
    ends = [slot["start"]] + ([slot["other"]] if slot["qtype"] == "S1b" else [])
    got = [label.get("king") or ""] + ([label.get("second_king") or ""] if slot["qtype"] == "S1b" else [])
    if slot["qtype"] == "S1b":
        if not any(all(finder.names_king(g, e) for g, e in zip(got, order)) for order in (ends, ends[::-1])):
            why.append("kings")
    elif not finder.names_king(got[0], slot["start"]):
        why.append("king")
    kd = KD.get(label.get("kingdom"))
    if kd and kd != slot["kingdom"]:
        why.append(f"kingdom {label.get('kingdom')}")
    if slot["qtype"] == "S1a" and label.get("k") != slot["k"]:
        why.append(f"k {label.get('k')}")
    if slot["qtype"] == "S1c" and label.get("n") != slot["n"]:
        why.append(f"n {label.get('n')}")
    return not why, why


def as_dicts(vs: Iterable[Violation]) -> list[dict[str, str]]:
    return [v.as_dict() for v in vs]
