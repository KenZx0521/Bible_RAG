"""Reference copies checked against their SHA256SUMS (ragdata.reference)."""

from __future__ import annotations

import hashlib
import subprocess

import pytest

import ref_dirs
from ragdata import reference
from ragdata.stages.errors import StageError


@pytest.fixture()
def copy(tmp_path):
    (tmp_path / "a.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "路得記.md").write_text("# 路得記\n", encoding="utf-8")
    return ref_dirs.sign(tmp_path)


def test_listed_files_give_their_sha256(copy):
    digests = reference.verified(copy, ["a.jsonl", "路得記.md"])
    assert digests["a.jsonl"] == hashlib.sha256(b"{}\n").hexdigest()


def test_the_list_is_what_sha256sum_writes_and_checks(copy):
    done = subprocess.run(["sha256sum", "-c", reference.SUMS], cwd=copy, capture_output=True,
                          text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_binary_markers_and_dot_slash_names_are_read(copy):
    sha = reference.read_sums(copy)["a.jsonl"]
    (copy / reference.SUMS).write_text(f"{sha} *./a.jsonl\n", encoding="utf-8")
    assert reference.verified(copy, ["a.jsonl"]) == {"a.jsonl": sha}


@pytest.mark.parametrize("change, message", [
    (lambda d: (d / "a.jsonl").write_text("{}\n{}\n", encoding="utf-8"), "copy changed"),
    (lambda d: (d / reference.SUMS).write_text("", encoding="utf-8"), "not listed"),
    (lambda d: (d / reference.SUMS).unlink(), "SHA256SUMS: unreadable"),
    (lambda d: (d / reference.SUMS).write_text("abc  a.jsonl\n", encoding="utf-8"),
     "not a sha256sum line"),
    (lambda d: (d / "a.jsonl").unlink(), "a.jsonl: unreadable"),
])
def test_a_changed_missing_or_unlisted_file_stops_the_reader(copy, change, message):
    change(copy)
    with pytest.raises(StageError, match=message):
        reference.verified(copy, ["a.jsonl"])
