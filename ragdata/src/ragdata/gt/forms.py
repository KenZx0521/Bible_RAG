"""Written forms that the service text never uses, with the form it uses instead.

Answer fields of GT v2 must not contain any of them (G-GT); question text is
exempt (it stands for user input). ``cunp_spelling`` lists the CUNP (新標點和合本)
spellings of the audit (G04 table, g16 name pairs); ``corpus_orthography`` the
variant characters the corpus writes differently (着 for the particle 著, 甚麼,
裏, 鍊 for chains). Each pattern must match nothing in the service text and the
replacement must occur in it; G-GT checks both against the slot universe, so a
new layer that breaks an entry fails the gate instead of silently passing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CUNP = "cunp_spelling"
ORTHO = "corpus_orthography"


@dataclass(frozen=True)
class Form:
    pattern: str        # regex of the form the corpus does not use
    corpus_form: str    # what replaces each match
    rule: str
    literal: bool       # the pattern is a plain word (may appear as a gloss in parentheses)

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


def _cunp(word: str, corpus_form: str) -> Form:
    return Form(re.escape(word), corpus_form, CUNP, True)


FORMS: tuple[Form, ...] = (
    _cunp("古列", "塞魯士"), _cunp("該撒", "凱撒"), _cunp("大利烏", "大流士"),
    _cunp("流便", "呂便"), _cunp("推羅", "泰爾"), _cunp("撒瑪利亞", "撒馬利亞"),
    _cunp("約但", "約旦"), _cunp("西乃", "西奈"), _cunp("大馬色", "大馬士革"),
    _cunp("尼西米", "尼希米"), _cunp("以利沙伯", "伊利莎白"), _cunp("尼哥底母", "尼哥德慕"),
    _cunp("友尼基", "友妮基"), _cunp("革老丟", "克勞第"), _cunp("伯尼基", "百妮基"),
    _cunp("非尼基", "腓尼基"), _cunp("利未亞", "利比亞"), _cunp("毘", "毗"),
    _cunp("不至滅亡", "不致滅亡"),
    Form("什麼", "甚麼", ORTHO, True),
    Form("裡", "裏", ORTHO, True),
    # 著 as a particle; 著名、著書、著作、著述、著有 (authored) and 顯著 keep it
    Form("(?<![顯昭卓])著(?![名書作述有])", "着", ORTHO, False),
    Form("(?<=[金鐵鎖])鏈", "鍊", ORTHO, False),
)


def gloss_regex(form: Form) -> re.Pattern[str] | None:
    """``凱撒（該撒）``: the corpus form followed by the CUNP form in parentheses."""
    if not form.literal:
        return None
    return re.compile(f"{re.escape(form.corpus_form)}[（(]{form.pattern}[）)]")


def find_forms(text: str, forms: tuple[Form, ...] = FORMS) -> list[tuple[Form, re.Match[str]]]:
    return [(form, m) for form in forms for m in form.regex.finditer(text)]
