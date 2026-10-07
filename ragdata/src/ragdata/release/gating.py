"""The core layers' hard gates, run again whenever a release is assembled (design §2.22, §8).

A layer was gated when it was built, but the store keeps every version and the gates
move on: kg0@3151851bc84f passed G-KG0 when it was built and fails it now. So a
release runs, for each core layer with the layers it depends on, every gate that reads
only the layers and the repository (``runner.record_gates``: not G-CONSERVE and
G-XCHECK, which re-read the PDFs) but G-ENC and G-ROUTE, which need BGE-M3 on a GPU and
the backend's environment; those two stay with the layer's own ``ragdata gate`` report.
G-EMB reads only token counts, so it gets the pinned tokenizers, not the model.

The verdicts are not written into the release: the build_id names the data alone, and
``read_release`` assembles again, so ``load`` and ``verify`` re-run the gates too.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from ragdata.contract.counts import PDF_COUNTS_PATH
from ragdata.gates import runner
from ragdata.stages.s06_emb.encoder import load_token_encoder
from ragdata.store import LayerData

NOT_RUN = frozenset({"G-ENC", "G-ROUTE"})
DETAILS = 3


@dataclass(frozen=True)
class ReleaseChecks:
    """What the release gates read besides the layers (``ragdata gate``'s inputs)."""

    counts_path: Path = PDF_COUNTS_PATH
    inputs: runner.GateInputs = field(default_factory=runner.GateInputs)


def default_checks(tokenizer: Path | None = None) -> ReleaseChecks:
    """The repository's expectations and registries; BGE-M3's tokenizer from ``tokenizer``
    or the HF cache."""
    return ReleaseChecks(inputs=runner.GateInputs(tokenizer=tokenizer))


def release_gates(layer: str) -> tuple[str, ...]:
    return tuple(name for name in runner.record_gates(layer) if name not in NOT_RUN)


def _with_token_encoder(inputs: runner.GateInputs) -> runner.GateInputs:
    if inputs.encoder is not None:
        return inputs
    return replace(inputs, encoder=load_token_encoder(inputs.tokenizer,
                                                      inputs.reranker_tokenizer))


def red_gates(layers: Mapping[str, LayerData], names: Sequence[str],
              checks: ReleaseChecks) -> list[str]:
    """``{version} {gate}: {details}`` for every red hard gate of the ``names`` layers.

    Raises GateInputError, StageError or StoreError when a layer cannot be gated."""
    inputs = _with_token_encoder(checks.inputs)
    red: list[str] = []
    for name in names:
        deps = [layers[dep].path for dep in runner.REQUIRED_DEPS[name]]
        report = runner.gate_layer(layers[name].path, name, deps, checks.counts_path,
                                   gates=release_gates(name), inputs=inputs)
        red += [f"{report.layer_version} {g.name}: {list(g.details[:DETAILS])}"
                for g in report.gates if g.hard and not g.passed]
    return red
