"""Dense and verse retrievers on fake stores: what a hit or a reference becomes."""

import asyncio

import pytest

from database import content
from ragcommon import ids
from utils import embedder
from utils.retrieval import dense, verse_retriever
from utils.verse_parser import VerseRef


def _payload(record_id, kind, passage_id, book="act"):
    return {"record_id": record_id, "kind": kind, "passage_id": passage_id, "book_id": book}


def _source(cid, kind="passage"):
    return {"id": cid, "kind": kind, "content": f"text of {cid}", "title": "t", "book_id": "act",
            "book_name": "使徒行傳", "chapter_num": 9, "verse_range": "1-3",
            "start_key": "act.9.1", "end_key": "act.9.3", "passage_id": "ps:act.9.1",
            "split_passage_ids": []}


@pytest.fixture
def stores(monkeypatch):
    asked = {}

    def search(vector, top_k=20, book_ids=None):
        asked.update(vector=vector, top_k=top_k, book_ids=book_ids)
        return [{"score": 0.9, "payload": _payload("vs:act.9.3", "verse", "ps:act.9.1")},
                {"score": 0.8, "payload": _payload("ps:act.9.1", "passage", "ps:act.9.1")},
                {"score": 0.7, "payload": _payload("ck:act.9.1~act.9.2", "chunk", "ps:act.9.1")}]

    async def fetch_sources(passage_ids, chunk_ids=()):
        asked.update(passages=list(passage_ids), chunks=list(chunk_ids))
        return {**{p: _source(p) for p in passage_ids},
                **{c: _source(c, "chunk") for c in chunk_ids}}

    monkeypatch.setattr(embedder, "encode_query", lambda q: [0.1, 0.2])
    monkeypatch.setattr(dense.qdrant_db, "search", search)
    monkeypatch.setattr(dense.postgres, "fetch_sources", fetch_sources)
    return asked


def test_a_verse_hit_stands_for_its_passage_and_a_chunk_for_itself(stores):
    found = asyncio.run(dense.retrieve_dense("q", dense.ROUTE_ARM))

    assert [(c["id"], c["kind"], c["weight"]) for c in found] == [
        ("ps:act.9.1", "passage", 0.70), ("ps:act.9.1", "passage", 0.65),
        ("ck:act.9.1~act.9.2", "chunk", 0.65)]
    assert {c["source_strategy"] for c in found} == {"hybrid_hybrid"}
    assert [c["semantic_score"] for c in found] == [0.9, 0.8, 0.7]
    assert found[0] is not found[1]  # each hit its own candidate
    assert stores["passages"] == ["ps:act.9.1", "ps:act.9.1"]
    assert stores["chunks"] == ["ck:act.9.1~act.9.2"]


def test_book_restriction_and_the_semantic_arm(stores):
    found = asyncio.run(dense.retrieve_dense("q", dense.SEMANTIC_ARM, top_k=4, book_ids=["act"]))

    assert stores["top_k"] == 4 and stores["book_ids"] == ["act"]
    assert [c["weight"] for c in found] == [0.65, 0.6, 0.6]
    assert {c["source_strategy"] for c in found} == {"semantic"}


# --- verse lookups ---------------------------------------------------------------------

UNITS = {
    "eph.6.1": content.VersePiece("eph.6.1", "1", 1, 1, "present", "作兒女的"),
    "eph.6.2": content.VersePiece("eph.6.2-3", "2-3", 2, 3, "merged", "要孝敬父母"),
    "eph.6.3": content.VersePiece("eph.6.2-3", "2-3", 2, 3, "merged", "要孝敬父母"),
    "mat.18.3": content.VersePiece(None, "3", 3, 3, "omitted_variant", content.OMITTED_TEXT,
                                   "fn:mat.18.2#1", "有古卷加：3人子來。"),
    "mat.18.4": content.VersePiece("mat.18.4", "4", 4, 4, "present", "凡自己謙卑的"),
}
OWNERS = {"eph.6.1": "ps:eph.6.1", "eph.6.2-3": "ps:eph.6.1", "mat.18.4": "ps:mat.18.4"}


@pytest.fixture
def pg(monkeypatch):
    p = verse_retriever.postgres

    async def verse_slots(slots):
        pieces = [UNITS[s] for s in slots]
        return [x for i, x in enumerate(pieces) if x.unit_key is None or i == 0
                or pieces[i - 1].unit_key != x.unit_key]

    async def owner_passages(units):
        return {u: {"passage_id": OWNERS[u], "split_passage_ids": []} for u in units}

    async def fetch_sources(passage_ids, chunk_ids=()):
        return {pid: {"title": f"title of {pid}"} for pid in passage_ids}

    async def book_name(book_id):
        return {"eph": "以弗所書", "mat": "馬太福音"}[book_id]

    async def chapter_passages(book_id, chapter):
        return [_source("ps:eph.6.1")]

    for name, fn in (("verse_slots", verse_slots), ("owner_passages", owner_passages),
                     ("fetch_sources", fetch_sources), ("book_name", book_name),
                     ("chapter_passages", chapter_passages)):
        monkeypatch.setattr(p, name, fn)


def _lookup(*refs):
    return asyncio.run(verse_retriever.retrieve_by_verse_refs(list(refs)))


def test_one_verse_of_a_merged_unit_returns_the_whole_unit(pg):
    [c] = _lookup(VerseRef("eph", "以弗所書", 6, 3, 3))

    assert c["id"] == "vs:eph.6.2-3" and c["kind"] == "verse"
    assert c["verse_range"] == "2-3" and (c["start_key"], c["end_key"]) == ("eph.6.2", "eph.6.3")
    assert c["content"] == "2-3. 要孝敬父母"
    assert c["passage_id"] == "ps:eph.6.1" and c["title"] == "title of ps:eph.6.1"
    assert c["source_strategy"] == "verse_direct" and c["weight"] == 1.0


def test_a_range_lists_each_unit_once(pg):
    [c] = _lookup(VerseRef("eph", "以弗所書", 6, 1, 3))

    assert c["id"] == "vr:eph.6.1~eph.6.3" and c["verse_range"] == "1-3"
    assert c["content"] == "1. 作兒女的\n2-3. 要孝敬父母"


def test_an_omitted_slot_says_so_with_its_footnote(pg):
    [only] = _lookup(VerseRef("mat", "馬太福音", 18, 3, 3))
    [both] = _lookup(VerseRef("mat", "馬太福音", 18, 3, 4))

    assert only["id"] == "vr:mat.18.3~mat.18.3" and only["passage_id"] is None
    assert only["title"] == ""
    assert only["content"] == "3. 本譯本此節從缺（有古卷加：3人子來。）"
    assert both["id"] == "vr:mat.18.3~mat.18.4" and both["passage_id"] == "ps:mat.18.4"


@pytest.mark.parametrize("ref, kind", [
    (VerseRef("eph", "以弗所書", 6, 3, 3), "verse_record"),
    (VerseRef("eph", "以弗所書", 6, 1, 3), "verse_range"),
    (VerseRef("mat", "馬太福音", 18, 3, 3), "verse_range"),
    (VerseRef("mat", "馬太福音", 18, 3, 4), "verse_range"),
])
def test_every_verse_result_id_parses_with_ragcommon(pg, ref, kind):
    [c] = _lookup(ref)

    parsed = ids.parse(c["id"])
    assert (parsed.kind, parsed.book_id, parsed.chapter) == (kind, ref.book_id, ref.chapter)


def test_a_chapter_reference_returns_its_passages_and_repeats_are_dropped(pg):
    found = _lookup(VerseRef("eph", "以弗所書", 6), VerseRef("eph", "以弗所書", 6, 3, 3),
                    VerseRef("eph", "以弗所書", 6, 2, 2))

    assert [c["id"] for c in found] == ["ps:eph.6.1", "vs:eph.6.2-3"]
    assert found[0]["source_strategy"] == "verse_direct"


def test_split_passages_are_listed_when_a_result_spans_several(pg, monkeypatch):
    async def owners(units):
        return {"eph.6.1": {"passage_id": "ps:eph.6.1", "split_passage_ids": []},
                "eph.6.2-3": {"passage_id": "ps:eph.6.1",
                              "split_passage_ids": ["ps:eph.6.1", "ps:eph.6.3b"]}}
    monkeypatch.setattr(verse_retriever.postgres, "owner_passages", owners)

    [c] = _lookup(VerseRef("eph", "以弗所書", 6, 1, 3))

    assert c["passage_id"] == "ps:eph.6.1" and c["split_passage_ids"] == ["ps:eph.6.1", "ps:eph.6.3b"]
