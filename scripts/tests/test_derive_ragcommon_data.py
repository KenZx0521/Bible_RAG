import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

import derive_ragcommon_data as derive  # noqa: E402


def _rec(book, ch, verse, v_start, v_end=None, status="present", **extra):
    return {"id": f"{book}.{ch}.{verse}", "book": book, "chapter": ch, "verse": str(verse),
            "v_start": v_start, "v_end": v_end or v_start, "status": status, **extra}


def _write(tmp_path, records):
    path = tmp_path / "canonical.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def _full_records(extra=()):
    """One chapter of 2 verses for every book, plus extras."""
    from ragcommon import books

    recs = [_rec(b, 1, v, v) for b in books.book_ids() for v in (1, 2)]
    return recs + list(extra)


def test_versification_counts_merged_and_omitted_slots(tmp_path):
    extra = [
        _rec("eph", 2, "1-2", 1, 2),
        _rec("eph", 2, 3, 3, status="omitted_variant", variant_in_footnote_of="eph.2.1-2"),
    ]
    path = _write(tmp_path, _full_records(extra))
    doc = derive.derive_versification(path)
    assert doc["max_verse"]["eph"] == [2, 3]
    assert doc["max_verse"]["gen"] == [2]
    assert doc["omitted_slots"] == [{"slot_key": "eph.2.3", "variant_in_footnote_of": "eph.2.1-2"}]
    assert doc["source"]["sha256"] and doc["source"]["path"] == str(path)


@pytest.mark.parametrize(
    "extra, message",
    [
        ([_rec("eph", 2, 2, 2)], "gap"),
        ([_rec("eph", 1, 2, 2)], "overlap"),
        ([_rec("eph", 3, 1, 1)], "chapter"),
        ([_rec("xyz", 1, 1, 1)], "unknown book"),
        ([_rec("eph", 2, 1, 1, status="missing")], "unknown status"),
    ],
)
def test_versification_rejects_broken_canonical(tmp_path, extra, message):
    path = _write(tmp_path, _full_records(extra))
    with pytest.raises(derive.DeriveError, match=message):
        derive.derive_versification(path)


def test_versification_rejects_missing_book(tmp_path):
    records = [r for r in _full_records() if r["book"] != "rev"]
    with pytest.raises(derive.DeriveError, match="rev"):
        derive.derive_versification(_write(tmp_path, records))


def test_abbreviation_check_reports_missing_pdf_abbreviations(tmp_path):
    recs = [_rec("mrk", 1, 1, 1, annotations=[
        {"type": "parallel_ref", "text": "（太3‧1－12；路3‧1－9；約1‧19－28）"},
        {"type": "footnote", "text": "見以賽亞十八章一節"},
    ])]
    counts = derive.count_abbreviations(_write(tmp_path, recs))
    assert counts["太"] == 1 and counts["以賽亞"] == 1 and counts["約"] == 1
    missing = derive.missing_pdf_abbreviations(counts)
    assert "太" not in missing and "林前" in missing


def test_main_writes_versification_json(tmp_path):
    src = _write(tmp_path, _full_records())
    out = tmp_path / "v.json"
    assert derive.main(["versification", "--canonical", str(src), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "ragcommon.versification.v1"


def test_main_check_abbreviations_fails_when_missing(tmp_path, capsys):
    src = _write(tmp_path, _full_records())
    assert derive.main(["check-abbreviations", "--canonical", str(src)]) == 1
    assert "missing" in capsys.readouterr().err
