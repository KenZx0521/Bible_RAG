"""
Context-block parity between the generator and the judge.

The judge must see exactly what the generator saw: the `[i] 書卷 第N章 - 標題 (節)`
header plus the passage text. These tests pin the header format and how a source's fetch is
resolved from its fields (`3jn:1:2` is both 3 John 1:2 and a pericope id).
"""

import pytest

from src.context_blocks import (
    contexts_from_raw_item,
    format_context_block,
    resolve_fetch_kind,
)
from src.models import SourceInfo


def _src(**kw) -> SourceInfo:
    base = dict(id="jhn:3:16", book="約翰福音", chapter=3, title="耶穌與尼哥德慕", verse_range="16")
    base.update(kw)
    return SourceInfo(**base)


# --- header format (must match backend/utils/generator.py:_build_context) ---

def test_header_full_matches_generator_format():
    block = format_context_block(1, _src(), "16. 上帝愛世人")
    assert block == "[1] 約翰福音 第3章 - 耶穌與尼哥德慕 (16節)\n16. 上帝愛世人"


def test_header_without_title_and_verse_range():
    block = format_context_block(3, _src(title="", verse_range=""), "內容")
    assert block == "[3] 約翰福音 第3章\n內容"


def test_header_with_verse_range_only():
    block = format_context_block(2, _src(title="", verse_range="1-3"), "內容")
    assert block == "[2] 約翰福音 第3章 (1-3節)\n內容"


def test_header_missing_chapter_renders_empty_like_generator():
    # generator uses src.get("chapter_num", "") -> "第章" when absent; parity over prettiness
    block = format_context_block(1, _src(chapter=None, title="", verse_range=""), "x")
    assert block == "[1] 約翰福音 第章\nx"


# --- fetch-kind resolution: from the payload, never by splitting the id ---

def _kind(source_id, verse_range="", **kw):
    return resolve_fetch_kind(_src(id=source_id, verse_range=verse_range, **kw))


def test_verse_id_beats_pericope_collision():
    # 3jn:1:2 is both 3 John 1:2 and a pericope id; the verse retriever's id matches its fields
    assert _kind("3jn:1:2", "2", book="約翰三書", chapter=1, strategy="verse_direct") == "verse"
    assert _kind("3jn:1:2", "2", book="約翰三書", chapter=1, strategy=None) == "verse"


def test_a_pericope_with_its_own_span_is_a_record():
    assert _kind("3jn:1:2", "13-15", book="約翰三書", chapter=1) == "record"
    assert _kind("rom:8:0", "", book="羅馬書", chapter=8) == "record"


def test_range_id():
    assert _kind("psa:23:1-3", "1-3", book="詩篇", chapter=23) == "range"


def test_old_nehemiah_name_still_spells_its_verse_id():
    assert _kind("neh:8:10", "10", book="尼西米記", chapter=8) == "verse"


@pytest.mark.parametrize("source_id", ["act:2:1:0", "act:9:0:v:4", "weird", "gen:1:x"])
def test_chunks_verse_records_and_unknown_ids_are_records(source_id):
    assert _kind(source_id, "", book="使徒行傳", chapter=2) == "record"


def test_a_source_without_book_or_chapter_is_a_record():
    assert _kind("jhn:3:16", "16", book="", chapter=3) == "record"
    assert _kind("jhn:3:16", "16", chapter=None) == "record"


@pytest.mark.parametrize("fields", [
    {"id": "ps:jhn.3.1"}, {"id": "ck:jhn.3.1~jhn.3.21"}, {"id": "vs:jhn.3.16"},
    {"id": "anything", "kind": "passage"},
])
def test_new_build_records_by_payload_kind_or_id_grammar(fields):
    assert resolve_fetch_kind(_src(**fields)) == "build"


# --- generator-format context blocks take precedence over legacy text ---

def test_contexts_from_raw_item_new_checkpoint_marks_context_source():
    item = {"context_source": "backend", "contexts": ["[1] b 第1章\nA"], "sources": [{"id": "a"}]}
    assert contexts_from_raw_item(item) == ["[1] b 第1章\nA"]
    item["context_source"] = "rebuilt"
    assert contexts_from_raw_item(item) == ["[1] b 第1章\nA"]


def test_contexts_from_raw_item_zero_source_sample_keeps_generator_tag():
    # a question with no retrieval results is still a new-format item, not a legacy one
    assert contexts_from_raw_item({"context_source": "backend", "contexts": [], "sources": []}) == []
    # legacy zero-source item stays None (caller tags it legacy)
    assert contexts_from_raw_item({"contexts": [], "sources": []}) is None


def test_contexts_from_raw_item_legacy_source_tag_is_not_trusted():
    item = {"context_source": "legacy_headerless", "contexts": ["x"], "sources": [{"id": "a"}]}
    assert contexts_from_raw_item(item) is None


def test_contexts_from_raw_item_uses_backend_blocks():
    item = {
        "contexts": ["headerless"],
        "sources": [
            {"id": "a", "book": "b", "chapter": 1, "title": "", "verse_range": "", "context": "[1] b 第1章\nA"},
            {"id": "c", "book": "d", "chapter": 2, "title": "", "verse_range": "", "context": "[2] d 第2章\nC"},
        ],
    }
    assert contexts_from_raw_item(item) == ["[1] b 第1章\nA", "[2] d 第2章\nC"]


def test_contexts_from_raw_item_falls_back_when_any_block_missing():
    item = {
        "contexts": ["headerless"],
        "sources": [
            {"id": "a", "book": "b", "chapter": 1, "title": "", "verse_range": "", "context": "[1] b 第1章\nA"},
            {"id": "c", "book": "d", "chapter": 2, "title": "", "verse_range": ""},
        ],
    }
    assert contexts_from_raw_item(item) is None


def test_contexts_from_raw_item_legacy_checkpoint():
    assert contexts_from_raw_item({"contexts": ["x"], "sources": []}) is None


def test_quick_tool_parse_ids_is_whitespace_tolerant():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from quick_faithfulness_eval import parse_ids
    assert parse_ids("A, B ,,C") == {"A", "B", "C"}
    assert parse_ids("") is None
    assert parse_ids(" , ") is None


def test_quick_tool_n_decomposed_ignores_strict_extras():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from quick_faithfulness_eval import n_decomposed
    assert n_decomposed([{"verdict": 1}, {"verdict": 0}, {"verdict": None, "strict_verdict": 0}]) == 2
    assert n_decomposed([{"verdict": None, "strict_verdict": 0}]) == 1
    assert n_decomposed([]) == 0
