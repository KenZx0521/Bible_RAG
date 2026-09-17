"""
Context-block parity between the generator and the judge.

The judge must see exactly what the generator saw: the `[i] 書卷 第N章 - 標題 (節)`
header plus the passage text. These tests pin the header format and the
verse/pericope id-collision resolution (`3jn:1:2` is both 3 John 1:2 and the
2nd pericope of 3 John 1).
"""

from src.context_blocks import (
    contexts_from_raw_item,
    format_context_block,
    pericope_id_of,
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


# --- fetch-kind resolution (id collision fix) ---

def test_verse_direct_single_verse_beats_pericope_collision():
    assert resolve_fetch_kind("3jn:1:2", strategy="verse_direct", verse_range="2") == "verse"


def test_verse_range_from_source_metadata_without_strategy():
    # legacy raw_responses carry no strategy; verse_range == third segment is enough
    assert resolve_fetch_kind("3jn:1:2", strategy=None, verse_range="2") == "verse"


def test_pericope_when_verse_range_is_a_span():
    assert resolve_fetch_kind("3jn:1:2", strategy=None, verse_range="13-15") == "pericope"


def test_pericope_when_no_metadata_at_all():
    assert resolve_fetch_kind("rom:8:0", strategy=None, verse_range="") == "pericope"


def test_range_form_id():
    assert resolve_fetch_kind("psa:23:1-3", strategy="verse_direct", verse_range="1-3") == "range"


def test_chunk_id():
    assert resolve_fetch_kind("act:2:1:0", strategy="semantic", verse_range="") == "chunk"


def test_unknown_shape():
    assert resolve_fetch_kind("weird", strategy=None, verse_range="") == "unknown"
    assert resolve_fetch_kind("gen:1:x", strategy=None, verse_range="") == "unknown"


def test_backend_verse_id_resolves_to_parent_pericope():
    # backend postgres.get_content_by_id hydrates book:chapter:index:v:verse with the pericope
    assert resolve_fetch_kind("act:9:0:v:4", strategy="semantic", verse_range="") == "pericope"
    assert pericope_id_of("act:9:0:v:4") == "act:9:0"
    assert pericope_id_of("act:9:0") == "act:9:0"


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
