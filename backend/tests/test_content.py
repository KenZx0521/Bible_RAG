"""Pure assembly of what PG rows hold: chunk text, passage order, verse pieces."""

import pytest

from database import content

PASSAGE = ("可拉後裔的訓誨詩。\n\n**1** 上帝啊，\n如鹿切慕溪水。\n\n〔新娘〕\n\n"
           "**2-3** 我的心渴想上帝。\n\n**4** 我晝夜")
REFS = [{"unit_key": "psa.42.1", "from": 0, "to": None},
        {"unit_key": "psa.42.2-3", "from": 0, "to": None},
        {"unit_key": "psa.42.4", "from": 0, "to": 4}]


def test_a_chunk_is_its_pieces_blocks_cut_from_the_passage():
    first = content.chunk_content(PASSAGE, REFS, REFS[:2])
    second = content.chunk_content(PASSAGE, REFS, REFS[1:])

    assert first == "可拉後裔的訓誨詩。\n\n**1** 上帝啊，\n如鹿切慕溪水。\n\n〔新娘〕\n\n**2-3** 我的心渴想上帝。"
    assert second == "〔新娘〕\n\n**2-3** 我的心渴想上帝。\n\n**4** 我晝夜"


@pytest.mark.parametrize("passage, chunk_refs, message", [
    (PASSAGE, [{"unit_key": "psa.42.9", "from": 0, "to": None}], "not a run"),
    (PASSAGE, [REFS[0], REFS[2]], "not a run"),
    (PASSAGE, [{**REFS[2], "to": None}], "not a run"),
    (PASSAGE + "\n\n**5** 又", REFS[:1], "4 verse blocks for 3 pieces"),
    (PASSAGE + "\n\n〔新郎〕", REFS[:1], "after the last verse"),
])
def test_a_chunk_that_does_not_fit_its_passage_raises(passage, chunk_refs, message):
    with pytest.raises(content.ContentError, match=message):
        content.chunk_content(passage, REFS, chunk_refs)


def test_passages_order_by_start_key_whole_verse_before_its_second_half():
    keys = ["act.9.20", "act.9.19b", "act.9.1", "act.9.19"]

    assert sorted(keys, key=content.key_order) == ["act.9.1", "act.9.19", "act.9.19b", "act.9.20"]


def _slot(slot, unit=None, status="present", label=None, text="t", fn=None, fn_text=None):
    v = int(slot.rsplit(".", 1)[1])
    return {"slot_key": slot, "unit_key": unit, "status": status, "variant_footnote_id": fn,
            "label": label, "v_start": v if unit else None,
            "v_end": int(label.split("-")[-1]) if label else None, "text": text,
            "footnote_text": fn_text}


ROWS = [
    _slot("eph.6.1", "eph.6.1", label="1", text="作兒女的"),
    _slot("eph.6.2", "eph.6.2-3", "merged", label="2-3", text="要孝敬父母"),
    _slot("eph.6.3", "eph.6.2-3", "merged", label="2-3", text="要孝敬父母"),
    _slot("mat.18.3", None, "omitted_variant", fn="fn:mat.18.2#1", text=None,
          fn_text="有古卷加：3人子來。"),
]


def test_slots_of_one_unit_become_one_piece_and_an_omitted_slot_its_own():
    pieces = content.verse_pieces(["eph.6.1", "eph.6.2", "eph.6.3", "mat.18.3"], ROWS)

    assert [(p.unit_key, p.label, p.v_start, p.v_end, p.status) for p in pieces] == [
        ("eph.6.1", "1", 1, 1, "present"), ("eph.6.2-3", "2-3", 2, 3, "merged"),
        (None, "3", 3, 3, "omitted_variant")]
    assert pieces[2].text == content.OMITTED_TEXT
    assert pieces[2].footnote_text == "有古卷加：3人子來。"
    assert pieces[2].line == "3. 本譯本此節從缺（有古卷加：3人子來。）"
    assert pieces[1].line == "2-3. 要孝敬父母"


def test_a_slot_the_build_does_not_hold_raises():
    with pytest.raises(content.ContentError, match="eph.6.9"):
        content.verse_pieces(["eph.6.9"], ROWS)
