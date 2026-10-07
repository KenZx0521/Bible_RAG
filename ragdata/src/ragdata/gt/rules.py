"""Rule-based edits of one answer field; each returns ``Edit``s for ``changes.apply_edits``.

The evidence slot of an edit is where the new wording occurs in the service
text, preferring the question's gold slots. Orthography edits (着, 甚麼, 裏)
have none: they change a character, not a wording.
"""

from __future__ import annotations

import re
from typing import Sequence

from ragdata.gt.changes import Edit
from ragdata.gt.corpus import DOT, ServiceText
from ragdata.gt.forms import CUNP, FORMS, gloss_regex
from ragdata.gt.textnorm import norm


class RuleError(ValueError):
    """A rule whose replacement the service text does not use either."""


def evidence(corpus: ServiceText, wording: str, gold: Sequence[str]) -> str | None:
    clause = norm(wording)
    return corpus.locate(clause, within=gold) or corpus.locate(clause)


def errata_edits(value: str, corpus: ServiceText, gold: Sequence[str]) -> list[Edit]:
    """A word the PDF misprints (糠詷) becomes the errata layer's corrected word (糠秕)."""
    edits = []
    for pdf_word, word, containers in corpus.errata_words:
        slot = next((c for c in containers if c in gold), containers[0])
        edits += [Edit(m.start(), m.end(), word, slot)
                  for m in re.finditer(re.escape(pdf_word), value)]
    return edits


def gloss_edits(value: str) -> list[Edit]:
    """``大流士（大利烏）`` → ``大流士``: drop a CUNP spelling given as a gloss."""
    edits = []
    for form in FORMS:
        regex = gloss_regex(form)
        if regex is not None:
            edits += [Edit(m.start(), m.end(), form.corpus_form, None)
                      for m in regex.finditer(value)]
    return edits


def form_edits(value: str, corpus: ServiceText, rule: str, gold: Sequence[str]) -> list[Edit]:
    """Every form of ``rule`` in ``forms.FORMS`` becomes the corpus form."""
    edits = []
    for form in (f for f in FORMS if f.rule == rule):
        matches = list(form.regex.finditer(value))
        if not matches:
            continue
        if not corpus.count(form.corpus_form):
            raise RuleError(f"{form.pattern!r} → {form.corpus_form!r}: {corpus.version} "
                            f"never writes {form.corpus_form!r}")
        slot = evidence(corpus, form.corpus_form, gold) if rule == CUNP else None
        edits += [Edit(m.start(), m.end(), form.corpus_form, slot) for m in matches]
    return edits


def interpunct_edits(value: str, corpus: ServiceText, gold: Sequence[str]) -> list[Edit]:
    """Compound names written without ``‧`` get it back (西門彼得 → 西門‧彼得).

    ``corpus.dotted_names`` holds only names whose bare form the service text
    never writes; longest first, never overlapping a longer name already matched.
    """
    taken = [False] * len(value)
    edits = []
    for name in corpus.dotted_names:
        bare = name.replace(DOT, "")
        for m in re.finditer(re.escape(bare), value):
            if any(taken[m.start():m.end()]):
                continue
            taken[m.start():m.end()] = [True] * len(bare)
            edits.append(Edit(m.start(), m.end(), name, evidence(corpus, name, gold)))
    return edits
