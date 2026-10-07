"""Clauses that become service text by CUV→RCUV spelling alone (audit g05).

A clause (≥4 Han characters) that is not in the service text is mechanical
when the deterministic transforms ``DET`` followed by the smallest subset of
per-occurrence transforms ``COMBO`` (神→上帝, 他→她, 不至→不致) make it a
substring of the gold verses' text, or else of the whole service text. The
transforms, their order and the subset search are the audit's (g05), so the
clause set is the one the audit counted. The new clause keeps the raw clause's
non-Han characters (dashes, digits) in place.
"""

from __future__ import annotations

import itertools
import re
from difflib import SequenceMatcher
from typing import Sequence

from ragdata.gt.changes import Edit
from ragdata.gt.corpus import ServiceText
from ragdata.gt.textnorm import HAN_RE, clause_spans, norm

MIN_CLAUSE = 4
MAX_COMBO = 8
DET: tuple[tuple[str, str, re.Pattern[str] | None], ...] = (
    ("著", "着", re.compile(r"著(?!名|書)(?<!顯著)")), ("裡", "裏", None), ("祂", "他", None),
    ("什麼", "甚麼", None), ("什", "甚", None), ("鏈", "鍊", None), ("古列", "塞魯士", None),
    ("該撒", "凱撒", None), ("流便", "呂便", None), ("尼西米", "尼希米", None),
    ("推羅", "泰爾", None), ("約但", "約旦", None), ("撒瑪利亞", "撒馬利亞", None),
    ("西乃", "西奈", None), ("大馬色", "大馬士革", None), ("唯", "惟", None),
)
COMBO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("上帝", re.compile(r"神(?!蹟|像|人)")), ("她", re.compile("他")),
    ("不致", re.compile(r"不至(?!於)")),
)


class MechanicalError(ValueError):
    """A fixed clause that cannot be written back into its raw clause."""


def _apply_det(clause: str) -> str:
    for old, new, regex in DET:
        clause = regex.sub(new, clause) if regex else clause.replace(old, new)
    return clause


def _subsets(clause: str):
    occ = sorted((m.start(), m.end(), new) for new, rx in COMBO for m in rx.finditer(clause))
    occ = occ[:MAX_COMBO]
    for k in range(len(occ) + 1):
        for subset in itertools.combinations(occ, k):
            out, shift = clause, 0
            for start, end, new in subset:
                out = out[:start + shift] + new + out[end + shift:]
                shift += len(new) - (end - start)
            yield out


def _fix(clause: str, local: str, corpus: ServiceText) -> tuple[str, bool] | None:
    """(fixed clause, found among the gold verses) or None."""
    for candidate in _subsets(_apply_det(clause)):
        if candidate in local:
            return candidate, True
        if corpus.contains(candidate, accept_pdf=False):
            return candidate, False
    return None


def project(raw: str, clause: str, fixed: str) -> str:
    """Rewrite ``raw`` (whose Han characters are ``clause``) so its Han characters read ``fixed``."""
    pos = [m.start() for m in HAN_RE.finditer(raw)]
    if "".join(raw[p] for p in pos) != clause:
        raise MechanicalError(f"{clause!r} is not the Han text of {raw!r}")
    out = raw
    ops = SequenceMatcher(None, clause, fixed, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in reversed(ops):
        if tag == "equal":
            continue
        start = pos[i1] if i1 < len(pos) else len(raw)
        end = pos[i2 - 1] + 1 if i2 > i1 else start
        if raw[start:end] != clause[i1:i2]:
            raise MechanicalError(f"{raw!r}: {clause[i1:i2]!r} is split by non-Han characters")
        out = out[:start] + fixed[j1:j2] + out[end:]
    if norm(out) != fixed:
        raise MechanicalError(f"{raw!r} → {out!r} does not read {fixed!r}")
    return out


def mechanical_edits(value: str, corpus: ServiceText, gold: Sequence[str],
                     local: str | None = None) -> list[Edit]:
    """Edits for the mechanical clauses of ``value``; ``local`` is ``corpus.local(gold)``."""
    local = corpus.local(gold) if local is None else local
    edits = []
    for span in clause_spans(value):
        clause = norm(span.text)
        if len(clause) < MIN_CLAUSE or clause in local or corpus.contains(clause):
            continue
        hit = _fix(clause, local, corpus)
        if hit is None:
            continue
        fixed, is_local = hit
        slot = corpus.locate(fixed, within=gold) if is_local else corpus.locate(fixed)
        edits.append(Edit(span.start, span.end, project(span.text, clause, fixed), slot))
    return edits
