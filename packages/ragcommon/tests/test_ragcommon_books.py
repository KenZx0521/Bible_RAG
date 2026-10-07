import json

import pytest

from ragcommon import books
from ragcommon.books import BookDataError, UnknownBookError


def _raw():
    return json.loads(books.DATA_PATH.read_text(encoding="utf-8"))


def _write(tmp_path, doc):
    path = tmp_path / "books.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_sixty_six_books_in_canonical_order():
    table = books.default_books()
    assert len(table.books) == 66
    assert [b.ord for b in table.books] == list(range(1, 67))
    assert table.ids()[:3] == ("gen", "exo", "lev")
    assert table.ids()[-1] == "rev"


@pytest.mark.parametrize(
    "book_id, name, testament",
    [
        ("gen", "創世記", "OT"),
        ("1sa", "撒母耳記上", "OT"),
        ("neh", "尼希米記", "OT"),
        ("psa", "詩篇", "OT"),
        ("mal", "瑪拉基書", "OT"),
        ("mat", "馬太福音", "NT"),
        ("jhn", "約翰福音", "NT"),
        ("1jn", "約翰一書", "NT"),
        ("jud", "猶大書", "NT"),
        ("rev", "啟示錄", "NT"),
    ],
)
def test_book_names_follow_pdf_title_line(book_id, name, testament):
    book = books.get_book(book_id)
    assert book.name == name
    assert book.testament == testament


def test_nehemiah_keeps_file_name_only_as_variant():
    neh = books.get_book("neh")
    assert neh.name == "尼希米記"
    assert neh.file_name == "尼西米記"
    entry = books.lookup_name("尼西米記")
    assert entry.book_id == "neh" and entry.kind == "name_variant"


@pytest.mark.parametrize(
    "text, book_id, kind",
    [
        ("創世記", "gen", "name"),
        ("撒上", "1sa", "pdf_abbreviation"),
        ("撒母耳上", "1sa", "pdf_abbreviation"),
        ("代下", "2ch", "pdf_abbreviation"),
        ("以賽亞", "isa", "pdf_abbreviation"),
        ("太", "mat", "pdf_abbreviation"),
        ("約", "jhn", "pdf_abbreviation"),
        ("林前", "1co", "pdf_abbreviation"),
        ("王上", "1ki", "pdf_abbreviation"),
        ("提前", "1ti", "colloquial_abbreviation"),
        ("約壹", "1jn", "colloquial_abbreviation"),
        ("啟", "rev", "colloquial_abbreviation"),
        ("列王記上", "1ki", "name_variant"),
    ],
)
def test_lookup_name_resolves_names_and_abbreviations(text, book_id, kind):
    entry = books.lookup_name(text)
    assert entry is not None
    assert (entry.book_id, entry.kind) == (book_id, kind)
    assert entry.is_abbreviation == kind.endswith("abbreviation")


@pytest.mark.parametrize("text", ["提摩太", "哥林多", "彼得", "撒母耳", "列王"])
def test_ambiguous_names_are_not_book_names(text):
    assert books.lookup_name(text) is None
    assert len(books.default_books().ambiguous[text]) == 2


@pytest.mark.parametrize("text", ["", "John", "創世記 ", "xyz", "約翰福"])
def test_lookup_name_returns_none_for_unknown(text):
    assert books.lookup_name(text) is None


def test_pdf_abbreviations_are_unique_and_cover_parallel_reference_forms():
    pdf = [a for b in books.all_books() for a in b.pdf_abbreviations]
    assert len(pdf) == len(set(pdf))
    assert {"太", "可", "路", "約", "代下", "林前", "撒上", "士"} <= set(pdf)


def test_names_longest_first_orders_by_length():
    names = books.default_books().names_longest_first()
    lengths = [len(n.text) for n in names]
    assert lengths == sorted(lengths, reverse=True)
    assert len({n.text for n in names}) == len(names)


def test_get_book_rejects_unknown_id():
    with pytest.raises(UnknownBookError):
        books.get_book("xyz")
    assert not books.is_book_id("xyz")
    assert books.is_book_id("1sa")


def test_book_abbreviations_property_joins_both_kinds():
    rut = books.get_book("rut")
    assert rut.pdf_abbreviations == ()
    assert rut.abbreviations == rut.colloquial_abbreviations


def _mutate(doc, index, **changes):
    new_books = list(doc["books"])
    new_books[index] = {**new_books[index], **changes}
    return {**doc, "books": new_books}


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda d: {**d, "books": d["books"][:-1]}, "66"),
        (lambda d: _mutate(d, 1, book_id="gen"), "duplicate"),
        (lambda d: _mutate(d, 0, book_id="GEN"), "book_id"),
        (lambda d: _mutate(d, 0, ord=5), "ord"),
        (lambda d: _mutate(d, 0, testament="NT"), "testament"),
        (lambda d: _mutate(d, 0, category="poetry"), "category"),
        (lambda d: _mutate(d, 1, pdf_abbreviations=["創"]), "duplicate name"),
        (lambda d: _mutate(d, 0, name="創 世記"), "name"),
        (lambda d: _mutate(d, 0, colloquial_abbreviations=["Gen"]), "name"),
        (lambda d: {**d, "ambiguous_names": {"創": ["gen", "exo"]}}, "ambiguous"),
        (lambda d: {**d, "ambiguous_names": {"某某": ["gen", "zzz"]}}, "ambiguous"),
        (lambda d: _mutate(d, 0, name_en=""), "name_en"),
    ],
)
def test_load_books_rejects_invalid_data(tmp_path, mutation, message):
    path = _write(tmp_path, mutation(_raw()))
    with pytest.raises(BookDataError, match=message):
        books.load_books(path)


def test_load_books_rejects_missing_field(tmp_path):
    doc = _raw()
    broken = dict(doc["books"][0])
    del broken["name_en"]
    path = _write(tmp_path, {**doc, "books": [broken] + doc["books"][1:]})
    with pytest.raises(BookDataError, match="name_en"):
        books.load_books(path)


def test_load_books_reads_custom_file(tmp_path):
    path = _write(tmp_path, _raw())
    assert books.load_books(path).ids() == books.default_books().ids()
