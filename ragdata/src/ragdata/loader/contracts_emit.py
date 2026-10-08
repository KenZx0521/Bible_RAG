"""Write a build's contract files to ``contracts/{build_id}/`` (design §7.5), once.

The directory is published with one ``rename`` from a temporary sibling, its files
read-only; an existing directory is never touched (the backend mounts it read-only
and selects it by the serving build id).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

MANIFEST = "manifest.json"


class ContractsExistError(FileExistsError):
    """The build's contract directory exists already."""


def write_contracts(directory: Path, files: Mapping[str, bytes]) -> Path:
    directory = Path(directory)
    if directory.exists():
        raise ContractsExistError(f"{directory} exists")
    directory.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{directory.name}-", dir=directory.parent))
    try:
        for name, data in sorted(files.items()):
            with open(tmp / name, "xb") as handle:
                handle.write(data)
            os.chmod(tmp / name, 0o444)
        os.chmod(tmp, 0o755)
        if directory.exists():
            raise ContractsExistError(f"{directory} exists")
        os.rename(tmp, directory)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return directory


def read_contracts(directory: Path) -> dict[str, bytes] | None:
    """Every file of a contract directory, or None when there is none."""
    directory = Path(directory)
    if not directory.is_dir():
        return None
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}
