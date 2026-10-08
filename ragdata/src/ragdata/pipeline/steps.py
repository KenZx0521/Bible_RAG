"""The layer steps of ``ragdata pipeline run``: build one layer, then gate what was stored.

A build runs the gates of its stage and stores nothing when a hard one is red. The stored
layer is then gated again with every gate design §8 requires of it (``gates.runner``),
including the ones a build cannot run: G-CONSERVE re-reads the src layer, G-XCHECK the
PDFs, G-REF compares ragcommon's verse grid, G-ENC encodes every record again with the
pinned BGE-M3 (on cuda) and G-ROUTE compares the frozen lexicon's matcher with the old
backend's matches frozen in the store (no backend runs).

``Sources`` holds what the builds and gates read besides the store; one ``GateInputs``
serves both, so a build and the gate after it read the same registries, tokenizer,
reference copies (bible_md, the old ``output/``, the frozen matches) and encoder.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping

from ragdata import paths, stages
from ragdata.contract.counts import PDF_COUNTS_PATH
from ragdata.gates.runner import REQUIRED_DEPS, GateInputs, GateReport, gate_layer
from ragdata.kg import k0_build, k1_build, k4_build, k4_live
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult
from ragdata.stages.s05_struct.build import StructInputs, build_struct
from ragdata.stages.s06_emb.build import EmbInputs, build_emb
from ragdata.store import StoredLayer

ORDER = ("text", "struct", "emb", "kg0", "events", "route")
GATE_DEPS: Mapping[str, tuple[str, ...]] = {**REQUIRED_DEPS, "text": ("src",)}
Built = Mapping[str, StoredLayer]


@dataclass(frozen=True)
class Sources:
    """What the layer builds and gates read besides the store (default: ``paths``)."""

    gate: GateInputs = field(default_factory=lambda: GateInputs(pdf_dir=paths.PDF_DIR))
    counts: Path = PDF_COUNTS_PATH
    events_yaml: Path = paths.EVENTS_REGISTRY
    text: stages.TextInputs = stages.TextInputs()
    workers: int = 8


@dataclass(frozen=True)
class Step:
    """One layer: ``build`` stores it (and src, for text); ``gate`` checks what was stored."""

    layer: str
    build: Callable[[Built], BuildResult]
    gate: Callable[[Built], GateReport]


def gate_stored(layer: str, built: Built, sources: Sources) -> GateReport:
    """Every required gate of the stored ``layer``, with the layers it was built on."""
    deps = [built[dep].path for dep in GATE_DEPS[layer]]
    return gate_layer(built[layer].path, layer, deps, sources.counts, inputs=sources.gate)


def _text(built: Built, store: Path, s: Sources) -> BuildResult:
    g = s.gate
    if g.pdf_dir is None:
        raise StageError("the text build reads the PDFs; no pdf_dir was given")
    return stages.build("text", g.pdf_dir, store, counts_path=s.counts,
                        expect_path=g.source_expect, workers=s.workers,
                        inputs=replace(s.text, registries=g.registries))


def _struct(built: Built, store: Path, s: Sources) -> BuildResult:
    g = s.gate
    inputs = StructInputs(legacy_dir=g.legacy_dir, tokenizer=g.tokenizer, counter=g.token_counter)
    return build_struct(built["text"].path, store, counts_path=s.counts, inputs=inputs)


def _emb(built: Built, store: Path, s: Sources) -> BuildResult:
    g = s.gate
    inputs = EmbInputs(tokenizer=g.tokenizer, reranker_tokenizer=g.reranker_tokenizer,
                       legacy_dir=g.legacy_dir, device=g.device, compat_sample=g.compat_sample,
                       encoder=g.encoder)
    return build_emb(built["struct"].path, built["text"].path, store, counts_path=s.counts,
                     inputs=inputs)


def _kg0(built: Built, store: Path, s: Sources) -> BuildResult:
    return k0_build.build_kg0(built["text"].path, built["struct"].path, store,
                              s.gate.registries, s.gate.kg0_counts)


def _events(built: Built, store: Path, s: Sources) -> BuildResult:
    return k1_build.build_events(built["text"].path, built["struct"].path, store,
                                 s.events_yaml, s.gate.legacy_registry, s.counts)


def _route(built: Built, store: Path, s: Sources) -> BuildResult:
    g = s.gate
    live = g.live_probe or k4_live.stored_probe(g.route_live, g.frozen_lexicon)
    return k4_build.build_route(built["text"].path, store, live, g.frozen_lexicon,
                                g.ground_truth, s.counts)


BUILDERS: Mapping[str, Callable[[Built, Path, Sources], BuildResult]] = {
    "text": _text, "struct": _struct, "emb": _emb, "kg0": _kg0, "events": _events,
    "route": _route,
}


def layer_step(layer: str, store: Path, sources: Sources) -> Step:
    build = BUILDERS[layer]
    return Step(layer, lambda built: build(built, store, sources),
                lambda built: gate_stored(layer, built, sources))


def layer_steps(store: Path, sources: Sources) -> tuple[Step, ...]:
    """The six layer steps in build order."""
    return tuple(layer_step(layer, Path(store), sources) for layer in ORDER)
