"""Reference directories in the tests: the SHA256SUMS their readers check (ragdata.reference)."""

from __future__ import annotations

from pathlib import Path

from ragdata import reference


def sign(directory: Path) -> Path:
    """Write ``directory/SHA256SUMS`` over every other file in it; returns ``directory``."""
    names = sorted(p.name for p in directory.iterdir() if p.is_file() and p.name != reference.SUMS)
    digests = {name: reference.sha256_file(directory / name) for name in names}
    (directory / reference.SUMS).write_bytes(reference.encode_sums(digests))
    return directory
