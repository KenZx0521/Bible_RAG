import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "packages", ROOT / "ragdata" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import derive_ragcommon_data as derive  # noqa: E402
from ragcommon import books  # noqa: E402
from ragdata import store  # noqa: E402


def _chapters(extra=()):
    """Two verses in one chapter of every book, plus extra (book, chapter, max_verse)."""
    rows = [{"chapter_key": f"{b}.1", "book_id": b, "chapter": 1, "max_verse": 2}
            for b in books.book_ids()]
    return rows + [{"chapter_key": f"{b}.{c}", "book_id": b, "chapter": c, "max_verse": m}
                   for b, c, m in extra]


OMITTED = {"slot_key": "eph.2.3", "unit_key": None, "status": "omitted_variant",
           "variant_footnote_id": "fn:eph.2.1-2#1"}
ALIAS = {"external_ref": "jhn.7.53", "relation": "contained_in", "target": "jhn.8.1",
         "note": "併入 8:1", "provenance_class": "external_reference"}


def _layer(tmp_path, chapters=None, slots=(OMITTED,), aliases=(ALIAS,)):
    files = {"chapters.jsonl": store.encode_jsonl(chapters or _chapters([("eph", 2, 3)])),
             "verse_slots.jsonl": store.encode_jsonl(slots),
             "ref_aliases.jsonl": store.encode_jsonl(aliases),
             "parallel_refs.jsonl": store.encode_jsonl(
                 [{"raw": "（太3‧1－12；路3‧1－9；約1‧19－28）"}]),
             "footnotes.jsonl": store.encode_jsonl([{"text_pdf": "見以賽亞十八章一節"}])}
    return store.write_layer(tmp_path / "store", "text", files).path


def test_versification_comes_from_the_text_layer(tmp_path):
    layer = _layer(tmp_path)
    doc = derive.derive_versification(layer)
    assert doc["max_verse"]["eph"] == [2, 3] and doc["max_verse"]["gen"] == [2]
    assert doc["omitted_slots"] == [{"slot_key": "eph.2.3", "variant_in_footnote_of": "eph.2.1-2"}]
    assert doc["source"]["kind"] == "text_layer"
    assert doc["source"]["layer_version"] == layer.name


@pytest.mark.parametrize("chapters, message", [
    (_chapters([("eph", 3, 4)]), "chapter numbers"),
    ([r for r in _chapters() if r["book_id"] != "rev"], "rev"),
    (_chapters([("xyz", 2, 1)]), "unknown book"),
], ids=["gap", "missing book", "unknown book"])
def test_versification_rejects_a_broken_grid(tmp_path, chapters, message):
    with pytest.raises(derive.DeriveError, match=message):
        derive.derive_versification(_layer(tmp_path, chapters=chapters))


def test_a_tampered_layer_is_refused(tmp_path):
    layer = _layer(tmp_path)
    (layer / "chapters.jsonl").write_bytes(b"")
    with pytest.raises(store.StoreError):
        derive.derive_versification(layer)


def test_aliases_are_copied_from_the_layer(tmp_path):
    rows = derive.derive_aliases(_layer(tmp_path))
    assert rows == [ALIAS]
    assert json.loads(derive.dump_aliases(rows).splitlines()[0]) == ALIAS


def test_abbreviation_check_reports_missing_pdf_abbreviations(tmp_path):
    counts = derive.count_abbreviations(_layer(tmp_path))
    assert counts["太"] == 1 and counts["以賽亞"] == 1 and counts["約"] == 1
    missing = derive.missing_pdf_abbreviations(counts)
    assert "太" not in missing and "林前" in missing


def test_main_writes_both_data_files(tmp_path):
    layer = _layer(tmp_path)
    out, aliases = tmp_path / "v.json", tmp_path / "a.jsonl"
    assert derive.main(["versification", "--text-layer", str(layer), "--out", str(out),
                        "--aliases-out", str(aliases)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "ragcommon.versification.v1"
    assert json.loads(aliases.read_text(encoding="utf-8"))["target"] == "jhn.8.1"


def test_main_check_abbreviations_fails_when_missing(tmp_path, capsys):
    assert derive.main(["check-abbreviations", "--text-layer", str(_layer(tmp_path))]) == 1
    assert "missing" in capsys.readouterr().err


def test_nothing_is_written_when_the_layer_lacks_its_aliases(tmp_path):
    files = {"chapters.jsonl": store.encode_jsonl(_chapters()),
             "verse_slots.jsonl": store.encode_jsonl([])}
    layer = store.write_layer(tmp_path / "store", "text", files).path
    out, aliases = tmp_path / "v.json", tmp_path / "a.jsonl"
    assert derive.main(["versification", "--text-layer", str(layer), "--out", str(out),
                        "--aliases-out", str(aliases)]) == 2
    assert not out.exists() and not aliases.exists()
