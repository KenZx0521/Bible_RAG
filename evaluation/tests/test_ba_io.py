"""book_anchor ablation JSON lines and context hash (experiments/2026-10-15_book_anchor/_ba_io.py).

prereg §6 I7, §9 (續跑前截到最後一個換行), §10 test_ba_io: a cut last line is truncated; a line
without "kind" or not JSON raises; resume keys; ctx_sha equals the hash of the blocks
format_context_block builds and of backend/utils/generator.py's own build_context_blocks;
a JSON round trip keeps the hash and a renamed field changes it.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXP = _REPO / "evaluation" / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_io as bio  # noqa: E402
import _ba_export as bex  # noqa: E402
from src.context_blocks import format_context_block  # noqa: E402
from src.models import SourceInfo  # noqa: E402


def backend_build_context_blocks():
    """backend/utils/generator.py's build_context_blocks, compiled from the repo source alone."""
    tree = ast.parse((_REPO / "backend" / "utils" / "generator.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "build_context_blocks")
    namespace: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "generator.py", "exec"), namespace)
    return namespace["build_context_blocks"]


BUILD = backend_build_context_blocks()


def results():
    return [
        {"id": "ps:isa.40.1", "kind": "passage", "book_name": "以賽亞書", "chapter_num": 40,
         "title": "安慰的話", "verse_range": "1-11", "content": "**1** 你們的上帝說：\n\n**3** 有聲音呼喊",
         "book_id": "isa", "weight": 0.9, "rerank_score": 0.5243, "fused_score": 0.637,
         "semantic_score": 0.71, "found_by": ["book_anchor"], "unit_refs": [{"unit_key": "isa.40.1"}],
         "split_passage_ids": []},
        {"id": "ck:mrk.1.1~mrk.1.8", "kind": "chunk", "book_name": "馬可福音", "chapter_num": 1,
         "title": "", "verse_range": "1-8", "content": "**1** 上帝的兒子", "book_id": "mrk",
         "weight": 0.65, "rerank_score": 0.967, "fused_score": None},
        {"id": "ps:exo.40.34", "kind": "passage", "book_name": "出埃及記", "chapter_num": 40,
         "title": "榮光充滿帳幕", "verse_range": "", "content": "雲彩遮蓋會幕",
         "source_strategy": "event_registry", "via_event_id": "ev.1"},
    ]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- JSON lines

def test_truncate_drops_a_cut_last_line_and_keeps_complete_ones(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_bytes(b'{"kind": "meta"}\n{"kind": "q", "qid": "A"}\n{"kind": "q", "qi')
    assert bio.truncate_to_last_newline(path) == len(b'{"kind": "q", "qi')
    assert path.read_bytes() == b'{"kind": "meta"}\n{"kind": "q", "qid": "A"}\n'
    assert bio.truncate_to_last_newline(path) == 0
    assert [r["kind"] for r in bio.read_jsonl(path)] == ["meta", "q"]


def test_truncate_without_any_newline_empties_the_file_and_a_missing_file_is_fine(tmp_path):
    path = tmp_path / "r.jsonl"
    assert bio.truncate_to_last_newline(path) == 0
    path.write_bytes(b'{"kind": "me')
    assert bio.truncate_to_last_newline(path) == 12
    assert path.read_bytes() == b""
    assert bio.read_jsonl(path) == []


@pytest.mark.parametrize("body", [
    b'{"qid": "A"}\n',                 # no kind
    b'{"kind": 3}\n',                  # kind not a string
    b'["kind"]\n',                     # not an object
    b'{"kind": "q"\n',                 # not JSON
    b'{"kind": "q"}\n\n',              # empty line
    b'{"kind": "q"}\n{"kind": "q"}',   # unterminated last line (truncate first)
], ids=["no_kind", "kind_not_str", "not_object", "not_json", "empty_line", "cut_tail"])
def test_a_bad_line_raises(tmp_path, body):
    path = tmp_path / "r.jsonl"
    path.write_bytes(body)
    with pytest.raises(bio.BaIoError):
        bio.read_jsonl(path)


def test_missing_file_reads_empty_only_when_allowed(tmp_path):
    assert bio.read_jsonl(tmp_path / "none.jsonl", missing_ok=True) == []
    with pytest.raises(bio.BaIoError):
        bio.read_jsonl(tmp_path / "none.jsonl")


def test_dumps_line_needs_a_kind_and_writes_one_line():
    line = bio.dumps_line({"kind": "q", "text": "第一行\n第二行"})
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line)["text"] == "第一行\n第二行"
    with pytest.raises(bio.BaIoError):
        bio.dumps_line({"qid": "A"})
    with pytest.raises(ValueError):
        bio.dumps_line({"kind": "q", "x": float("nan")})


def test_resume_keys():
    rows = [{"kind": "meta"}, {"kind": "q", "qid": "A"}, {"kind": "q", "qid": "B"},
            {"kind": "gen", "qid": "A", "arm": "ctrl", "rep": 1, "ok": True},
            {"kind": "gen", "qid": "A", "arm": "off", "rep": 1, "ok": False},
            {"kind": "gen", "qid": "B", "arm": "off", "rep": 2, "ok": False},
            {"kind": "gen", "qid": "B", "arm": "off", "rep": 2, "ok": True}]
    assert bio.done_questions(rows) == {"A", "B"}
    assert bio.done_gens(rows) == {("A", "ctrl", 1), ("A", "off", 1), ("B", "off", 2)}
    # --retry-failed: a key whose latest row failed is not done; a later success supersedes
    assert bio.done_gens(rows, retry_failed=True) == {("A", "ctrl", 1), ("B", "off", 2)}
    assert bio.latest_gens(rows)[("B", "off", 2)]["ok"] is True


# ---------------------------------------------------------------- ctx_sha

def test_ctx_sha_is_the_hash_of_the_generator_context():
    res = results()
    text = "\n\n".join(BUILD(res))
    assert bio.ctx_sha(res, BUILD) == sha(text)
    assert bio.context_text(res, BUILD) == text


def test_ctx_sha_equals_the_blocks_format_context_block_builds():
    res = results()
    blocks = [format_context_block(i, SourceInfo(id=r["id"], book=r["book_name"],
                                                 chapter=r["chapter_num"], title=r["title"],
                                                 verse_range=r["verse_range"]), r["content"])
              for i, r in enumerate(res, 1)]
    assert bio.ctx_sha(res, BUILD) == sha("\n\n".join(blocks))
    assert bio.ctx_sha(res, bex.host_blocks) == bio.ctx_sha(res, BUILD)


def test_a_json_round_trip_keeps_the_hash():
    res = results()
    res[0]["unit_refs"] = ({"unit_key": "isa.40.1"},)          # a tuple becomes a list
    back = json.loads(json.dumps(bio.to_jsonable(res), ensure_ascii=False))
    assert bio.ctx_sha(back, BUILD) == bio.ctx_sha(res, BUILD)
    assert bio.ctx_sha(back, bex.host_blocks) == bio.ctx_sha(res, BUILD)


def test_numpy_scalars_serialise_as_numbers():
    np = pytest.importorskip("numpy")
    out = bio.to_jsonable({"a": np.float32(0.5), "b": np.int64(3), "c": {"x", "y"}})
    assert out == {"a": 0.5, "b": 3, "c": ["x", "y"]}


def test_a_renamed_field_changes_the_hash():
    res = results()
    renamed = [{("book" if k == "book_name" else k): v for k, v in r.items()} for r in res]
    assert bio.ctx_sha(renamed, BUILD) != bio.ctx_sha(res, BUILD)
    with pytest.raises(bex.ExportError):
        bex.verified_contexts(renamed, bio.ctx_sha(res, BUILD))


def test_messages_sha_is_order_and_content_sensitive():
    a = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert bio.messages_sha(a) == bio.messages_sha(json.loads(json.dumps(a)))
    assert bio.messages_sha(a) != bio.messages_sha(a[::-1])
    assert bio.messages_sha(a) != bio.messages_sha([a[0], {"role": "user", "content": "u2"}])
