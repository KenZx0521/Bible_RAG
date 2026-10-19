"""Mechanical checks of the writers' questions and of the labeller's reading (qset.md §4).

Validity (an invalid question is dropped and its slot refilled once; it never enters a denominator):
  v_slot        the job's output has exactly its slot labels, one non-empty question each (≤ MAX_CHARS)
  v_simplified  no simplified-only character (the set's questions are Traditional Chinese)
  v_duplicate   the same question text (NFKC, spaces dropped) as an earlier item of the set
  v_answer      a positive question names its answer king (S1a, S1c, S4); a name the start king
                shares, an alias that is another chain king's name, or a name inside a father
                marker of the start king (below) does not count
Flags (recorded, the item stays in every denominator: a reader may well phrase a question so):
  f_start_unnamed     no name of the start king (or, S1b, of either end) in the question
  f_between           a king strictly between the start and the answer is named (S1a, S1b, S1c),
                      a father marker's name not counted
  f_father_is_answer  the answer king is named only in the start king's father marker
Father marker (the scouting design §2.6 exception; the writer's note asks to tell homonyms apart,
and the father is the natural way): F written as the father of an end king X, F one of the names of
X's reference father, in 「F(王)的兒子X」「F(王)之子X」「X(F(王)的兒子)」「X(父親(是)F)」「X,父親(是)F」
「X是F的兒子」 (NFKC text, so （） are () and ， is ,; the forms of the rule seeds' markers).
Label consistency (labeller vs spec; inconsistent items stay in the denominator and are reported
apart, never dropped): positives need the same intent, the start king, the kingdom (or 不明), k for
offset, n for usurper_n, the other end for handovers; a near miss is consistent when the labeller did
not read it as one of the four positive intents.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from q_common import FLAGS, KD, POS_INTENTS, Violation
from spec_q import Chains

MAX_CHARS = 200
# characters that exist only in simplified Chinese (each traditional form differs)
SIMPLIFIED = frozenset("这们说时国为过对来见问门长东车书经实关会犹亚约罗吗让还从与亲谁该应开")
# non-king words that contain a king's name (押沙龍 ⊃ 沙龍, 亞哈隨魯 ⊃ 亞哈, 以利亞撒 ⊃ 亞撒, …)
BLOCKERS = ("押沙龍", "亞哈隨魯", "以利亞撒", "亞撒黑", "亞比雅他", "約哈難", "約雅大")
_SON = r"王?(?:的兒子|之子)"
_SON_BEFORE = re.compile(rf"{_SON}(?:,?(?:猶大|以色列)國?的?王)?")      # F … X
_LABEL = re.compile(r"[,、]?(?:父親?|其父)(?:是|為|名叫)?")              # X … F
_IS = re.compile(r"[,、]?(?:是|為)")                                       # X 是 F 的兒子
_BRACKET = re.compile(r"(?:二世)?\(([^()]*)\)")


class NameFinder:
    """Chain-king names in a text, longest first, none inside one already taken (trigger._kings rule),
    with BLOCKERS taken first so that their inner names are not read as kings."""

    def __init__(self, ch: Chains):
        self.ch = ch
        names = {n for x in ch.on_chain() for n in ch.names(x)}
        self.terms = sorted(names | set(BLOCKERS), key=lambda n: (-len(n), n))
        self.owners = {n: [x for x in ch.on_chain() if n in ch.names(x)] for n in names}

    def mentions(self, text: str) -> list[tuple[int, int, str]]:
        """(start, end, name) of the chain names in the NFKC text, in order (blockers dropped)."""
        q = unicodedata.normalize("NFKC", text or "")
        taken: list[tuple[int, int, str]] = []
        for term in self.terms:
            for m in re.finditer(re.escape(term), q):
                if not any(m.start() < e and s < m.end() for s, e, _ in taken):
                    taken.append((m.start(), m.end(), term))
        return [t for t in sorted(taken) if t[2] not in BLOCKERS]

    def names(self, text: str) -> list[str]:
        return [n for _, _, n in self.mentions(text)]

    def kings(self, text: str) -> set[str]:
        """Every chain king one of whose names occurs (a shared name gives all its owners)."""
        return {x for n in self.names(text) for x in self.owners[n]}

    def names_king(self, text: str, x: str) -> bool:
        return any(n in self.ch.names(x) for n in self.names(text))


def father_names(ch: Chains, x: str) -> set[str]:
    """x's reference father and, when he is a king of x's kingdom, every name of that king."""
    f = ch.field(x, "father")
    if not f:
        return set()
    return {f} | {n for y in ch.chain[ch.kingdom(x)] if f in ch.names(y) for n in ch.names(y)}


def _marks(q: str, f: tuple[int, int, str], x: tuple[int, int, str]) -> bool:
    """Mention f is written as the father of mention x (one of the module's marker forms)."""
    if f[1] <= x[0] and _SON_BEFORE.fullmatch(q, f[1], x[0]):
        return True
    if x[1] <= f[0]:
        if _LABEL.fullmatch(q, x[1], f[0]):
            return True
        if _IS.fullmatch(q, x[1], f[0]) and re.match(_SON, q[f[1]:]):
            return True
        b = _BRACKET.match(q, x[1])
        if b and b.start(1) <= f[0] and f[1] <= b.end(1):
            pre, post = q[b.start(1):f[0]], q[f[1]:b.end(1)]
            return (not pre and bool(re.fullmatch(_SON, post))) or \
                (bool(_LABEL.fullmatch(pre)) and not pre.startswith((",", "、")) and post in ("", "王"))
    return False


def father_marks(ch: Chains, finder: NameFinder, text: str, ends: Iterable[str]) -> set[int]:
    """Indices (in ``finder.mentions``) of the mentions written as the father of an end king."""
    q = unicodedata.normalize("NFKC", text or "")
    ms = finder.mentions(q)
    out: set[int] = set()
    for e in ends:
        fathers, own = father_names(ch, e), set(ch.names(e))
        xs = [m for m in ms if m[2] in own]
        out |= {i for i, m in enumerate(ms) if m[2] in fathers and any(_marks(q, m, x) for x in xs)}
    return out


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
    ends = {slot["start"]} | ({slot["other"]} if slot.get("other") else set())
    ms = finder.mentions(question)
    marks = father_marks(ch, finder, question, ends)
    free = [n for i, (_, _, n) in enumerate(ms) if i not in marks]      # names outside father markers
    shared = {n for e in ends for n in ch.names(e)}
    if slot["kind"] == "pos" and slot["qtype"] != "S1b":
        # the answer's own names: an alias that is another king's name (亞哈謝 also called 約哈斯) is no leak
        gold_names = [n for n in ch.safe_names(slot["gold"]) if n not in shared]
        if any(n in free for n in gold_names):
            bad.append(Violation("v_answer", f"names the answer king {ch.name(slot['gold'])}"))
        elif any(ms[i][2] in gold_names for i in marks):
            flags.append("f_father_is_answer")
    need = [slot["start"]] + ([slot["other"]] if slot["qtype"] == "S1b" else [])
    if not all(finder.names_king(question, e) for e in need):
        flags.append("f_start_unnamed")
    named = {x for n in free for x in finder.owners[n]}
    if slot["kind"] == "pos" and set(between(ch, slot)) & named - ends:
        flags.append("f_between")
    return bad, sorted(flags, key=FLAGS.index)


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
