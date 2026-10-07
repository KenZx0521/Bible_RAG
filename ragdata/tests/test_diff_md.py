"""Diff of the text layer against bible_md: every difference gets a cause, ``other`` stays 0."""

from __future__ import annotations

from collections import Counter

import pytest

from ragdata.stages.diffs import md as dmd
from ragdata.stages.diffs.md import CharInfo

SELAH = "（細拉）"


def _unit(v, text, ord_, breaks=(), selah=None, ve=None, text_pdf=None):
    label = str(v) if ve is None else f"{v}-{ve}"
    markers = [] if selah is None else [{"type": "selah", "start": selah, "end": selah + 4}]
    return {"unit_key": f"rut.1.{label}", "book_id": "rut", "chapter": 1, "label": label,
            "v_start": v, "v_end": ve or v, "ord": ord_, "text": text,
            "text_pdf": text if text_pdf is None else text_pdf,
            "line_breaks": [{"offset": o, "kind": "soft"} for o in breaks], "markers": markers}


def _note(unit, n, kind, text, variant=None):
    return {"fn_id": f"fn:{unit}#{n}", "unit_key": unit, "n": n, "kind": kind, "text": text,
            "text_pdf": text, "variant_slot_key": variant}


def _rows():
    units = [
        _unit(1, "甲乙丙丁", 1, breaks=(2,)),
        _unit(2, "一二三四五六", 2),
        _unit(3, "天地" + SELAH, 3, selah=2),
        _unit(4, "風雨" + SELAH + "雷電", 4, selah=2),
        _unit(5, "山川河海", 5),
        _unit(6, "日月星辰", 6, breaks=(2,)),
        _unit(7, "東南西北", 7),
        _unit(8, "春秕秋冬", 8, text_pdf="春詷秋冬"),
        _unit(9, "金木", 9),
        _unit(11, "甲", 11),
        _unit(12, "乙", 12),
        _unit(13, "丙", 13),
        _unit(14, "丁", 14, ve=15),
    ]
    notes = [_note("rut.1.1", 1, "alt_rendering", "或譯：甲"),
             _note("rut.1.2", 1, "original", "原文是乙乙"),
             _note("rut.1.5", 1, "original", "註五"), _note("rut.1.6", 1, "original", "註六"),
             _note("rut.1.9", 1, "variant", "有古卷加：水火"),
             _note("rut.1.9", 2, "variant", "有古卷加：10土", variant="rut.1.10"),
             _note("rut.1.14-15", 1, "original", "原文是丙")]
    return {
        "books": [{"book_id": "rut", "file_name": "路得記"}], "verse_units": units,
        "footnotes": notes,
        "verse_slots": [{"slot_key": "rut.1.10", "status": "omitted_variant",
                         "variant_footnote_id": "fn:rut.1.9#2"}],
        "headings": [{"heading_id": "hd:rut.1.5b#1", "anchor_unit_key": "rut.1.5",
                      "anchor_offset": 2, "pos": "mid"}],
        "speakers": [{"sk_id": "sk:rut.1.12#1", "unit_key": "rut.1.12", "offset": 0,
                      "text": "〔新娘〕"}],
        "chapter_texts": [
            {"id": "dv:rut.1", "kind": "book_division", "chapter_key": "rut.1", "text": "卷一"},
            {"id": "sp:rut.1", "kind": "superscription", "chapter_key": "rut.1",
             "text": "大衛的詩"}],
        "errata_applied": [{"errata_id": "er:0001", "container_id": "rut.1.8", "offset": 1,
                            "pdf_char": "詷", "corrected_char": "秕"}],
    }


def _chars(rows):
    plain = CharInfo(1, False, 70.0)
    chars = {u["unit_key"]: [plain] * len(u["text_pdf"]) for u in rows["verse_units"]}
    chars.update({n["fn_id"]: [plain] * len(n["text_pdf"]) for n in rows["footnotes"]})
    chars["rut.1.2"][4:] = [CharInfo(2, False, 70.0)] * 2
    chars["rut.1.6"][2] = CharInfo(1, False, 90.0)
    chars["rut.1.7"][1:3] = [CharInfo(1, True, 430.0)] * 2
    chars["fn:rut.1.2#1"][4] = CharInfo(1, True, 430.0)
    return {k: tuple(v) for k, v in chars.items()}


MD = """# 路得記

## 第 1 章

**1** 甲乙
丙丁

**2** 一二三四

**3** 天地

**4** 風雨

**5** 山川

### 河海

**6** 日月

**7** 東北

**8** 春詷秋冬

**9** 金木水火

**10** 土

**11** 甲〔新娘〕

**12** 乙

**13** 戊

**14-15** 丁

---

**註腳：**
- 1:1: 或譯：甲
- 1:2:原文是乙
- 1:5:註五1:6:註六
"""


@pytest.fixture()
def diff(tmp_path):
    (tmp_path / "路得記.md").write_text(MD, encoding="utf-8")
    rows = _rows()
    return dmd.diff_md(rows, _chars(rows), tmp_path)


def _classes(result):
    return {(r.container, r.cls) for r in result.rows}


def test_every_difference_gets_its_cause(diff):
    assert _classes(diff) == {
        ("rut.1.1", "whitespace"), ("rut.1.2", "converter_footnote_pagebreak"),
        ("rut.1.3", "converter_selah"), ("rut.1.4", "converter_selah_midverse"),
        ("rut.1.5", "converter_midverse_heading"), ("rut.1.6", "converter_indented_line"),
        ("rut.1.7", "converter_offpage_clip"), ("rut.1.8", "errata"),
        ("rut.1.9", "hand_edit_variant_merged"), ("rut.1.10", "hand_edit_ghost_verse"),
        ("rut.1.11", "converter_speaker_label"), ("rut.1.13", "other"),
        ("fn:rut.1.1#1", "whitespace"), ("fn:rut.1.2#1", "converter_footnote_offpage_clip"),
        ("rut.1", "converter_footnotes_glued"), ("fn:rut.1.9#1", "hand_edit_footnote_removed"),
        ("fn:rut.1.9#2", "hand_edit_footnote_removed"),
        ("fn:rut.1.14-15#1", "converter_footnote_range_caller"),
        ("sp:rut.1", "converter_superscription_lost"), ("dv:rut.1", "converter_division_lost"),
    }


def test_rows_carry_the_layer_and_md_sides_of_each_difference(diff):
    row = next(r for r in diff.rows if r.container == "rut.1.2")
    assert (row.op, row.offset, row.layer, row.md) == ("delete", 4, "五六", "")
    clip = next(r for r in diff.rows if r.container == "rut.1.7")
    assert (clip.offset, clip.layer) == (1, "南西")
    errata = next(r for r in diff.rows if r.container == "rut.1.8")
    assert (errata.op, errata.layer, errata.md) == ("replace", "秕", "詷")
    notes = {r.container: (r.layer, r.md) for r in diff.rows if r.kind == "footnote"}
    assert notes["fn:rut.1.1#1"] == ("", " 或譯：甲")
    assert notes["fn:rut.1.2#1"] == ("乙", "")
    assert notes["fn:rut.1.14-15#1"] == ("原文是丙", "")


def test_the_summary_counts_units_and_characters_by_cause(diff):
    summary = diff.summary
    assert summary["units_compared"] == 13 and summary["md_only_verses"] == 1
    assert summary["by_class"]["converter_footnote_pagebreak"] == {"rows": 1, "containers": 1,
                                                                   "chars": 2}
    assert summary["by_class"]["other"]["rows"] == 1
    assert summary["loss"] == {"units": 5, "chars": 2 + 2 + 2 + 6 + 2}  # 細拉 counts
    assert summary["by_class"]["converter_superscription_lost"]["chars"] == 4


def test_a_md_file_missing_for_a_built_book_is_an_error(tmp_path):
    rows = _rows()
    with pytest.raises(dmd.DiffError, match="路得記.md"):
        dmd.diff_md(rows, _chars(rows), tmp_path)


def test_a_verse_the_md_lacks_is_other(tmp_path):
    (tmp_path / "路得記.md").write_text(MD.replace("**12** 乙\n", ""), encoding="utf-8")
    rows = _rows()
    result = dmd.diff_md(rows, _chars(rows), tmp_path)
    assert ("rut.1.12", "other") in _classes(result)


def test_a_variant_footnote_dropped_without_a_hand_edit_is_other(tmp_path):
    md = MD.replace("**9** 金木水火", "**9** 金木").replace("**10** 土\n", "")
    (tmp_path / "路得記.md").write_text(md, encoding="utf-8")
    rows = _rows()
    classes = Counter(r.cls for r in dmd.diff_md(rows, _chars(rows), tmp_path).rows)
    assert classes["hand_edit_footnote_removed"] == 0 and classes["other"] == 3


def test_the_tsv_escapes_tabs_and_newlines(diff):
    data = dmd.encode_tsv(diff.rows).decode("utf-8")
    lines = data.splitlines()
    assert lines[0].split("\t") == list(dmd.TSV_COLUMNS)
    assert all(len(line.split("\t")) == len(dmd.TSV_COLUMNS) for line in lines)
    assert "\\n" in data


def test_a_md_footnote_with_an_impossible_caller_is_other(tmp_path):
    (tmp_path / "路得記.md").write_text(MD + "- 0:3: 註\n", encoding="utf-8")
    rows = _rows()
    result = dmd.diff_md(rows, _chars(rows), tmp_path)
    assert ("rut.1", "other") in _classes(result)
