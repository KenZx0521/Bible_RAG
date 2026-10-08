"""Default locations of what a build reads besides the PDFs (all overridable on the CLI)."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STORE = Path("/mnt/ollama-data/bible_rag_store")
# copies of what the old system left, never edited; each directory has a SHA256SUMS
# that its readers check (ragdata.reference)
REFERENCE = STORE / "reference"
PDF_DIR = REPO / "bible_pdf"                  # the 66 PDFs every layer is built from
REGISTRIES = REPO / "config" / "registries"   # errata, normalization, versification
BIBLE_MD = REFERENCE / "bible_md"             # the old converter's corpus, for G-DIFF only
CANONICAL = (REFERENCE / "audit_prototypes" / "gap_pdf_canonical"
             / "canonical_full.jsonl")        # the audit's verse table, for G-DIFF only
LEGACY_OUTPUT = REFERENCE / "legacy_output"   # the old output/: pericopes and chunks for struct's
                                              # legacy_ids, embedding_queue and embeddings for
                                              # G-ENC; never a source of new records
MODELS = STORE / "models"
RERANKER_TOKENIZER = (MODELS / "bge-reranker-v2-m3" / "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
                      / "tokenizer.json")   # the reranker snapshot's tokenizer (no weights here)
# KG stages (K1; K4 reads REGISTRIES: the K0 ones and query_aliases.yaml)
EVENTS_REGISTRY = REGISTRIES / "events.yaml"                  # K1, the hand-kept registry
GROUND_TRUTH = REPO / "ground_truth.json"                     # GT v1, for G-GT's change log
# releases and what the loader writes beside the layers (design §2.22, §7.5)
RELEASES = STORE / "releases"                                  # releases/{build_id}.json
CONTRACTS = STORE / "contracts"                                # contracts/{build_id}/
GOLD = REPO / "config" / "gold"
GT_V2 = REPO / "ground_truth.v2.json"                          # G-PROJ C6
GT_V2_FREEZE = GOLD / "gt_v2_freeze.json"
