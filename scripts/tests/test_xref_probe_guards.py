"""xref_probe's input and usage guards (W1 1B): a bad input exits before a
target is read or a file is written, and a usage error exits 2 as --help says.
predict refuses an empty edge table and a seed file of another version;
fingerprint checks its --expect file before streaming the target's edges;
allow never writes its fragment over its own --expect file.
Split from test_xref_probe.py, whose fixtures it borrows.
"""

from __future__ import annotations

import json

import pytest

from scripts.tools import xref_probe as xp
from test_xref_probe import (SENTINEL_EDGES, FakeDriver, patch_target, profile_answers, run_expect,
                             write_jsonl, write_seeds)


def test_predict_refuses_no_edges_and_other_seed_versions_without_output(tmp_path, capsys):
    write_jsonl(tmp_path / "empty.jsonl", [])
    write_jsonl(tmp_path / "edges.jsonl", SENTINEL_EDGES)
    write_seeds(tmp_path / "seeds.json", ["jer:29:0"], {})
    (tmp_path / "v2.json").write_text(json.dumps({"version": 2, "singles": ["jer:29:0"], "sets": {}}),
                                      encoding="utf-8")
    out = tmp_path / "pred.json"

    def predict(seeds: str, edges: str) -> int:
        return xp.main(["predict", "--seeds", str(tmp_path / seeds), "--edges", str(tmp_path / edges),
                        "--out", str(out)])
    assert predict("seeds.json", "empty.jsonl") == 1          # no edges is never an empty prediction
    assert predict("v2.json", "edges.jsonl") == 1
    err = capsys.readouterr().err
    assert "no CROSS_REFERENCES edges read from" in err and "v2.json: not a version-1 seed file" in err
    assert not out.exists()


@pytest.mark.parametrize("argv, message", [
    (["predict", "--seeds", "s.json"], "predict needs --out"),
    (["predict", "--seeds", "s.json", "--out", "p.json"], "exactly one of --target and --edges"),
    (["predict", "--seeds", "s.json", "--out", "p.json", "--target", "prod", "--edges", "e.jsonl"],
     "exactly one of --target and --edges"),
])
def test_usage_errors_exit_2_as_the_help_says(argv, message, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        xp.main(argv)
    assert exc.value.code == 2 and message in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    assert "2 a usage error" in " ".join(xp.__doc__.split())


def test_fingerprint_checks_the_expect_file_before_reading_the_target(tmp_path, monkeypatch, capsys):
    reads = []

    def read_target(*args):                     # about 250k edge rows on the real graphs
        reads.append(args)
        raise AssertionError("the target was read before --expect was checked")
    monkeypatch.setattr(xp, "_read_target", read_target)
    (tmp_path / "v2.json").write_text(json.dumps({"version": 2}), encoding="utf-8")
    for expect in ("missing.json", "v2.json"):
        assert xp.main(["fingerprint", "--target", "staging", "--expect", str(tmp_path / expect)]) == 1
    assert reads == []
    err = capsys.readouterr().err
    assert "missing.json" in err and "v2.json: not a version-1 expect file" in err


def test_allow_refuses_to_overwrite_its_expect_file(tmp_path, monkeypatch, capsys):
    assert run_expect(tmp_path) == 0
    before = (tmp_path / "xref.json").read_bytes()
    resolved = patch_target(monkeypatch, FakeDriver(profile_answers()))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        xp.main(["allow", "--expect", "xref.json", "--out", "./xref.json"])    # one file, spelt two ways
    assert exc.value.code == 2 and "allow --out would overwrite the expect file" in capsys.readouterr().err
    assert resolved == [] and (tmp_path / "xref.json").read_bytes() == before
