"""Reference files a build reads but never derives (the store's ``reference/``), checked by digest.

Each reference directory holds a ``SHA256SUMS`` in ``sha256sum`` format (names relative
to the directory). A reader names the files it reads and ``verified`` hashes them: a file
that is missing, not listed, or not the bytes the list records stops the reader, so a
changed reference fails loudly instead of silently changing a layer or a gate. The copies
are never edited; a new reference goes into a new directory with its own ``SHA256SUMS``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, Mapping

from ragdata.stages.errors import StageError

SUMS = "SHA256SUMS"
_LINE_RE = re.compile(r"([0-9a-f]{64}) [ *](?:\./)?(.+)")
_BLOCK = 1 << 20


class ReferenceError(StageError):
    """A reference file is missing, unlisted, or not the bytes its SHA256SUMS records."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def read_sums(directory: Path) -> dict[str, str]:
    """File name -> sha256, as ``directory/SHA256SUMS`` lists them."""
    path = Path(directory) / SUMS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ReferenceError(f"{path}: unreadable ({exc}); a reference directory lists "
                             "the sha256 of every file it holds") from None
    sums: dict[str, str] = {}
    for number, line in enumerate(lines, start=1):
        found = _LINE_RE.fullmatch(line)
        if found is None:
            raise ReferenceError(f"{path}:{number}: not a sha256sum line: {line[:80]!r}")
        sums[found.group(2)] = found.group(1)
    return sums


def check(directory: Path, digests: Mapping[str, str]) -> None:
    """Stop unless every ``name -> sha256`` of ``digests`` is what SHA256SUMS records."""
    sums = read_sums(directory)
    for name, sha in digests.items():
        path = Path(directory) / name
        if name not in sums:
            raise ReferenceError(f"{path}: not listed in {Path(directory) / SUMS}")
        if sha != sums[name]:
            raise ReferenceError(f"{path}: sha256 {sha} is not the {sums[name]} that "
                                 f"{SUMS} records; the reference copy changed")


def verified(directory: Path, names: Iterable[str]) -> dict[str, str]:
    """The sha256 of each named file of ``directory``, checked against its SHA256SUMS."""
    digests = {}
    for name in names:
        try:
            digests[name] = sha256_file(Path(directory) / name)
        except OSError as exc:
            raise ReferenceError(f"{Path(directory) / name}: unreadable: {exc}") from None
    check(directory, digests)
    return digests


def encode_sums(digests: Mapping[str, str]) -> bytes:
    """``SHA256SUMS`` bytes for ``name -> sha256`` (sorted by name, as sha256sum writes)."""
    return "".join(f"{digests[name]}  {name}\n" for name in sorted(digests)).encode("utf-8")
