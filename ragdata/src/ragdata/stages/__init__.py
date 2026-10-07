"""Build stages (design §4). S0–S4 (PDF → text layer) are the next step of the
rebuild; until a stage exists, ``build`` raises instead of producing anything."""

from __future__ import annotations

from pathlib import Path

from ragdata.store import StoredLayer

BUILDABLE = ("text",)


class StageNotImplementedError(RuntimeError):
    """The requested stage has not been written yet."""


def build(layer: str, pdf_dir: Path, store_root: Path) -> StoredLayer:
    """Build ``layer`` from the PDFs into the store and return the stored version."""
    if layer not in BUILDABLE:
        raise ValueError(f"no stage builds layer {layer!r}")
    raise StageNotImplementedError(
        f"stage for layer {layer!r} (S0–S4: PDF → text layer) is not implemented yet")
