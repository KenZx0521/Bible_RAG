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
    """"3:16-3:18" collapses to a plain in-chapter range."""
    refs = parse_reference("馬太福音 3:16-3:18")

    assert len(refs) == 1
    assert refs[0].chapters == [3]
    assert (refs[0].verse_start, refs[0].verse_end) == (16, 18)
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
