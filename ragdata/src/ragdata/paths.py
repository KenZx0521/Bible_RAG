"""Default locations of what a build reads besides the PDFs (all overridable on the CLI)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REGISTRIES = REPO / "config" / "registries"   # errata, normalization, versification
BIBLE_MD = REPO / "bible_md"                  # the converter corpus the layer replaces
CANONICAL = Path("/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/"
                 "gap_pdf_canonical/canonical_full.jsonl")  # the audit's verse table
LEGACY_OUTPUT = REPO / "output"              # the old build's records, read for legacy_ids only
