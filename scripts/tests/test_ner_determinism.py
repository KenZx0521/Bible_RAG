"""NER output must not depend on PYTHONHASHSEED.

The dictionary pass tries names longest first, but get_all_*_names() return
sets, so equal-length names came out in hash order: two full NER runs with
different seeds produced the same mentions in a different order (different
mention_id numbering) and, where equal-length names overlap in the text
(以利亞 / 利亞撒 inside 以利亞撒), could even keep a different one.
Measured 2026-10-04: --stage ner --sample 400 with PYTHONHASHSEED=1 vs 2
gave byte-different ner_*.jsonl (269 of 1,863 mentions renumbered).
"""

import pytest

from entity_extraction.ner_extractor import NERExtractor

TEXT = "以利亞撒和以利亞在亞倫那裏，倫亞撒也在。"
NAMES = ["以利亞", "利亞撒", "亞倫", "以利亞撒", "倫亞撒"]


def _extractor(order: list[str]) -> NERExtractor:
    ex = NERExtractor.__new__(NERExtractor)  # skip CKIP model loading
    ex._all_entities = {name: "Person" for name in order}
    return ex


@pytest.mark.parametrize("order", [NAMES, list(reversed(NAMES)), sorted(NAMES)])
def test_dictionary_pass_ignores_insertion_order(order):
    baseline = _extractor(NAMES)._extract_by_dictionary(TEXT)

    assert _extractor(order)._extract_by_dictionary(TEXT) == baseline


def test_equal_length_overlap_keeps_a_fixed_winner():
    """利亞撒 and 倫亞撒 overlap 亞倫 / 以利亞 spans; whichever is tried first wins,
    so 'first' must be defined by the name, not by hash order."""
    a = _extractor(["利亞撒", "倫亞撒", "以利亞", "亞倫"])._extract_by_dictionary(TEXT)
    b = _extractor(["亞倫", "以利亞", "倫亞撒", "利亞撒"])._extract_by_dictionary(TEXT)

    assert [(r.text, r.start) for r in a] == [(r.text, r.start) for r in b]
