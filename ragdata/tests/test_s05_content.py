"""S5 content: `**n** 經文` blocks as the old pericopes.jsonl wrote them, plus the
superscription and speaker labels the old converter dropped (design §2.14)."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.stages.s05_struct import content
from ragdata.stages.s05_struct.view import Piece, text_view


def _view(text=None):
    rows = mini_build.text_layer() if text is None else text
    _, snap = check_schema({f"{k}.jsonl": v for k, v in rows.items()}, ("text",))
    return text_view(snap)


def _content(view, *pieces):
    return content.render(content.piece_blocks(view, [Piece(view.unit[k], a, b)
                                                      for k, a, b in pieces]))


def test_poetry_keeps_its_printed_lines_and_selah_but_not_its_wraps():
    view = _view()
    assert content.verse_body(view.unit["psa.42.1"], 0, None, ()) == "上帝啊，我的心切慕你，\n如鹿切慕溪水。"
    assert content.verse_body(view.unit["psa.42.2"], 0, None, ()) == "我的心渴想上帝，就是永生上帝。\n（細拉）"


def test_prose_is_one_line_whatever_breaks_the_page_had():
    rows = mini_build.text_layer()
    unit = next(u for u in rows["verse_units"] if u["unit_key"] == "eph.6.2-3")
    unit["line_breaks"] = [{"offset": 18, "kind": "hard"}]
    assert "\n" not in content.verse_body(_view(rows).unit["eph.6.2-3"], 0, None, ())


def test_a_piece_renders_only_its_slice_and_the_breaks_inside_it():
    unit = _view().unit["psa.42.1"]
    assert content.verse_body(unit, 4, None, ()) == "我的心切慕你，\n如鹿切慕溪水。"
    assert content.verse_body(unit, 0, 11, ()) == "上帝啊，我的心切慕你，"
    assert content.verse_body(unit, 11, None, ()) == "如鹿切慕溪水。"


def test_a_mid_verse_speaker_stands_on_its_own_line():
    rows = mini_build.text_layer()
    rows["speakers"].append({"sk_id": "sk:sng.1.1#2", "unit_key": "sng.1.1", "offset": 3,
                             "pos": "mid", "text_pdf": "〔新郎〕", "text": "〔新郎〕",
                             "provenance_class": "pdf_deterministic"})
    view = _view(rows)
    assert _content(view, ("sng.1.1", 0, None)) == "〔新娘〕\n\n**1** 願他用\n〔新郎〕\n口與我親嘴。"


def test_superscription_and_speaker_come_first_and_only_where_their_text_starts():
    view = _view()
    assert _content(view, ("psa.42.1", 0, None)).startswith("可拉後裔的訓誨詩，交給聖詠團長。\n\n**1** ")
    assert _content(view, ("psa.42.2", 0, None)).startswith("**2** ")
    assert _content(view, ("sng.1.1", 0, None)) == "〔新娘〕\n\n**1** 願他用口與我親嘴。"
    assert _content(view, ("sng.1.1", 2, None)) == "**1** 用口與我親嘴。"


def test_merged_units_and_half_verses_keep_integer_labels():
    view = _view()
    assert _content(view, ("eph.6.2-3", 0, None)).startswith("**2-3** 「要孝敬父母")
    second_half = _content(view, ("act.9.3", mini_build.ACT_MID, None))
    assert second_half == "**3** 忽然有光四面照着他。"


def test_blocks_group_by_piece_with_the_superscription_in_the_first_group():
    view = _view()
    groups = content.piece_blocks(view, [Piece(view.unit["psa.42.1"]), Piece(view.unit["psa.42.2"])])
    assert [[b.label for b in g] for g in groups] == [[None, "1"], ["2"]]


@pytest.mark.parametrize("title, expected", [
    ("渴慕上帝", "詩篇 第42章 渴慕上帝 (1-3節)：甲 乙"),
    (None, "詩篇 第42章 (1-3節)：甲 乙"),
])
def test_v1c_text_is_the_old_template_with_an_untitled_opening_left_out(title, expected):
    assert content.v1c_text("詩篇", 42, title, "1-3", ["甲", "乙"]) == expected
