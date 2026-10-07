"""Default locations of what a build reads besides the PDFs (all overridable on the CLI)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REGISTRIES = REPO / "config" / "registries"   # errata, normalization, versification
BIBLE_MD = REPO / "bible_md"                  # the converter corpus the layer replaces
CANONICAL = Path("/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/"
                 "gap_pdf_canonical/canonical_full.jsonl")  # the audit's verse table
LEGACY_OUTPUT = REPO / "output"              # the old build's records, read for legacy_ids only
MODELS = Path("/mnt/ollama-data/bible_rag_store/models")
RERANKER_TOKENIZER = (MODELS / "bge-reranker-v2-m3" / "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
                      / "tokenizer.json")   # the reranker snapshot's tokenizer (no weights here)
# KG stages (K1, K4) and the DAG-external tools that write their registries
EVENTS_REGISTRY = REGISTRIES / "events.yaml"                  # K1, converted from the next line
LEGACY_EVENT_REGISTRY = REPO / "backend" / "data" / "event_registry.json"
FROZEN_LEXICON = REGISTRIES / "routing_lexicon.legacy.json"   # K4, frozen from the backend
GROUND_TRUTH = REPO / "ground_truth.json"                     # G-ROUTE probe questions
BACKEND = REPO / "backend"
BACKEND_PYTHON = BACKEND / ".venv" / "bin" / "python"          # imports entity_dicts (G-ROUTE)
