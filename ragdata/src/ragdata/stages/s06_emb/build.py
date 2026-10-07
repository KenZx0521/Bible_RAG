"""Build the emb layer from stored struct and text layers (S6 records, S7 vectors).

Inputs: the struct layer and the text layer it was built on (both verified on
read and required to pass G-SCHEMA), the pinned encoder (``encoder.load_encoder``)
and the old ``output/`` for the legacy compatibility check. The gates are G-SCHEMA,
G-COUNT, G-EMB and G-ENC; a red build writes nothing.

The layer holds ``embedding_records.jsonl``, ``emb_report.json`` (inputs, the
declared template, counts) and ``encoder_fingerprint.json``, so its version
follows from the records, the fingerprint and the template. The vectors are the
layer's ``vectors`` attachment (``vectors.npy``, ``vector_index.jsonl``) and do not
enter the version. A rebuild of a stored version keeps the stored vectors, and
stops if this run's vectors are not within G-DET's tolerance of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

from ragdata import paths
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.contract.registry import EMB_REPORT, ENCODER_FINGERPRINT
from ragdata.gates import emb_legacy
from ragdata.gates.base import GateResult, Snapshot, snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.emb import EmbFiles, check_emb
from ragdata.gates.enc import run_enc
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.gates.vectors import compare_runs
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.stages.s06_emb import fingerprint
from ragdata.stages.s06_emb.encoder import BATCH_SIZE, Encoder, encode_texts, load_encoder
from ragdata.stages.s06_emb.records import emb_records, emb_report
from ragdata.stages.s06_emb.template import V1C
from ragdata.store import LayerData, StoredLayer, encode_jsonl, read_layer, write_layer
from ragdata.store import vectors as vector_files
from ragdata.store.attach import Attachment, read_attachment, write_attachment

RECORDS = "embedding_records.jsonl"


@dataclass(frozen=True)
class EmbInputs:
    """What an emb build reads besides the struct and text layers."""

    tokenizer: Path | None = None                      # BGE-M3 tokenizer.json; None: HF cache
    reranker_tokenizer: Path = paths.RERANKER_TOKENIZER
    legacy_dir: Path = paths.LEGACY_OUTPUT             # old embedding_queue / embeddings
    device: str | None = None                          # None: cuda when available
    batch_size: int = BATCH_SIZE
    compat_sample: int = emb_legacy.SAMPLE
    encoder: Encoder | None = None                     # a stand-in encoder (tests only)


def load_inputs(struct_dir: Path, text_dir: Path) -> tuple[LayerData, LayerData, Snapshot]:
    """The text and struct layers, checked to belong together and to pass G-SCHEMA."""
    struct, text = read_layer(struct_dir), read_layer(text_dir)
    for data, layer in ((struct, "struct"), (text, "text")):
        if data.layer != layer:
            raise StageError(f"{data.path} holds a {data.layer} layer, not a {layer} layer")
    if struct.depends_on.get("text") != text.version:
        raise StageError(f"{struct.version} was built on {struct.depends_on.get('text')}, "
                         f"not on {text.version}")
    schema, snap = check_schema(merge_files([text, struct]), ["text", "struct"])
    if not schema.passed:
        raise StageError(f"the text and struct layers fail G-SCHEMA: {list(schema.details[:3])}")
    return text, struct, snap


def _gates(base: Snapshot, rows: Sequence[dict], report: Mapping[str, Any],
           fp: Mapping[str, Any], vfiles: Mapping[str, bytes], enc: Encoder,
           counts_path: Path, inputs: EmbInputs) -> list[GateResult]:
    schema, own = check_schema({RECORDS: rows}, ["emb"])
    snap = snapshot({**base.records, **own.records})
    matrix, index = vector_files.decode_vectors(vfiles)
    counts = check_counts(snap, "emb", load_counts(counts_path).get("emb", {}))
    return [schema, counts, check_emb(snap, EmbFiles(report, matrix, index), enc.stats),
            run_enc(snap.of("embedding_records"), matrix, fp, enc, inputs.legacy_dir,
                    inputs.compat_sample)]


def _json(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _keep_stored(layer: StoredLayer, stored: Attachment, vfiles: Mapping[str, bytes]) -> None:
    """A version stored before keeps its vectors; this run must agree with them."""
    _, files = read_attachment(layer.path, vector_files.NAME)
    if files == dict(vfiles):
        return
    (old, old_index), (new, new_index) = (vector_files.decode_vectors(files),
                                          vector_files.decode_vectors(vfiles))
    ids = [[r["record_id"] for r in index] for index in (old_index, new_index)]
    _, violations = compare_runs(ids[0], old, ids[1], new)
    if violations:
        raise StageError(f"{layer.version}: the vectors already stored at {stored.path} "
                         f"differ from this run: {violations[:3]}")


def _store(root: Path, text: LayerData, struct: LayerData, files: Mapping[str, bytes],
           vfiles: Mapping[str, bytes], enc: Encoder) -> tuple[StoredLayer, Attachment]:
    layer = write_layer(root, "emb", files, exist_ok=True,
                        depends_on={"struct": struct.version, "text": text.version})
    meta = {"encode": dict(enc.model), "runtime": dict(enc.runtime)}
    stored = write_attachment(layer, vector_files.NAME, vfiles, meta, exist_ok=True)
    _keep_stored(layer, stored, vfiles)
    return layer, stored


def _encoder(inputs: EmbInputs) -> Encoder:
    return inputs.encoder or load_encoder(inputs.tokenizer, inputs.reranker_tokenizer,
                                          inputs.device, inputs.batch_size)


def build_emb(struct_dir: Path, text_dir: Path, store_root: Path,
              counts_path: Path = PDF_COUNTS_PATH, inputs: EmbInputs = EmbInputs()
              ) -> BuildResult:
    """S6 and S7 over the struct layer in ``struct_dir`` and its text layer in ``text_dir``;
    the layer and its vectors are stored only if every gate passed."""
    clock = Clock()
    with clock.lap("load_layers"):
        text, struct, snap = load_inputs(Path(struct_dir), Path(text_dir))
    with clock.lap("encoder"):
        enc = _encoder(inputs)
    with clock.lap("s6_records"):
        rows = emb_records(snap, V1C, enc.stats)
        report = emb_report(struct.version, text.version, V1C, rows)
    with clock.lap("s7_encode"):
        matrix: np.ndarray = encode_texts(enc, [r["text"] for r in rows])
        fp = fingerprint.encoder_fingerprint(enc)
        vfiles = vector_files.encode_vectors([(r["record_id"], r["text_sha"]) for r in rows],
                                             matrix)
    with clock.lap("gates"):
        gates = _gates(snap, rows, report, fp, vfiles, enc, Path(counts_path), inputs)
    layers: dict[str, StoredLayer] = {}
    attachments: dict[str, Mapping[str, Any]] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            files = {RECORDS: encode_jsonl(rows), EMB_REPORT: _json(report),
                     ENCODER_FINGERPRINT: fingerprint.encode(fp)}
            layers["emb"], stored = _store(Path(store_root), text, struct, files, vfiles, enc)
            attachments["emb"] = {"path": str(stored.path), "files": dict(stored.file_shas)}
    return BuildResult(MappingProxyType(layers), tuple(gates), MappingProxyType(clock.laps),
                       MappingProxyType(attachments))
