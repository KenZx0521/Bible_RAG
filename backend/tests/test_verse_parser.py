"""verse_parser reads references with ragcommon.refs and names books from ragcommon.books.

Every reference is checked against the PDF verse grid: one naming no verse is
reported (rejected), never routed; a cross-chapter range becomes one reference per
chapter, so verse_range stays chapter-internal.
"""

from utils.verse_parser import VerseRef, find_verse_references, parse_verse_references


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


def test_chapter_range_is_one_reference_per_chapter():
    assert parse_verse_references("馬太福音5-7章") == [
        VerseRef("mat", "馬太福音", ch) for ch in (5, 6, 7)]


def test_a_reference_to_no_verse_is_rejected_not_routed():
    found = find_verse_references("約翰福音3:99說什麼？")

    assert found.refs == ()
    assert [r.raw for r in found.rejected] == ["約翰福音3:99"]


def test_quantities_are_not_references():
    assert parse_verse_references("耶穌在曠野40天，約3天後") == []
