"""The chronology card's seed call: experiment A's seeds_a.py, verbatim but its imports.

gemma reads the question and the retrieved passages once and names the starting kings as
「國別｜王名」 lines (≤2); ``parse_seeds`` turns them into (kingdom, name) pairs that
``engine.resolve`` maps to layer nodes.
"""
from __future__ import annotations

import re
import unicodedata

# experiment A's cards_common.strip_parens (bracketed text, innermost first)
_PARENS = re.compile(r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")


def strip_parens(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, _PARENS.sub("", s)
    return s


SEED_SYSTEM = """你是資訊抽取工具，只負責找出問題裏的王。
規則：
1. 只找問題直接點名、或用事蹟描述的以色列王或猶大王，作為推算的起點；可以讀經文段落來辨認是哪一位王
2. 不要回答問題，不要推算問題要問的答案
3. 只輸出指定格式的行，不要輸出任何其他文字"""

SEED_USER = """以下是經文段落：

{context}

---

問題：{question}

請列出這個問題點名或描述的王（推算的起點，不是問題要問的答案），最多 2 位，每位一行，格式：
國別｜王名
國別只寫「猶大」或「以色列」；王名用經文中的寫法。"""

MAX_SEEDS = 2
_SEP = "｜|:："
_LABEL = re.compile(r"(?:國別|王名|名字|國家)\s*[:：]")
_ROW = re.compile(r"^\|(.*)\|$")
_LINE = re.compile(rf"^[\s\-*•·>#\d.、)）]*(?P<k>[^{_SEP}\n]{{1,12}}?)\s*[{_SEP}]\s*(?P<n>[^{_SEP}\n]{{1,20}}?)\s*[{_SEP}]?\s*$")
_NAME = re.compile(r"[一-鿿‧]{1,6}")


def seed_user(context: str, question: str) -> str:
    return SEED_USER.format(context=context, question=question)


def _kingdom(s: str) -> str | None:
    if "猶大" in s:
        return "J"
    if "以色列" in s:
        return "I"
    return None


def _name(s: str) -> str | None:
    s = strip_parens(unicodedata.normalize("NFKC", s))
    s = re.sub(r"[*_`#\s]", "", s)
    s = re.sub(r"^(?:猶大|以色列)(?:國)?王?", "", s)
    s = re.sub(r"王$", "", s)
    m = _NAME.fullmatch(s)
    return m.group(0) if m else None


def clean_line(raw: str) -> str:
    """NFKC; drop 國別：/王名： labels and the outer pipes of a Markdown table row."""
    s = _LABEL.sub("", unicodedata.normalize("NFKC", raw).strip())
    m = _ROW.match(s.strip())
    return m.group(1).strip() if m else s.strip()


def parse_seeds(text: str) -> list[tuple[str, str]]:
    """Up to two distinct (kingdom, name) from 「國別｜王名」 lines (｜ | ： : accepted, also
    「國別：猶大｜王名：希西家」 and table rows 「| 猶大 | 希西家 |」); a line without 猶大 or 以色列 in
    its first field, or without a 1–6 character name, is skipped."""
    out = []
    for raw in (text or "").splitlines():
        m = _LINE.match(clean_line(raw))
        if not m:
            continue
        kd, nm = _kingdom(m.group("k")), _name(m.group("n"))
        if kd and nm and (kd, nm) not in out:
            out.append((kd, nm))
        if len(out) == MAX_SEEDS:
            break
    return out
