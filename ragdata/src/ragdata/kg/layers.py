"""Load the stored layers a KG stage builds on: verified, of the right kind, consistent
with each other (struct built on that text) and passing G-SCHEMA, or a StageError."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragdata.gates.base import Snapshot
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.stages.errors import StageError
from ragdata.store import LayerData, read_layer


def _layer(path: Path, kind: str) -> LayerData:
    data = read_layer(path)
    if data.layer != kind:
        raise StageError(f"{path} holds a {data.layer} layer, not a {kind} layer")
    return data


def load_inputs(text_dir: Path, struct_dir: Path | None = None
                ) -> tuple[dict[str, LayerData], Snapshot]:
    """The text (and struct) layers and their records; struct must be built on that text."""
    layers = {"text": _layer(Path(text_dir), "text")}
    if struct_dir is not None:
        layers["struct"] = _layer(Path(struct_dir), "struct")
        if layers["struct"].depends_on.get("text") != layers["text"].version:
            built_on = layers["struct"].depends_on.get("text")
            raise StageError(f"{struct_dir} was built on {built_on}, "
                             f"not on {layers['text'].version}")
    schema, snap = check_schema(merge_files(list(layers.values())), list(layers))
    if not schema.passed:
        raise StageError(f"input layers fail G-SCHEMA: {list(schema.details[:3])}")
    return layers, snap


def with_records(base: Snapshot, own: Snapshot) -> Snapshot:
    return Snapshot({**base.records, **own.records})


def encode_json(doc: Mapping[str, Any] | Sequence[Any]) -> bytes:
    """A report or contract document: sorted keys, two-space indent, UTF-8, final newline."""
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
