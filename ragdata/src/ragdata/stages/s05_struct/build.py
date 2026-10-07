"""Build the struct layer from a stored text layer (S5) and store it if its gates pass.

Inputs: the text layer (verified on read and required to pass G-SCHEMA), the
pinned BGE-M3 tokenizer, and the old ``output/`` for the legacy map only. The
gates are G-SCHEMA, G-COUNT, G-REFINT and G-STRUCT over the text and new struct
records together; a red build writes nothing. The layer holds the five record
files and ``struct_report.json`` (what shaped it: text version, template,
tokenizer, chunk parameters, legacy input sha256 and relation counts).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata import paths
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.contract.registry import STRUCT_REPORT
from ragdata.contract.struct import CHUNK_MAX_TOKENS
from ragdata.gates.base import GateResult, Snapshot, snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.refint import check_refint
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.gates.struct import check_struct
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.stages.s05_struct import chunker, content, legacy, rows
from ragdata.stages.s05_struct.tokens import TokenCounter, pinned_counter
from ragdata.stages.s05_struct.view import text_view
from ragdata.store import LayerData, StoredLayer, encode_jsonl, read_layer, write_layer

REPORT_SCHEMA = "ragdata.struct_report.v1"
STRUCT_FILES = (*rows.STRUCT_TYPES, "legacy_ids")


@dataclass(frozen=True)
class StructInputs:
    """What a struct build reads besides the text layer."""

    legacy_dir: Path = paths.LEGACY_OUTPUT      # old pericopes.jsonl / chunks.jsonl
    tokenizer: Path | None = None               # tokenizer.json; None: the pinned HF snapshot
    counter: TokenCounter | None = None         # a stand-in counter (tests only)


def _text_snapshot(text_dir: Path) -> tuple[LayerData, Snapshot]:
    text = read_layer(text_dir)
    if text.layer != "text":
        raise StageError(f"{text_dir} holds a {text.layer} layer, not a text layer")
    schema, snap = check_schema(merge_files([text]), ["text"])
    if not schema.passed:
        raise StageError(f"{text_dir}: the text layer fails G-SCHEMA: {list(schema.details[:3])}")
    return text, snap


def _gates(text: Snapshot, struct: Mapping[str, Sequence[dict]], counts_path: Path,
           counter: TokenCounter) -> list[GateResult]:
    schema, own = check_schema({f"{n}.jsonl": struct[n] for n in STRUCT_FILES}, ["struct"])
    both = snapshot({**text.records, **own.records})
    return [schema, check_counts(both, "struct", load_counts(counts_path).get("struct", {})),
            check_refint(both, "struct"), check_struct(both, counter)]


def _report(text_version: str, counter: TokenCounter, legacy_in: legacy.LegacyInputs,
            struct: Mapping[str, Sequence[dict]]) -> bytes:
    relations: dict[str, Counter] = {}
    for row in struct["legacy_ids"]:
        relations.setdefault(row["kind"], Counter())[row["relation"]] += 1
    doc: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "text_layer": text_version,
        "template_id": content.TEMPLATE_ID, "tokenizer": dict(counter.fingerprint),
        "chunking": {"max_tokens": CHUNK_MAX_TOKENS, "target_tokens": chunker.TARGET_TOKENS,
                     "min_tokens": chunker.MIN_TOKENS, "overlap_pieces": chunker.OVERLAP,
                     "merge_max_pieces": chunker.MERGE_MAX_PIECES,
                     "head_slack": chunker.HEAD_SLACK},
        "legacy_inputs": dict(legacy_in.sha256),
        "legacy_relations": {k: dict(v) for k, v in relations.items()},
        "counts": {name: len(struct[name]) for name in STRUCT_FILES},
    }
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build_struct(text_dir: Path, store_root: Path, counts_path: Path = PDF_COUNTS_PATH,
                 inputs: StructInputs = StructInputs()) -> BuildResult:
    """S5 over the text layer in ``text_dir``; the layer is stored only if every gate passed."""
    clock = Clock()
    with clock.lap("load_text"):
        text, text_snap = _text_snapshot(Path(text_dir))
        view = text_view(text_snap)
    with clock.lap("tokenizer"):
        counter = inputs.counter or pinned_counter(inputs.tokenizer)
    with clock.lap("s5_struct"):
        struct = rows.struct_rows(view, counter)
    with clock.lap("legacy_ids"):
        legacy_in = legacy.load_legacy(inputs.legacy_dir)
        struct = {**struct, "legacy_ids": legacy.legacy_rows(legacy_in, struct, view)}
    with clock.lap("gates"):
        gates = _gates(text_snap, struct, Path(counts_path), counter)
    layers: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            files = {**{f"{n}.jsonl": encode_jsonl(struct[n]) for n in STRUCT_FILES},
                     STRUCT_REPORT: _report(text.version, counter, legacy_in, struct)}
            layers["struct"] = write_layer(store_root, "struct", files,
                                           depends_on={"text": text.version}, exist_ok=True)
    return BuildResult(MappingProxyType(layers), tuple(gates), MappingProxyType(clock.laps))
