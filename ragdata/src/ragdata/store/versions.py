"""The layer names and versions the store accepts: ragcommon's, and the graph layer's.

``ragcommon.ids`` spells the versions of the layers a served build is made of, and its source is
part of metric_version (``evaluation/quick_retrieval_eval.py`` hashes the file): a new name there
makes the closed experiments' integrity checks refuse to run. Only ragdata reads a graph layer's
version, so that one name lives here, with the same grammar: ``{layer}@{digest[:12]}``.
"""

from __future__ import annotations

import re

from ragcommon import ids

GRAPH = "graph"
LAYERS = (*ids.LAYERS, GRAPH)
_GRAPH_VERSION = re.compile(rf"{GRAPH}@[0-9a-f]{{12}}")
_ANY_LAYER = ids.LAYERS[0]          # any name ids knows: it checks the digest, whatever the layer


def layer_version(layer: str, digest: str) -> str:
    """``{layer}@{digest[:12]}``; raises ``ids.IdError`` for an unknown layer or a bad digest."""
    if layer == GRAPH:
        return f"{GRAPH}@{ids.parse(ids.layer_version(_ANY_LAYER, digest)).digest}"
    return ids.layer_version(layer, digest)


def layer_of(version: object) -> str | None:
    """The layer a well-formed version belongs to; None for anything else."""
    if isinstance(version, str) and _GRAPH_VERSION.fullmatch(version):
        return GRAPH
    if isinstance(version, str) and ids.is_valid(version, "layer_version"):
        return ids.parse(version).text
    return None
