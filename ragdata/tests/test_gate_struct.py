"""G-STRUCT (design §8): every condition of the row turns the gate red on its own."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.gates.struct import check_struct
from ragdata.stages.s05_struct.tokens import TokenCounter

BOTH = ("text", "struct")
MINI = TokenCounter(mini_build.count_tokens, {"tokenizer": "mini"})


def _gate(mutate=None, counter=MINI):
    files = mini_build.files(*BOTH)
    if mutate is not None:
        mutate(files)
    schema, snap = check_schema(files, BOTH)
    assert schema.passed, schema.details  # each case keeps every row within its contract
    return check_struct(snap, counter)


def _row(files, type_name, pk, key):
    return next(r for r in files[f"{type_name}.jsonl"] if r[pk] == key)


def _set(type_name, pk, key, **changes):
    return lambda f: _row(f, type_name, pk, key).update(changes)


def _legacy(legacy_id, **changes):
    return _set("legacy_ids", "legacy_id", legacy_id, **changes)


def _passage_content(passage_id, text):
    def mutate(f):
        _row(f, "passages", "passage_id", passage_id).update(
            content=text, content_sha=mini_build.sha(text))
    return mutate


def _heading(**changes):
    def mutate(f):
        f["headings.jsonl"].append({**_row(f, "headings", "heading_id", "hd:eph.6.1#1"), **changes})
    return mutate


def _drop_ref(f):
    p = _row(f, "passages", "passage_id", "ps:mat.18.1")
    p["unit_refs"] = p["unit_refs"][:2]
    p["end_key"] = p["end_slot"] = "mat.18.2"
    p["verse_range"] = "1-2"


def _overlap_ref(f):
    _row(f, "passages", "passage_id", "ps:act.9.3b")["unit_refs"] = [
        {"unit_key": "act.9.3", "from": mini_build.ACT_MID - 2, "to": None}]


def _swap_chunks(f):
    first, second = f["chunks.jsonl"]
    first["overlap_unit_keys"], second["overlap_unit_keys"] = ["act.9.1"], []


def test_the_mini_layer_is_green_and_counts_its_links():
    result = _gate()
    assert result.passed, result.details
    assert (result.name, result.hard) == ("G-STRUCT", True)
    assert result.observed["next"] == 1 and result.observed["next_book"] == 4
    assert result.observed["split_units"] == 1 and result.observed["untitled"] == 1


CASES = {
    "a unit left uncovered": (_drop_ref, "mat.18.4"),
    "a unit covered twice": (_overlap_ref, "act.9.3"),
    "content that is not the text": (_passage_content("ps:eph.6.1", "**1** 改過的經文"), "content"),
    "a superscription in the wrong passage": (
        _set("passages", "passage_id", "ps:psa.42.1", superscription_id=None), "superscription"),
    "a token count that is not the tokenizer's": (
        _set("passages", "passage_id", "ps:eph.6.1", token_count=99), "token_count"),
    "a pericope without its heading": (
        _set("pericopes", "pericope_id", "pc:mat.18.1", heading_id=None, title=None,
             untitled_reason="book_opening"), "pc:mat.18.1"),
    "a pericope titled off its heading": (
        _set("pericopes", "pericope_id", "pc:eph.6.1", title="別的標題"), "title"),
    "a stacked heading not recorded as the section": (
        _set("pericopes", "pericope_id", "pc:act.9.1", section_heading_id=None),
        "section_heading_id"),
    "a heading that opens no pericope": (
        _heading(heading_id="hd:eph.6.4#1", anchor_unit_key="eph.6.4"), "hd:eph.6.4#1"),
    "a mid heading in a merged unit": (
        _heading(heading_id="hd:eph.6.2b#1", anchor_unit_key="eph.6.2-3", anchor_offset=3,
                 pos="mid"), "merged"),
    "two mid headings in one unit": (
        _heading(heading_id="hd:act.9.3b#2", book_id="act", anchor_unit_key="act.9.3",
                 anchor_offset=3, pos="mid"), "2 mid-verse headings"),
    "a heading that starts with （": (_heading(heading_id="hd:eph.6.1#2", text_pdf="（弗6‧1）",
                                              text="（弗6‧1）", display_title="（弗6‧1）"), "（"),
    "a heading with unbalanced brackets": (
        _heading(heading_id="hd:eph.6.1#2", text_pdf="兒女「和父母", text="兒女「和父母",
                 display_title="兒女「和父母"), "brackets"),
    "a heading in a body typeface": (
        _heading(heading_id="hd:eph.6.1#2", prov={"style_class": "body", "glyph_range": [1, 2]}),
        "style"),
    "a next link across books": (
        _set("pericopes", "pericope_id", "pc:mat.18.1", next_id="pc:act.9.1", next_book_id=None),
        "next"),
    "a missing next book link": (
        _set("pericopes", "pericope_id", "pc:sng.1.1", next_book_id=None), "next_book_id"),
    "a unit filed under another pericope": (
        _set("verse_index", "unit_key", "act.10.1", pericope_id="pc:act.9.1"), "pericope_id"),
    "a split unit without its split list": (
        _set("verse_index", "unit_key", "act.9.3", split_passage_ids=[]), "split_passage_ids"),
    "a long passage left unchunked": (
        lambda f: f.update({"chunks.jsonl": []}), "ps:act.9.1"),
    "chunks that do not overlap by one piece": (_swap_chunks, "overlap"),
    "a chunk token count that is not the tokenizer's": (
        _set("chunks", "chunk_id", "ck:act.9.1~act.9.2", token_count=700), "token_count"),
    "an exact legacy row relabelled contained": (
        _legacy("psa:42:0", relation="contained"), "psa:42:0"),
    "a legacy row pointed at a passage of another chapter": (
        _legacy("psa:42:0", new_ids=["ps:eph.6.1"]), "psa:42:0"),
    "a legacy row pointed at another passage of its chapter": (
        _legacy("act:9:1", new_ids=["ps:act.9.1"]), "act:9:1"),
    "a contained legacy row whose passage does not hold it": (
        _legacy("act:9:0", new_ids=["ps:act.9.3b"]), "act:9:0"),
    "a contained legacy row although a passage matches exactly": (
        _legacy("act:9:1", relation="contained", new_ids=["ps:act.9.1"]), "act:9:1"),
    "a split legacy row missing an overlapping record": (
        _legacy("act:9:0:1", new_ids=["ck:act.9.1~act.9.2", "ps:act.9.3b"]), "act:9:0:1"),
    "a split legacy row that one record holds": (
        _legacy("act:9:0:0", relation="split",
                new_ids=["ck:act.9.1~act.9.2", "ck:act.9.2~act.9.3"]), "act:9:0:0"),
    "an old chunk mapped to a chunked passage": (
        _legacy("act:9:0:0", new_ids=["ps:act.9.1"]), "act:9:0:0"),
    "an old verse mapped to another unit": (
        _legacy("mat:18:0:v:4", new_ids=["vs:mat.18.2"]), "mat:18:0:v:4"),
    "a retired old verse whose slot the PDF holds": (
        _legacy("mat:18:0:v:4", relation="retired", new_ids=[]), "mat.18.4"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_condition_turns_the_gate_red(case):
    mutate, needle = CASES[case]
    result = _gate(mutate)
    assert not result.passed
    assert any(needle in d for d in result.details), result.details


def test_headings_found_word_for_word_in_the_text_are_reported_not_failed():
    result = _gate()
    assert result.passed
    assert result.observed["headings_in_verse_text"] == ["hd:mat.18.1#1"]  # 天國裏誰是最大的
