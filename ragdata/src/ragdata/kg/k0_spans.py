"""K0 extra spans: names the PDF does not underline (design §2.17).

- ``divine_rule``: divine names and titles in verse text (divine_refs.yaml);
- ``lexicon``: names in the regions without underlines (superscriptions, headings,
  footnotes), matched against the normalized underline names — never entity_dict;
- ``curated_underline``: underlines the PDF misses, one per decided registry entry.

Both rule sources match longest first, left to right, without overlap, and never
touch an underline span (or a curated one). A single 主 or 神 inside one of its
registry exclusion words (主人, 神蹟, …) is no span; a lexicon match is dropped
when it is shorter than ``min_len``, sits in a declared context (麻哈拉), or cites a
book chapter or opens a book title (撒母耳上十六章, 路加福音). Every skip is counted
for the report.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable, Mapping, Sequence

from ragcommon import ids
from ragdata.kg.registries import DivineRefs, LexiconRules, UnderlineFixes

Blocked = Mapping[str, Sequence[tuple[int, int]]]
Accept = Callable[[int, str], bool]


def overlaps(blocked: Blocked, container: str, start: int, end: int) -> bool:
    return any(start < b and a < end for a, b in blocked.get(container, ()))


def index_words(words: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Words by first character, longest first (ties by code point)."""
    index: dict[str, list[str]] = {}
    for word in sorted(set(words), key=lambda w: (-len(w), w)):
        index.setdefault(word[0], []).append(word)
    return {char: tuple(group) for char, group in index.items()}


def scan(text: str, index: Mapping[str, Sequence[str]], accept: Accept) -> list[tuple[int, str]]:
    """Longest accepted word at each position, left to right, without overlap."""
    found, i = [], 0
    while i < len(text):
        for word in index.get(text[i], ()):
            if text.startswith(word, i) and accept(i, word):
                found.append((i, word))
                i += len(word)
                break
        else:
            i += 1
    return found


def span_row(container: str, region: str, start: int, surface: str, source: str,
             rule_id: str | None, version: str, decided: tuple[str, str] | None = None
             ) -> dict[str, Any]:
    return {"span_id": ids.name_span_id(container, start), "container_id": container,
            "region": region, "start": start, "end": start + len(surface), "surface": surface,
            "source": source, "rule_id": rule_id, "registry_version": version,
            "decision_ref": decided[0] if decided else None,
            "decided_by": decided[1] if decided else None,
            "provenance_class": "curated_human" if decided else "pdf_rule"}


def excluded_word(text: str, i: int, surface: str,
                  exclusions: Mapping[str, Sequence[str]]) -> str | None:
    """The exclusion word around a single-character match at ``i``, if any."""
    for word in exclusions.get(surface, ()):
        for j, char in enumerate(word):
            if char == surface and i >= j and text[i - j:i - j + len(word)] == word:
                return word
    return None


def divine_spans(units: Sequence[Any], divine: DivineRefs,
                 blocked: Blocked) -> tuple[list[dict[str, Any]], Counter]:
    rule_of = {surface: rule_id for rule_id, surface in divine.patterns}
    index = index_words(rule_of)
    hits: Counter = Counter()
    rows = []
    for unit in units:
        key, text = unit.unit_key, unit.text_pdf

        def accept(i: int, word: str) -> bool:
            if overlaps(blocked, key, i, i + len(word)):
                return False
            excluded = excluded_word(text, i, word, divine.exclusions)
            if excluded is not None:
                hits[excluded] += 1
            return excluded is None
        rows += [span_row(key, "body", i, word, "divine_rule", rule_of[word], divine.version)
                 for i, word in scan(text, index, accept)]
    return rows, hits


def _in_context(text: str, i: int, word: str, contexts: Sequence[tuple[str, str]]) -> bool:
    for surface, context in contexts:
        if surface != word:
            continue
        for k in range(len(context) - len(word) + 1):
            if context[k:k + len(word)] == word and i >= k \
                    and text[i - k:i - k + len(context)] == context:
                return True
    return False


def _lexicon_accept(text: str, container: str, rules: LexiconRules, blocked: Blocked,
                    skipped: Counter) -> Accept:
    def accept(i: int, word: str) -> bool:
        reason = None
        if overlaps(blocked, container, i, i + len(word)):
            reason = "underline"
        elif len(word) < rules.min_len:
            reason = "min_len"
        elif rules.book_citation.match(text, i + len(word)) or any(
                len(title) > len(word) and text.startswith(title, i)
                for title in rules.book_titles):
            reason = "book_citation"
        elif _in_context(text, i, word, rules.exclude_contexts):
            reason = "exclude_context"
        if reason is not None:
            skipped[reason] += 1
        return reason is None
    return accept


def lexicon_spans(containers: Sequence[tuple[str, str, str]], words: Iterable[str],
                  rules: LexiconRules, version: str,
                  blocked: Blocked) -> tuple[list[dict[str, Any]], Counter]:
    """``containers`` are (container id, region, text) in output order."""
    index = index_words(words)
    skipped: Counter = Counter({k: 0 for k in ("underline", "min_len", "book_citation",
                                               "exclude_context")})
    rows = []
    for container, region, text in containers:
        accept = _lexicon_accept(text, container, rules, blocked, skipped)
        rows += [span_row(container, region, i, word, "lexicon", rules.rule_id, version)
                 for i, word in scan(text, index, accept)]
    return rows, skipped


def curated_spans(fixes: UnderlineFixes) -> list[dict[str, Any]]:
    return [span_row(fix.container_id, "body", fix.start, fix.surface, "curated_underline",
                     None, fixes.version, (f"underline_fixes.yaml#{fix.fix_id}", fix.decided_by))
            for fix in fixes.curated]
