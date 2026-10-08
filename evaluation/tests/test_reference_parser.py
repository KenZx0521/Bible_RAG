"""Reference parser tests — especially the cross-chapter verse-range formats
that used to fall back to whole-book (GENERAL_015 / GENERAL_018)."""

from src.reference_parser import parse_reference


def test_single_verse():
    refs = parse_reference("約翰福音 3:16")

    assert len(refs) == 1
    assert refs[0].book_id == "jhn"
    assert refs[0].chapters == [3]
    assert refs[0].verse_start == 16
    assert refs[0].verse_end == 16
    assert not refs[0].is_whole_book


def test_verse_range():
    refs = parse_reference("詩篇 23:1-3")

    assert len(refs) == 1
    assert refs[0].chapters == [23]
    assert (refs[0].verse_start, refs[0].verse_end) == (1, 3)


def test_chapter_range():
    refs = parse_reference("創世記 6-9章")

    assert len(refs) == 1
    assert refs[0].chapters == [6, 7, 8, 9]
    assert refs[0].verse_start is None


def test_chapter_range_pian_suffix():
    """詩篇 ranges written with 篇 must not fall back to whole-book."""
    refs = parse_reference("詩篇 120-134篇")

    assert len(refs) == 1
    assert not refs[0].is_whole_book
    assert refs[0].chapters == list(range(120, 135))


def test_cross_chapter_verse_range_adjacent():
    """約拿書 1:17-2:10 → tail of ch1 + head of ch2, not whole book."""
    refs = parse_reference("約拿書 1:17-2:10")

    assert len(refs) == 2
    assert all(not r.is_whole_book for r in refs)
    head, tail = refs
    assert head.chapters == [1]
    assert head.verse_start == 17
    assert head.to_chapter_end
    assert tail.chapters == [2]
    assert (tail.verse_start, tail.verse_end) == (1, 10)


def test_cross_chapter_verse_range_with_middle_chapters():
    refs = parse_reference("出埃及記 1:5-4:10")

    assert len(refs) == 3
    head, middle, tail = refs
    assert head.chapters == [1] and head.verse_start == 5 and head.to_chapter_end
    assert middle.chapters == [2, 3] and middle.verse_start is None
    assert tail.chapters == [4] and (tail.verse_start, tail.verse_end) == (1, 10)


def test_cross_chapter_same_chapter_guard():
    """"3:13-3:17" collapses to a plain in-chapter range."""
    refs = parse_reference("馬太福音 3:13-3:17")

    assert len(refs) == 1
    assert refs[0].chapters == [3]
    assert (refs[0].verse_start, refs[0].verse_end) == (13, 17)
    assert not refs[0].to_chapter_end


def test_whole_book():
    refs = parse_reference("以斯拉記; 尼希米記")

    assert len(refs) == 2
    assert all(r.is_whole_book for r in refs)
    assert {r.book_id for r in refs} == {"ezr", "neh"}


def test_semicolon_inherits_book():
    """GENERAL_018 style: bare "3:22-24" inherits 創世記 from the prior segment."""
    refs = parse_reference("創世記 2:8-17; 3:22-24; 啟示錄 21:1-22:5")

    gen_refs = [r for r in refs if r.book_id == "gen"]
    rev_refs = [r for r in refs if r.book_id == "rev"]
    assert len(gen_refs) == 2
    assert gen_refs[1].chapters == [3]
    assert (gen_refs[1].verse_start, gen_refs[1].verse_end) == (22, 24)
    # 21:1-22:5 must expand instead of whole-book fallback
    assert len(rev_refs) == 2
    assert all(not r.is_whole_book for r in rev_refs)
    assert rev_refs[0].chapters == [21] and rev_refs[0].to_chapter_end
    assert rev_refs[1].chapters == [22] and rev_refs[1].verse_end == 5


def test_bare_number_after_verse_is_verse_in_same_chapter():
    """GENERAL_043: "以賽亞書 11:1, 10" means 11:10, not the whole of chapter 10
    (the old parse put 34 of its 40 gold verses in the wrong chapter)."""
    refs = parse_reference("以賽亞書 11:1, 10; 羅馬書 15:8-12")

    isa = [r for r in refs if r.book_id == "isa"]
    assert [(r.chapters, r.verse_start, r.verse_end) for r in isa] == [
        ([11], 1, 1), ([11], 10, 10),
    ]


def test_bare_range_after_verse_is_verse_range_in_same_chapter():
    refs = parse_reference("以賽亞書 11:1-5, 10-12")

    assert [(r.chapters, r.verse_start, r.verse_end) for r in refs] == [
        ([11], 1, 5), ([11], 10, 12),
    ]


def test_bare_numbers_after_chapter_stay_chapters():
    """Without a preceding chapter:verse part, a bare number is still a chapter."""
    refs = parse_reference("出埃及記 2-4章, 18")

    assert [r.chapters for r in refs] == [[2, 3, 4], [18]]
    assert all(r.verse_start is None for r in refs)


def test_bare_number_after_cross_book_part_follows_that_book():
    refs = parse_reference("以賽亞書 11:1, 羅馬書 15:8, 10")

    assert [(r.book_id, r.chapters, r.verse_start) for r in refs] == [
        ("isa", [11], 1), ("rom", [15], 8), ("rom", [15], 10),
    ]


# --- ragcommon.refs (strict) ---------------------------------------------------

import pytest  # noqa: E402

from src.reference_parser import RefParseError  # noqa: E402


def test_nehemiah_resolves_by_pdf_name_and_old_variant():
    """尼希米記 is the PDF name; 尼西米記 (the old file name) stays a recorded variant."""
    for name in ("尼希米記", "尼西米記"):
        refs = parse_reference(f"{name} 8章")
        assert [(r.book_id, r.chapters) for r in refs] == [("neh", [8])]


@pytest.mark.parametrize("text, expected", [
    ("約翰福音３：１６", [("jhn", [3], 16, 16)]),
    ("約翰福音 第3章16節", [("jhn", [3], 16, 16)]),
    ("羅馬書 3:23；6:23", [("rom", [3], 23, 23), ("rom", [6], 23, 23)]),
    ("約 3:16a", [("jhn", [3], 16, 16)]),
])
def test_strict_forms_the_old_parser_did_not_read(text, expected):
    refs = parse_reference(text)

    assert [(r.book_id, r.chapters, r.verse_start, r.verse_end) for r in refs] == expected


@pytest.mark.parametrize("text", ["創世記 51章", "約翰福音 3:99", "不存在的書 1:1", "創世記 1:1 外加文字"])
def test_references_that_do_not_fully_parse_raise(text):
    with pytest.raises(RefParseError):
        parse_reference(text)


def test_blank_reference_has_no_units():
    assert parse_reference("  ") == []


def test_every_chapter_of_a_book_is_the_whole_book():
    refs = parse_reference("路得記 1-4章")

    assert len(refs) == 1 and refs[0].is_whole_book and refs[0].book_id == "rut"


def test_the_500_gt_references_all_parse():
    from src.data_loader import load_ground_truth

    unparsed = [q.question_id for q in load_ground_truth() if not parse_reference(q.reference)]

    assert unparsed == []
