"""Syntactic checks of drafted GEN questions, audit outputs and the three-way value comparison (prereg §3.4–§3.6).

Every rule whose input can be read is checked (not just the first; a schema error does not hide the question
rules); an error sends the draft back for the one mech fix. There is no gold here: the writer's value meets the
auditor's and the program gold after the value-blind audit (compare_values, after_audit). A detail is neutral
English tool text; the fragment of the question a rule points at is returned apart as ``quote`` (agent text), so a
fix prompt gives the detail the full prompt check and the quote the memory-marker check (prompts_g.Issue).
Questions are read NFKC-normalised; id, slot, X, Y, marker and the audit id are compared NFKC-normalised and
stripped (``canonical_item`` then writes the assigned strings back).

  schema          writer item fields and types (prompts_g.ITEM_SCHEMA); steps >= 2 with Genesis verse keys
  slot_match      id, slot, qtype, and the chain ids of X and Y as assigned
  names_present   X and Y by exact layer string
  extra_name      another name: the chain or gen_names extra_persons (the name_spans of Genesis 4/5/10/11 and
                  Abram's family; they hold some peoples and places too). The accepted forms of the required
                  marker, then X and Y, are masked first, longest first; the routing-lexicon superstrings
                  (gen_names lexicon_blockers) are masked as non-names, except one that overlaps a §5.2 rule-7
                  cue word without holding it (gencard's rule: 希伯來 in 希伯來到世上 names 希伯); names are
                  matched longest first and masked, so a name inside a longer one never counts (撒拉 in 瑪土撒拉);
                  a one-character name counts only in a name context (_name_context)
  marker_rule     a required marker missing from the question, written more than once, or not in the item's
                  ``marker``; a marker (「N的兒子A」 「N的父親A」 or 「A（N的…）」, A = X or Y) on a slot that takes
                  none; a marker other than the given one; a marker naming someone on the path
  v_number        Arabic digits; a Chinese numeral run followed by 歲年代世章節, a lone 十百千萬 followed by
                  多餘來 (百多歲), or two or more numeral characters (names masked first; 那一年, 同一年, 這一年
                  exempt; 一生 and 兩人 never match: a lone numeral before a non-unit)
  v_kin           孫 (not in 子孫 or 子子孫孫), 曾孫, 玄孫, 祖父, 曾祖, 高祖, numeral / 幾 / 多少 + 代
  v_source        創世記 missing, or another book named (OTHER_BOOKS, gen_names other_books)
  ordinal_form    第幾年, 第多少年
  yes_no          嗎 at a sentence end, 是否, 是不是, 有沒有
  multi_question  more than one question mark
  key_form        answer not a positive integer with 歲, or with 年 when the question asks (多少|幾)年 (not
                  多少年紀 / 年歲 / 年齡, which ask an age) or 多久

``syntax_violations(question, spec, names)`` runs the nine question rules (P2_RULES) on a bare question: the
P2 validity check of prereg §5.6 (qset-shaped {slot, question} items have no marker field, so only the
written phrase is checked). It is part of this file, so the F1a sha of mech_g.py pins it.

Known trade-offs (prereg §3.4 literal; the auditor covers numerals): 嗎 counts only at a sentence end (gencard's
rule 10 abstains on any 嗎); the marker is read in the 的父親 / 的兒子 spellings and the bracket form only
(gencard also reads 之父 / 之子); a lone 「（含）」 counts as the one-character name; 歷代誌 and one-character
book abbreviations are not other books.

§3.6 row 3 (writer = auditor ≠ program gold) needs no fix round, so it is a dispute whatever the round state:
the CPU comparison of the cited verses, the disputed part of Kay's page, then K-gold or the slot is deleted
(``Decision.closes_slot``: never retried, attrition 「問了別的量而刪的」 of §1.2). The spent-round sentence
(「任何值不一致都結束這次嘗試」) holds for the rows that need a fix; deleting the slot also ends the attempt.
"""
from __future__ import annotations

import functools
import importlib
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import banned_g as B
import prompts_g as P

RULES = ("schema", "slot_match", "names_present", "extra_name", "marker_rule", "v_number", "v_kin", "v_source",
         "ordinal_form", "yes_no", "multi_question", "key_form")
P2_RULES = ("names_present", "extra_name", "marker_rule", "v_number", "v_kin", "v_source", "ordinal_form", "yes_no",
            "multi_question")
VERSE_KEY = re.compile(r"^gen\.[0-9]{1,2}\.[0-9]{1,3}(?:-(?:gen\.[0-9]{1,2}\.)?[0-9]{1,3})?$")
NUMERALS = "零〇一二三四五六七八九十百千萬億兩廿卅壹貳參肆伍陸柒捌玖拾佰仟"
NUMERAL_UNITS = "歲年代世章節"
APPROX_HEADS, APPROX_TAILS = "十百千萬", "多餘來"         # 百多歲, 十多年, 百餘年, 十來歲
NUMBER_EXEMPT = ("那一年", "同一年", "這一年")
KIN_IDIOMS = ("子子孫孫",)
_NUM = f"[{NUMERALS}]"
DIGITS = re.compile(r"\d+")
NUMERAL_RUN = re.compile(f"{_NUM}+")
KIN_TERMS = re.compile(rf"曾孫|玄孫|祖父|曾祖|高祖|(?:\d+|{_NUM}+|幾|多少)\s*代")
ORDINAL = re.compile(r"第\s*(?:幾|多少)\s*年")
YES_NO = re.compile(r"嗎\s*(?:[?!。.]|$)|是否|是不是|有沒有")
ASKS_YEARS = re.compile(r"(?<!第)(?:多少|幾)\s*年(?![紀齡歲])|多久")
GENESIS = "創世記"
# every book of the text layer but Genesis (books.jsonl names; a store test checks it), plus the unnumbered stems
OTHER_BOOKS = (
    "出埃及記", "利未記", "民數記", "申命記", "約書亞記", "士師記", "路得記", "撒母耳記上", "撒母耳記下", "撒母耳記",
    "列王紀上", "列王紀下", "列王紀", "歷代志上", "歷代志下", "歷代志", "以斯拉記", "尼希米記", "以斯帖記", "約伯記",
    "詩篇", "箴言", "傳道書", "雅歌", "以賽亞書", "耶利米書", "耶利米哀歌", "以西結書", "但以理書", "何西阿書", "約珥書",
    "阿摩司書", "俄巴底亞書", "約拿書", "彌迦書", "那鴻書", "哈巴谷書", "西番雅書", "哈該書", "撒迦利亞書", "瑪拉基書",
    "馬太福音", "馬可福音", "路加福音", "約翰福音", "使徒行傳", "羅馬書", "哥林多前書", "哥林多後書", "加拉太書",
    "以弗所書", "腓立比書", "歌羅西書", "帖撒羅尼迦前書", "帖撒羅尼迦後書", "提摩太前書", "提摩太後書", "提多書",
    "腓利門書", "希伯來書", "雅各書", "彼得前書", "彼得後書", "約翰一書", "約翰二書", "約翰三書", "猶大書", "啟示錄")
MASK = "\x00"
# one-character names (含, 弗, 赫, 閃 …) count only next to list or kin context, never inside a word (包含, 閃電)
_PUNCT = set(" \t\n、,。.;:!?「」『』()[]〔〕【】《》〈〉\"'“”‘’…—–-‧·")
PREV_OK = _PUNCT | set("和與及跟同或了生是比從到")
NEXT_OK = _PUNCT | set("和與及跟同或生是比活死去幾多那")
STRONG_PREV = ("兒子", "父親", "名叫", "叫做", "長子", "次子")
KIN_AFTER_DE = ("兒子", "父親", "後代", "後裔", "子孫", "兒女", "兄弟", "弟兄", "哥哥", "弟弟", "長子", "妻子", "母親",
                "祖先", "家")
# a one-character chain name (閃) also counts right before a rule-7 event word, 在世, or 的 + an age word / 一生
ALIVE_WORDS, LIFE_WORDS = ("在世",), ("一生",)
# gencard.trigger's §5.2 rule-7 word tuples mech_g reads (imported, never copied; gencard never runs here)
TRIGGER_WORD_NAMES = ("RULE7_WORDS", "AGE_WORDS", "BIRTH_WORDS", "BEGET_WORDS", "DEATH_WORDS")
SEVERITY_ORDER = ("ok", "minor", "major", "critical")
# forwarded audit findings: a verse key is kept, every other number masked (redact_numbers)
_REF = r"[a-z0-9]{2,4}\.[0-9]{1,3}\."
VERSE_REF = re.compile(rf"(?<![a-z0-9]){_REF}[0-9]{{1,3}}(?:-(?:{_REF})?[0-9]{{1,3}})?")
NUMBER_TOKEN = re.compile(rf"\d+|{_NUM}{{2,}}|{_NUM}(?=[{NUMERAL_UNITS}{APPROX_TAILS}])")
REDACTED = "#"


@dataclass(frozen=True)
class Violation:
    """One failed rule: ``detail`` is tool text, ``quote`` the question fragment it points at (agent text)."""
    rule: str
    detail: str
    quote: str = ""
    level: str = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _v(rule: str, detail: str, quote: str = "") -> Violation:
    return Violation(rule, detail, quote)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _readable(question: Any) -> bool:
    return isinstance(question, str) and bool(question.strip())


def _text_is(value: Any, want: str) -> bool:
    """An id / slot / name string as assigned, NFKC-normalised and stripped."""
    return isinstance(value, str) and norm(value).strip() == want


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + MASK * (end - start) + text[end:]


def _mask_strings(text: str, needles: Iterable[str]) -> str:
    for s in sorted({n for n in needles if n}, key=lambda n: (-len(n), n)):
        text = text.replace(s, MASK * len(s))
    return text


def _mask_regex(text: str, pattern: re.Pattern[str]) -> str:
    for m in reversed(list(pattern.finditer(text))):
        text = _mask(text, m.start(), m.end())
    return text


@functools.lru_cache(maxsize=None)
def trigger_words() -> Mapping[str, tuple[str, ...]]:
    """gencard.trigger's rule-7 word tuples (TRIGGER_WORD_NAMES), imported on first use from this experiment's
    gencard; only the words are read, the trigger never runs on a question here (prereg §5.5)."""
    mod = importlib.import_module("gencard.trigger")
    if Path(mod.__file__).resolve().parent != B.GENCARD_DIR.resolve():
        raise RuntimeError(f"gencard.trigger resolved to {mod.__file__}, not {B.GENCARD_DIR}")
    words = {k: getattr(mod, k, None) for k in TRIGGER_WORD_NAMES}
    bad = [k for k, v in words.items() if not (isinstance(v, tuple) and v and all(isinstance(w, str) and w for w in v))]
    if bad:
        raise RuntimeError(f"gencard.trigger {bad} must be non-empty tuples of non-empty strings")
    return MappingProxyType(words)


def _spans(text: str, words: Iterable[str]) -> list[tuple[int, int]]:
    """Every occurrence of every word, overlaps included (gencard.trigger._spans)."""
    out = []
    for w in words:
        i = text.find(w)
        while i >= 0:
            out.append((i, i + len(w)))
            i = text.find(w, i + 1)
    return out


def _swallows(s: int, e: int, cues: Sequence[tuple[int, int]]) -> bool:
    """text[s:e] overlaps a cue word without holding it (gencard.trigger._swallows)."""
    return any(a < e and s < b and not (s <= a and b <= e) for a, b in cues)


def _mask_blockers(text: str, blockers: Iterable[str]) -> str:
    """The routing-lexicon superstrings masked as non-names, longest first; a blocker that would swallow a
    rule-7 cue word is left alone, so the chain name in it still counts (希伯來 in 希伯來到世上)."""
    cues = _spans(text, trigger_words()["RULE7_WORDS"])
    for b in sorted({n for n in blockers if n}, key=lambda n: (-len(n), n)):
        for m in reversed(list(re.finditer(re.escape(b), text))):
            if not _swallows(m.start(), m.end(), cues):
                text = _mask(text, m.start(), m.end())
    return text


# ---------------------------------------------------------------- schema
def check_gen_output(out: Any) -> list[Violation]:
    """The writer's StructuredOutput wrapper {status, reason, item} (item checked by check_draft)."""
    if not isinstance(out, Mapping):
        return [_v("schema", "the output must be an object {status, reason, item}")]
    bad = []
    if out.get("status") not in P.GEN_STATUSES:
        bad.append(_v("schema", f"status must be one of {', '.join(P.GEN_STATUSES)}"))
    if not isinstance(out.get("reason"), str):
        bad.append(_v("schema", "reason must be a string"))
    if out.get("status") in ("drafted", "revised", "no_change") and not isinstance(out.get("item"), Mapping):
        bad.append(_v("schema", f"status {out.get('status')} needs the complete question in item"))
    if out.get("status") in ("abandoned", "dropped") and out.get("item") is not None:
        bad.append(_v("schema", f"status {out.get('status')} needs item null"))
    return bad


def _answer_readable(ans: Any) -> bool:
    return isinstance(ans, Mapping) and "value" in ans and "unit" in ans


def _schema(q: Mapping[str, Any]) -> list[Violation]:
    """Field and type errors; a missing or unreadable field never stops the other checks."""
    out = []
    missing = [k for k in P.ITEM_KEYS if k not in q]
    if missing:
        out.append(_v("schema", f"missing fields: {', '.join(missing)}"))
    if "question" in q and not _readable(q["question"]):
        out.append(_v("schema", "question must be a non-empty string"))
    for k in ("id", "slot", "X", "Y", "convention", "notes"):
        if k in q and not isinstance(q[k], str):
            out.append(_v("schema", f"{k} must be a string"))
    if "qtype" in q and q["qtype"] not in P.QTYPES:
        out.append(_v("schema", f"qtype must be {' or '.join(P.QTYPES)}"))
    if "marker" in q and q["marker"] is not None and not isinstance(q["marker"], str):
        out.append(_v("schema", "marker must be a string or null"))
    if "answer" in q:
        if not _answer_readable(q["answer"]):
            out.append(_v("schema", "answer must be an object {value, unit}"))
        elif q["answer"]["unit"] not in P.UNITS:
            out.append(_v("schema", f"answer.unit must be {' or '.join(P.UNITS)}"))
    if "steps" in q:
        steps = q["steps"]
        if not (isinstance(steps, list) and len(steps) >= 2 and all(
                isinstance(s, Mapping) and all(isinstance(s.get(k), str) for k in P.STEP_KEYS) for s in steps)):
            out.append(_v("schema", "steps must list at least two {person, fact, verse} entries"))
        elif not all(VERSE_KEY.match(s["verse"].strip()) for s in steps):
            out.append(_v("schema", "every steps verse must be a Genesis verse key such as gen.1.1"))
    return out


def _slot(q: Mapping[str, Any], spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    """The fields present, as assigned (a missing one is schema's)."""
    out = []
    if any(k in q and not _text_is(q[k], want) for k, want in (("id", spec.qid), ("slot", spec.slot_id))):
        out.append(_v("slot_match", f"id must be {spec.qid} and slot must be {spec.slot_id}"))
    if "qtype" in q and q["qtype"] != spec.qtype:
        out.append(_v("slot_match", f"qtype must be {spec.qtype}"))
    person = {k: names.id_of(norm(q[k]).strip()) if isinstance(q.get(k), str) else None for k in ("X", "Y")}
    if any(k in q and person[k] != want for k, want in (("X", spec.x_id), ("Y", spec.y_id))):
        out.append(_v("slot_match", f"X must be {spec.x} and Y must be {spec.y}"))
    return out


def canonical_item(item: Mapping[str, Any], spec: P.SlotSpec) -> dict[str, Any]:
    """A copy of an item check_draft passed, with id, slot, qtype, X, Y and marker written as assigned."""
    return {**item, "id": spec.qid, "slot": spec.slot_id, "qtype": spec.qtype, "X": spec.x, "Y": spec.y,
            "marker": spec.marker}


# ---------------------------------------------------------------- names and markers
def _marker_forms(spec: P.SlotSpec) -> re.Pattern[str] | None:
    """The accepted spellings of the required marker: 「C的父親Y」 / 「Y（C的父親）」 (or 「F的兒子X」 / 「X（F的兒子）」)."""
    if spec.marker is None:
        return None
    end = spec.y if spec.marker_end == "Y" else spec.x
    rel = "父親" if spec.marker_end == "Y" else "兒子"
    n, a = re.escape(spec.marker_person), re.escape(end)
    return re.compile(rf"{n}的{rel}{a}|{a}\s*\(\s*{n}的{rel}\s*\)")


def _event_next(t: str, i: int) -> bool:
    """t[i] is right before a rule-7 event word, 在世, or 的 + an age word, 一生 or an event word."""
    w = trigger_words()
    events = w["BIRTH_WORDS"] + w["BEGET_WORDS"] + w["DEATH_WORDS"]
    rest = t[i + 1:]
    return rest.startswith(events + ALIVE_WORDS) or (
        rest.startswith("的") and rest[1:].startswith(w["AGE_WORDS"] + LIFE_WORDS + events))


def _name_context(t: str, i: int, chain: bool = False) -> bool:
    """A one-character name at t[i] counts after 兒子/父親/名叫 …, or between list or kin context on both sides;
    a chain one (閃) also right before an event or age word (閃過世, 閃出生, 閃在世, 閃的年紀). The extra ones
    (含, 弗, 赫) stay strict: 「（含出生那年）」 reads as 'including'."""
    if chain and _event_next(t, i):
        return True
    if any(t[max(i - len(w), 0):i] == w for w in STRONG_PREV) or (i > 0 and t[i - 1] == "叫"):
        return True
    prev_ok = i == 0 or t[i - 1] in PREV_OK
    nxt = t[i + 1:i + 2]
    next_ok = nxt == "" or nxt in NEXT_OK or (nxt == "的" and t[i + 2:].startswith(KIN_AFTER_DE))
    return prev_ok and next_ok


def extra_names(question: str, spec: P.SlotSpec, names: P.Names) -> list[str]:
    """Names other than X, Y and the required marker, in order of first appearance."""
    t = norm(question)
    forms = _marker_forms(spec)
    if forms is not None:
        t = _mask_regex(t, forms)
    t = _mask_blockers(_mask_strings(t, (spec.x, spec.y)), names.lexicon_blockers)
    chain = {p.name for p in names.chain}
    found: list[tuple[int, str]] = []
    for name in sorted(set(names.known) - {spec.x, spec.y}, key=lambda n: (-len(n), n)):
        for m in list(re.finditer(re.escape(name), t)):
            if len(name) == 1 and not _name_context(t, m.start(), name in chain):
                continue
            found.append((m.start(), name))
            t = _mask(t, m.start(), m.end())
    return list(dict.fromkeys(n for _, n in sorted(found)))


def marker_phrases(question: str, spec: P.SlotSpec, names: P.Names) -> list[tuple[str, str, str]]:
    """Every (N, 父親|兒子, A) phrase 「N的…A」 or 「A（N的…）」 with A = X or Y and N a known person."""
    t = _mask_blockers(norm(question), names.lexicon_blockers)
    ns = "|".join(re.escape(n) for n in sorted(names.known, key=lambda n: (-len(n), n)))
    ends = "|".join(re.escape(a) for a in sorted({spec.x, spec.y}, key=lambda n: (-len(n), n)))
    pat = re.compile(rf"(?P<n>{ns})的(?P<rel>兒子|父親)(?P<a>{ends})"
                     rf"|(?P<a2>{ends})\s*\(\s*(?P<n2>{ns})的(?P<rel2>兒子|父親)\s*\)")
    out = []
    for m in pat.finditer(t):
        out.append((m["n"], m["rel"], m["a"]) if m["n"] else (m["n2"], m["rel2"], m["a2"]))
    return out


def _names_rules(question: str, spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    t, out = norm(question), []
    for who in (spec.x, spec.y):
        if who not in t:
            out.append(_v("names_present", f"the question must name {who} exactly as written here"))
    extra = extra_names(question, spec, names)
    if extra:
        tail = " and the identifying phrase" if spec.marker else ""
        out.append(_v("extra_name", f"the question uses another name (a person, people or place) besides {spec.x} "
                                    f"and {spec.y}{tail}", "、".join(extra)))
    return out


def _phrase(found: Iterable[tuple[str, str, str]]) -> str:
    return "、".join(f"{n}的{rel}{a}" for n, rel, a in found)


def _marker_phrase_rule(question: str, spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    """The identifying phrase as written in the question (prereg §3.2: exactly one, off the path)."""
    out, found = [], marker_phrases(question, spec, names)
    if spec.marker is None:
        if found:
            out.append(_v("marker_rule", f"this question takes no identifying phrase: name only {spec.x} and {spec.y}",
                          _phrase(found)))
    else:
        allowed = (spec.marker_person, "父親" if spec.marker_end == "Y" else "兒子",
                   spec.y if spec.marker_end == "Y" else spec.x)
        n = found.count(allowed)
        if n == 0:
            out.append(_v("marker_rule",
                          f"the question must contain the identifying phrase {spec.marker} exactly as given"))
        elif n > 1:
            out.append(_v("marker_rule",
                          f"the question must contain the identifying phrase {spec.marker} exactly once"))
        other = [f for f in found if f != allowed]
        if other:
            out.append(_v("marker_rule", f"the only identifying phrase allowed is {spec.marker}", _phrase(other)))
    on_path = [f for f in found if f[0] in spec.path]
    if on_path:
        out.append(_v("marker_rule", f"an identifying phrase names someone on the line from {spec.x} to {spec.y}",
                      _phrase(on_path)))
    return out


def _marker_field(q: Mapping[str, Any], spec: P.SlotSpec) -> list[Violation]:
    """The item's ``marker`` field (a writer item has one; a bare P2 question does not)."""
    if "marker" not in q:
        return []
    field = norm(q["marker"]).strip() if isinstance(q["marker"], str) else ""
    if spec.marker is None:
        return [_v("marker_rule", "this question takes no identifying phrase: set marker to null")] if field else []
    return [] if field == spec.marker else [_v("marker_rule", f"marker must be {spec.marker}")]


# ---------------------------------------------------------------- wording
def _masked_names(question: str, spec: P.SlotSpec, names: P.Names) -> str:
    t = norm(question)
    forms = _marker_forms(spec)
    if forms is not None:
        t = _mask_regex(t, forms)
    return _mask_strings(t, (spec.x, spec.y, *names.known, *names.lexicon_blockers))


def numerals(question: str, spec: P.SlotSpec, names: P.Names) -> list[str]:
    """Numeral marks of the question, after masking names and the exempt idioms."""
    t = _mask_strings(_masked_names(question, spec, names), NUMBER_EXEMPT)
    hits = [m.group() for m in DIGITS.finditer(t)]
    for m in NUMERAL_RUN.finditer(t):
        run, nxt = m.group(), t[m.end():m.end() + 1]
        unit = nxt and nxt in NUMERAL_UNITS
        approx = run in APPROX_HEADS and nxt and nxt in APPROX_TAILS
        if len(run) >= 2 or unit or approx:
            hits.append(run + (nxt if unit or approx else ""))
    return hits


def kin_terms(question: str, spec: P.SlotSpec, names: P.Names) -> list[str]:
    t = _mask_strings(_masked_names(question, spec, names), KIN_IDIOMS)
    hits = [(m.start(), m.group()) for m in KIN_TERMS.finditer(t)]
    covered = {i for m in KIN_TERMS.finditer(t) for i in range(m.start(), m.end())}
    for m in re.finditer("孫", t):
        i = m.start()
        if i in covered or (t[i - 1:i] == "子" and t[i + 1:i + 2] != "子"):
            continue
        hits.append((i, "孫"))
    return [h for _, h in sorted(hits)]


def _wording(question: str, spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    t, out = norm(question), []
    nums = numerals(question, spec, names)
    if nums:
        out.append(_v("v_number", "the question contains a numeral or a chapter or verse number", "、".join(nums)))
    kin = kin_terms(question, spec, names)
    if kin:
        out.append(_v("v_kin", "the question uses a kinship word that fixes the number of generations", "、".join(kin)))
    if GENESIS not in t:
        out.append(_v("v_source", f"the question must name {GENESIS}"))
    books = [b for b in sorted(set(OTHER_BOOKS) | set(names.other_books), key=lambda b: (-len(b), b)) if b in t]
    if books:
        out.append(_v("v_source", "the question names another book", "、".join(books)))
    ords = ORDINAL.findall(t)
    if ords:
        out.append(_v("ordinal_form", "the question asks in which year of someone's life (an ordinal year)",
                      "、".join(ords)))
    yn = [m.group().rstrip("?!。. ") or m.group() for m in YES_NO.finditer(t)]
    if yn:
        out.append(_v("yes_no", "the question is a yes/no question", "、".join(yn)))
    if t.count("?") > 1:
        out.append(_v("multi_question", "the question asks more than one question"))
    return out


def _key(question: str, ans: Mapping[str, Any]) -> list[Violation]:
    want = "年" if ASKS_YEARS.search(norm(question)) else "歲"
    if not (_is_int(ans["value"]) and ans["value"] >= 1):
        return [_v("key_form", "answer.value must be a positive integer")]
    if ans["unit"] != want:
        why = "the question asks for a number of years" if want == "年" else "the question asks for an age"
        return [_v("key_form", f"{why}: answer.unit must be {want}")]
    return []


def syntax_violations(question: str, spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    """The nine question rules (P2_RULES) on a bare question of slot `spec`: the P2 validity check (prereg §5.6)
    and the question part of check_draft. A qset-shaped item has no marker field: only the phrase is checked."""
    if not _readable(question):
        raise ValueError("syntax_violations needs a non-empty question string")
    return _names_rules(question, spec, names) + _marker_phrase_rule(question, spec, names) + _wording(
        question, spec, names)


def check_draft(item: Any, spec: P.SlotSpec, names: P.Names) -> list[Violation]:
    """Every §3.4 rule on one drafted item of slot `spec` (gen_names lists in `names`); a schema error does not
    stop the rules whose fields can be read."""
    if not isinstance(item, Mapping):
        return [_v("schema", "item must be an object")]
    out = _schema(item) + _slot(item, spec, names) + _marker_field(item, spec)
    question = item.get("question")
    if not _readable(question):
        return out
    out += syntax_violations(question, spec, names)
    return out + (_key(question, item["answer"]) if _answer_readable(item.get("answer")) else [])


def errors_of(found: Sequence[Violation]) -> list[Violation]:
    return [v for v in found if v.level == "error"]


def fix_issues(found: Sequence[Violation]) -> tuple[P.Issue, ...]:
    """Fix-request lines of the mech round: the detail as tool text, the quote as agent text."""
    out = {}
    for v in errors_of(found):
        parts = (("tool", v.detail),) + ((("tool", ": "), ("agent", v.quote)) if v.quote else ())
        out.setdefault((v.detail, v.quote), P.Issue.of(*parts))
    return tuple(out.values())


# ---------------------------------------------------------------- audit output
def check_audit(out: Any, qid: str) -> list[Violation]:
    """The auditor's StructuredOutput {id, value, reading, findings, checked} (prompts_g.AUDIT_SCHEMA)."""
    if not isinstance(out, Mapping):
        return [_v("audit_schema", "the audit output must be an object")]
    bad = [_v("audit_schema", f"missing {k}") for k in P.AUDIT_KEYS if k not in out]
    if bad:
        return bad
    if not _text_is(out["id"], qid):
        bad.append(_v("audit_schema", f"audit answered for id {out['id']!r}, not {qid}"))
    if out["value"] is not None and not _is_int(out["value"]):
        bad.append(_v("audit_schema", "value must be an integer or null"))
    if not (isinstance(out["reading"], str) and isinstance(out["checked"], str)):
        bad.append(_v("audit_schema", "reading and checked must be strings"))
    fs = out["findings"]
    if not (isinstance(fs, list) and all(
            isinstance(f, Mapping) and f.get("severity") in P.SEVERITIES
            and isinstance(f.get("issue"), str) and isinstance(f.get("suggested_fix"), str) for f in fs)):
        bad.append(_v("audit_schema",
                      "findings must be a list of {severity critical|major|minor, issue, suggested_fix}"))
    return bad


def severity_of(findings: Sequence[Mapping[str, Any]]) -> str:
    """The worst finding's severity, ok when there is none."""
    return max((f["severity"] for f in findings), key=SEVERITY_ORDER.index, default="ok")


def redact_numbers(text: str) -> str:
    """Every number of a forwarded finding as #: Arabic digits, a Chinese numeral run of two or more, a lone
    numeral before a unit or 多餘來; verse keys (gen.5.3, gen.11.10-gen.11.12) are kept."""
    keep = [m.span() for m in VERSE_REF.finditer(text)]
    return NUMBER_TOKEN.sub(lambda m: m.group() if any(a <= m.start() and m.end() <= b for a, b in keep)
                            else REDACTED, text)


def audit_issues(findings: Sequence[Mapping[str, Any]], redact: bool = False) -> tuple[P.Issue, ...]:
    """The findings as agent text; with `redact`, their numbers masked (redact_numbers)."""
    clean = redact_numbers if redact else (lambda t: t)
    out = []
    for f in findings:
        parts = [("agent", clean(f["issue"]))]
        if f.get("suggested_fix"):
            parts += [("tool", " Suggested fix: "), ("agent", clean(f["suggested_fix"]))]
        out.append(P.Issue.of(*parts))
    return tuple(out)


# ---------------------------------------------------------------- §3.6 three-way value comparison
CASES = ("agree", "writer_differs", "auditor_differs", "program_differs", "all_differ")
_HINTS = {"writer_differs": (P.GOLD_MISMATCH_HINT,), "auditor_differs": (P.AMBIGUITY_HINT,),
          "all_differ": (P.GOLD_MISMATCH_HINT, P.AMBIGUITY_HINT)}
# the cases whose forwarded findings lose their numbers: the auditor's value would hint at the gold (writer_differs)
# or point the writer at a second wrong value (all_differ); §3.6 gives the writer the neutral hint only
REDACT_CASES = ("writer_differs", "all_differ")


@dataclass(frozen=True)
class Decision:
    """What happens after an audit (prereg §3.5, §3.6).

    action: pass (all three values agree, no critical/major finding) | fix (one fix, counted as the audit round,
    then mech, re-audit and a new comparison) | dispute (row 3: CPU comparison of the cited verses with the reader,
    then the disputed part of Kay's page) | end_attempt. gold_trace: writer and auditor agree against the program
    gold, so the CPU verse comparison (the K-gold evidence) is recorded whatever the action.
    """
    action: str
    case: str
    issues: tuple[P.Issue, ...] = ()
    reaudit: bool = False
    uses_audit_round: bool = False
    gold_trace: bool = False
    severity: str = "ok"

    @property
    def closes_slot(self) -> bool:
        """Row 3's dispute: K-gold when the program gold is wrong, else the slot is deleted (never retried)."""
        return self.action == "dispute" and self.case == "program_differs"


def _same(a: Any, b: Any) -> bool:
    return _is_int(a) and _is_int(b) and a == b


def value_case(writer: Any, auditor: Any, gold: int) -> str:
    """Which §3.6 row the three values fall in; a missing or non-integer value equals nothing (not even itself)."""
    if not _is_int(gold):
        raise ValueError(f"program gold {gold!r} is not an integer")
    wg, ag = _same(writer, gold), _same(auditor, gold)
    if wg and ag:
        return "agree"
    if ag:
        return "writer_differs"
    if wg:
        return "auditor_differs"
    return "program_differs" if _same(writer, auditor) else "all_differ"


def compare_values(writer: Any, auditor: Any, gold: int, audit_round_spent: bool) -> Decision:
    """§3.6: writer value = auditor value = program gold freezes; row 3 is a dispute whatever the round state;
    the other rows take a fix, and once the attempt's audit round is spent they end the attempt."""
    case = value_case(writer, auditor, gold)
    if case == "agree":
        return Decision("pass", case)
    if case == "program_differs":
        return Decision("dispute", case, gold_trace=True)
    if audit_round_spent:
        return Decision("end_attempt", case)
    return Decision("fix", case, tuple(P.Issue.tool(h) for h in _HINTS[case]), True, True)


def after_audit(audit: Mapping[str, Any], writer_value: Any, gold: int, audit_round_spent: bool) -> Decision:
    """The audit's verdict, then the value comparison (prereg §3.1 order: blind audit -> three-way comparison).

    `audit` is an output that passed check_audit (a refused one is the runner's to drop or rerun).

    A critical or major finding takes the attempt's one audit round (its findings, numbers masked in
    REDACT_CASES, plus any value hint form the fix request) or, when the round is spent, ends the attempt; row-3
    values then still go to the dispute. ok and minor go on to compare_values.
    """
    sev = severity_of(audit["findings"])
    case = value_case(writer_value, audit.get("value"), gold)
    if sev in ("critical", "major"):
        if not audit_round_spent:
            hints = tuple(P.Issue.tool(h) for h in _HINTS.get(case, ()))
            issues = audit_issues(audit["findings"], redact=case in REDACT_CASES) + hints
            return Decision("fix", case, issues, True, True, case == "program_differs", sev)
        if case != "program_differs":
            return Decision("end_attempt", case, severity=sev)
    return replace(compare_values(writer_value, audit.get("value"), gold, audit_round_spent), severity=sev)
