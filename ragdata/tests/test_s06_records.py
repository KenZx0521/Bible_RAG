"""S6: the embedding records of the mini snapshot, against the hand-written v1c oracle."""

from __future__ import annotations

import pytest

import mini_build
from ragcommon import ids
from ragdata.contract import parse_record
from ragdata.gates import check_schema
from ragdata.stages.s06_emb import records, template
from ragdata.stages.s06_emb.records import TokenStats

STATS = TokenStats(lambda text: (mini_build.count_tokens(text), mini_build.count_unk(text)))


def _snapshot(text=None, struct=None):
    files = {**{f"{k}.jsonl": v for k, v in (text or mini_build.text_layer()).items()},
             **{f"{k}.jsonl": v for k, v in (struct or mini_build.struct_layer()).items()}}
    result, snap = check_schema(files, ("text", "struct"))
    assert result.passed, result.details
    return snap


def _records(**layers):
    return records.emb_records(_snapshot(**layers), template.V1C, STATS)


def _by_id(rows):
    return {r["record_id"]: r for r in rows}


def test_one_record_per_unit_unchunked_passage_and_chunk_in_file_order():
    rows = _records()
    assert tuple(r["record_id"] for r in rows) == mini_build.EMB_RECORD_IDS
    assert [r["kind"] for r in rows] == ["verse"] * 14 + ["passage"] * 6 + ["chunk"] * 2


def test_texts_are_the_v1c_template_with_the_fixed_values():
    assert {r["record_id"]: r["text"] for r in _records()} == {
        rid: mini_build.emb_text(rid) for rid in mini_build.EMB_RECORD_IDS}


def test_passage_and_chunk_tokens_are_what_s5_counted():
    rows = _by_id(_records())
    struct = mini_build.struct_layer()
    for row in struct["passages"] + struct["chunks"]:
        key = row.get("chunk_id") or row["passage_id"]
        if key in rows:
            assert rows[key]["token_count"] == row["token_count"]


def test_records_carry_ids_hashes_token_stats_and_parse():
    for row in _records():
        assert row["point_id"] == ids.point_id(row["record_id"])
        assert row["text_sha"] == mini_build.sha(row["text"])
        assert row["unk_count"] == mini_build.count_unk(row["text"])
        assert row["template_id"] == "v1c"
        parse_record("embedding_records", row)


@pytest.mark.parametrize("record_id", sorted(mini_build.EMB_PAYLOADS))
def test_payload_keeps_the_backend_fields_and_adds_the_new_ones(record_id):
    assert _by_id(_records())[record_id]["payload"] == mini_build.EMB_PAYLOADS[record_id]


def test_source_ids_name_the_unit_passage_or_chunk():
    rows = _by_id(_records())
    assert rows["vs:eph.6.2-3"]["source_id"] == "eph.6.2-3"
    assert rows["ps:act.10.1"]["source_id"] == "ps:act.10.1"
    assert rows["ck:act.9.1~act.9.2"]["source_id"] == "ck:act.9.1~act.9.2"


def test_an_untitled_book_opening_keeps_an_empty_payload_title():
    row = _by_id(_records())["ps:sng.1.1"]
    assert row["payload"]["title"] == "" and row["text"].startswith("雅歌 第1章 (1節)：")


def test_a_verse_preview_is_its_text_without_the_template_head():
    rows = _by_id(_records())
    assert rows["vs:psa.42.1"]["payload"]["content_preview"] == "上帝啊，我的心切慕你，\n如鹿切慕溪水。"


def test_the_template_renders_its_declared_format_strings():
    decl = template.V1C.declaration()
    assert decl["template_id"] == "v1c"
    assert decl["formats"]["passage"] == "{書名} 第{章}章 {標題} ({verse_range}節)：{content}"
    assert decl["formats"]["verse"] == "{書名} 第{章}章 {標題} 第{n}節：{經文}"
    assert template.V1C.render_verse("書", 2, None, "3", "經文") == "書 第2章 第3節：經文"
    assert template.V1C.render_passage("書", 2, "題", "1-3", ["甲", "乙"]) == "書 第2章 題 (1-3節)：甲 乙"


def test_a_verse_index_row_naming_a_missing_passage_stops_the_stage():
    struct = mini_build.struct_layer()
    struct["passages"] = [p for p in struct["passages"] if p["passage_id"] != "ps:act.10.1"]
    files = {**{f"{k}.jsonl": v for k, v in mini_build.text_layer().items()},
             **{f"{k}.jsonl": v for k, v in struct.items()}}
    _, snap = check_schema(files, ("text", "struct"))
    with pytest.raises(records.StageError, match="act.10.1"):
        records.emb_records(snap, template.V1C, STATS)
