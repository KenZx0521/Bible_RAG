"""import_neo4j refuses duplicate CROSS_REFERENCES pairs before it connects.

Relationships are written with `MERGE (a)-[r:CROSS_REFERENCES]->(b) SET r +=
$props`, so a second row for the same (start, end) does not add an edge: it
overwrites the first row's properties and the import still looks green
(XREF-1(b): three supplementary anchors vanished this way). Step 0 now writes
one aggregated row per pair; the guard makes any regression stop the rebuild
before the graph is cleared.

main() catches every Exception around get_neo4j_driver() and turns it into
exit 1, so the stub signals "connected" with a BaseException that cannot be
mistaken for the guard's own exit.
"""

import json
import sys

import pytest

import import_neo4j


class _Connected(BaseException):
    """Raised by the get_neo4j_driver stub: main() got past the guard."""


def _connect():
    raise _Connected


def _xref(start: str, end: str, source: str = "supplementary") -> dict:
    return {"start": start, "end": end, "type": "CROSS_REFERENCES",
            "properties": {"source": source}}


def _run_main(monkeypatch, output_dir):
    monkeypatch.delenv("KG_TARGET", raising=False)
    monkeypatch.setattr(import_neo4j, "get_neo4j_driver", _connect)
    monkeypatch.setattr(sys, "argv", ["import_neo4j.py", "--output-dir", str(output_dir)])
    import_neo4j.main()


def _write_rels(output_dir, rows):
    with open(output_dir / "neo4j_relationships.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def test_duplicate_pair_exits_before_connecting(monkeypatch, tmp_path, capsys):
    # A pair is one edge whatever the rows' sources: markdown + supplementary
    # (what 1B-C4a aggregates) and markdown + markdown are both duplicates.
    _write_rels(tmp_path, [
        _xref("mat:4:0", "deu:6:1", "markdown"), _xref("1pe:2:2", "isa:53:0", "markdown"),
        _xref("1pe:2:2", "isa:53:0", "markdown"), _xref("mat:4:0", "deu:6:1"),
        _xref("1pe:2:2", "isa:53:0", "markdown"), _xref("rev:19:2", "dan:7:1"),
        # Other types are not checked: only CROSS_REFERENCES carry row data.
        {"start": "gen", "end": "gen:1", "type": "CONTAINS", "properties": {}},
        {"start": "gen", "end": "gen:1", "type": "CONTAINS", "properties": {}},
    ])

    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path)

    assert exc.value.code == 1
    listed = [line.strip() for line in capsys.readouterr().err.splitlines()
              if "→" in line]
    assert listed == ["1pe:2:2→isa:53:0 (3 rows)", "mat:4:0→deu:6:1 (2 rows)"]


def test_unique_pairs_reach_connection(monkeypatch, tmp_path, capsys):
    _write_rels(tmp_path, [
        _xref("mat:4:0", "deu:6:1"), _xref("deu:6:1", "mat:4:0"),
        _xref("1pe:2:2", "isa:53:0"),
        {"start": "gen", "end": "gen:1", "type": "CONTAINS", "properties": {}},
    ])

    with pytest.raises(_Connected):
        _run_main(monkeypatch, tmp_path)
    assert "3 CROSS_REFERENCES rows, no duplicate pair" in capsys.readouterr().out


def test_missing_file_reaches_connection(monkeypatch, tmp_path):
    # Same exists() semantics as the import itself (test_import_exit_codes runs
    # main() on an empty output dir and expects the connection failure).
    with pytest.raises(_Connected):
        _run_main(monkeypatch, tmp_path)
