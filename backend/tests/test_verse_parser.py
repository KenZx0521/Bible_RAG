"""verse_parser reads references with ragcommon.refs and names books from ragcommon.books.

Every reference is checked against the PDF verse grid: one naming no verse is
reported (rejected), never routed. A cross-chapter verse range becomes one
reference per chapter, so verse_range stays chapter-internal; a chapter range
stays one reference (its first chapter is what retrieval and the chapter pin use).
"""

import json
from pathlib import Path

import pytest

from utils.verse_parser import VerseRef, find_verse_references, parse_verse_references

LEGACY = Path(__file__).resolve().parent / "fixtures" / "verse_refs_legacy_gt.json"
# GT questions the legacy parser missed: its book table spelled 尼希米記 as 尼西米記
# (design §11.1 R1: the PDF name, the old spelling only as an input alias).
LEGACY_MISSED = {
    "根據尼希米記8:10，尼希米如何勸勉那些聽見律法書就哭的百姓？": [("neh", 8, 10, 10)],
    "根據尼希米記第4章，尼希米如何應對仇敵對修牆工程的攻擊與譏誚？": [("neh", 4, None, None)],
}


def test_single_verse_uses_the_pdf_book_name():
    [ref] = parse_verse_references("約翰福音3:16說了什麼？")

    assert ref == VerseRef("jhn", "約翰福音", 3, 16, 16)
    assert ref.display == "約翰福音3:16"
    assert ref.is_range is False


def test_nehemiah_old_spelling_is_still_read_but_answered_with_the_pdf_name():
    [old] = parse_verse_references("尼西米記8:10")
    [new] = parse_verse_references("尼希米記8:10")

    assert old == new == VerseRef("neh", "尼希米記", 8, 10, 10)


def test_range_and_chapter_only_references():
    refs = parse_verse_references("羅馬書3:23-24 與創世記第1章")

    assert refs == [VerseRef("rom", "羅馬書", 3, 23, 24), VerseRef("gen", "創世記", 1)]
    assert refs[0].is_range and refs[0].display == "羅馬書3:23-24"
    assert refs[1].display == "創世記1"


def test_cross_chapter_range_is_split_per_chapter():
    refs = parse_verse_references("創世記1:30-2:3")

    assert refs == [VerseRef("gen", "創世記", 1, 30, 31), VerseRef("gen", "創世記", 2, 1, 3)]


@pytest.mark.parametrize("text, ref, display", [
    ("利未記1-7章記載了哪五種祭？", VerseRef("lev", "利未記", 1, chapter_end=7), "利未記1-7"),
    ("詩篇120至134篇的上行之詩", VerseRef("psa", "詩篇", 120, chapter_end=134), "詩篇120-134"),
    ("詩篇1-150篇", VerseRef("psa", "詩篇", 1, chapter_end=150), "詩篇1-150"),
])
def test_a_chapter_range_stays_one_reference(text, ref, display):
    assert parse_verse_references(text) == [ref]
    assert ref.display == display


def _retrieval_view(ref) -> tuple:
    """What routing, retrieval and the chapter pin read: verses, or the (first) chapter."""
    if ref.verse_start is None:
        return (ref.book_id, ref.chapter, None, None)
    return (ref.book_id, ref.chapter, ref.verse_start, ref.verse_end or ref.verse_start)


def test_gt_questions_route_on_the_references_the_legacy_parser_read():
    """R1 parity (design §0.2): on all 500 GT questions retrieval reads what legacy read.

    The legacy parser took 「利未記1-7章」 as chapter 1 (verse_end 7, no verse), so
    a chapter range is served by its first chapter. Only LEGACY_MISSED differs.
    """
    rows = json.loads(LEGACY.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 500

    for row in rows:
        legacy = [_retrieval_view(VerseRef(r[0], "", *r[1:])) for r in row["refs"]]
        new = [_retrieval_view(r) for r in parse_verse_references(row["text"])]
        if row["text"] in LEGACY_MISSED:
            assert (legacy, new) == ([], LEGACY_MISSED[row["text"]])
        else:
            assert new == legacy, row["text"]


def test_a_reference_to_no_verse_is_rejected_not_routed():
    found = find_verse_references("約翰福音3:99說什麼？")

    assert found.refs == ()
    assert [r.raw for r in found.rejected] == ["約翰福音3:99"]


def test_quantities_are_not_references():
    assert parse_verse_references("耶穌在曠野40天，約3天後") == []
