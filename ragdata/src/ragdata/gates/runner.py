"""Run the data gates of one stored layer and collect them into a JSON report.

A layer is gated together with the record layers it depends on (struct needs
text); each must be the exact version the layer's manifest declares. A ``src``
dependency (the PDFs as extracted) holds no records: it may be given like any
dependency (``--dep``) and is then verified, not loaded, and G-CONSERVE re-reads
it; G-XCHECK re-reads the PDFs (``GateInputs.pdf_dir``). A gate whose input is
not given fails closed. Any other declared dependency must be a record layer,
or the layer is refused. Whether src came from the pinned PDFs and tools is
G-SRC/G-TOOL's job at build time, and ``build`` stores nothing when they fail.
Besides its records a layer may hold the reports its build wrote
(``LAYER_REPORTS``), nothing else.

``REQUIRED_GATES`` lists, per layer, every gate of design §8 whose subject is
that layer (G-DET compares two runs and has its own command). A gate that is
not built yet still appears in the report as a failing hard gate, so the
report fails closed: it passes only when every required gate ran and every
hard gate passed. Tests may run a subset (``gates=``) to see what the built
gates catch; such a report never passes.

An emb layer is gated with its struct and text layers. G-EMB and G-ENC also read
its report, fingerprint and ``vectors`` attachment, and the pinned encoder
(``GateInputs``: tokenizer files, device, the old ``output/`` for the legacy
check); an encoder that does not load fails both closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ragcommon.versification import Versification, default_versification
from ragdata import paths
from ragdata.contract import LAYERS, record_type_for_file
from ragdata.contract.counts import (
    KG0_COUNTS_PATH, PDF_COUNTS_PATH, load_counts, load_kg0_counts,
)
from ragdata.contract.registry import (
    EMB_REPORT, ENCODER_FINGERPRINT, EVENT_REGISTRY_V1, EVENT_REGISTRY_V2, KG0_REPORT,
    LAYER_REPORTS, ROUTE_REPORT, ROUTING_LEXICON, XCHECK_REPORT,
)
from ragdata.gates import emb_legacy, sourced
from ragdata.gates.base import GateInputError, GateResult, Snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.emb import EmbFiles, check_emb
from ragdata.gates.enc import REENCODE, EncOptions, StoredEncoding, run_enc
from ragdata.gates.events import check_event
from ragdata.gates.kg0 import check_kg0
from ragdata.gates.prov import check_prov
from ragdata.gates.ref import check_ref
from ragdata.gates.route import check_route
from ragdata.gates.refint import check_refint
from ragdata.gates.schema import check_schema
from ragdata.gates.struct import check_struct
from ragdata.gates.text import check_text
from ragdata.kg import k4_route
from ragdata.kg.k4_route import LiveProbe
from ragdata.stages.errors import StageError
from ragdata.stages.s00_source import EXPECT_PATH
from ragdata.stages.s04_overlay.normalization import load_normalization
from ragdata.stages.s05_struct.tokens import TokenCounter, pinned_counter
from ragdata.stages.s06_emb.encoder import Encoder, load_encoder
from ragdata.store import (
    DEPENDS_ON, MANIFEST, LayerData, StoreError, attach, read_layer, vectors, verify_layer,
)

REPORT_SCHEMA = "ragdata.gate_report.v1"
REQUIRED_DEPS: Mapping[str, tuple[str, ...]] = {
    "text": (), "struct": ("text",), "emb": ("struct", "text"), "kg0": ("text", "struct"),
    "events": ("text", "struct"), "route": ("text",),
}
REQUIRED_GATES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "text": ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-TEXT", "G-CONSERVE", "G-XCHECK", "G-REF"),
    "struct": ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-STRUCT"),
    "emb": ("G-SCHEMA", "G-COUNT", "G-EMB", "G-ENC"),
    "kg0": ("G-SCHEMA", "G-REFINT", "G-KG0", "G-PROV"),
    "events": ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-EVENT", "G-PROV"),
    "route": ("G-SCHEMA", "G-COUNT", "G-ROUTE", "G-PROV"),
})
NOT_IMPLEMENTED = "not implemented"
UNLOADED_DEPS = frozenset({"src"})


@dataclass(frozen=True)
class GateInputs:
    """What some gates read besides the layers."""

    pdf_dir: Path | None = None                   # G-XCHECK: the PDFs, read with poppler
    registries: Path = paths.REGISTRIES           # G-TEXT: normalization.yaml (ASCII allow-list)
    source_expect: Path = EXPECT_PATH             # G-CONSERVE: the corpus totals
    versification: Versification | None = None    # G-REF: None means ragcommon's data
    tokenizer: Path | None = None                 # G-STRUCT/emb: tokenizer.json (None: HF cache)
    token_counter: TokenCounter | None = None     # G-STRUCT: a stand-in counter (tests only)
    reranker_tokenizer: Path = paths.RERANKER_TOKENIZER   # G-ENC
    legacy_dir: Path = paths.LEGACY_OUTPUT        # G-ENC: the old embedding_queue / embeddings
    compat_sample: int = emb_legacy.SAMPLE        # G-ENC: records checked against the old index
    reencode_sample: int = REENCODE               # G-ENC: records encoded again away from cuda
    device: str | None = None                     # G-EMB/G-ENC: where BGE-M3 runs
    encoder: Encoder | None = None                # G-EMB/G-ENC: a stand-in encoder (tests only)
    kg0_counts: Path = KG0_COUNTS_PATH            # G-KG0: the per-surface expectations
    legacy_registry: Path = paths.LEGACY_EVENT_REGISTRY  # G-EVENT: what R1 froze
    frozen_lexicon: Path = paths.FROZEN_LEXICON   # G-ROUTE: the frozen routing lexicon
    ground_truth: Path = paths.GROUND_TRUTH       # G-ROUTE: probe questions
    backend_python: Path = paths.BACKEND_PYTHON   # G-ROUTE: runs the live entity_dicts
    backend_dir: Path = paths.BACKEND
    live_probe: LiveProbe | None = None           # G-ROUTE: a stand-in live matcher (tests only)


@dataclass(frozen=True)
class EmbContext:
    """What G-EMB and G-ENC read of an emb layer besides its records."""

    files: EmbFiles
    stored: StoredEncoding
    encoder: Encoder | None
    encoder_error: str | None


@dataclass(frozen=True)
class GateContext:
    """What the gates of one run read."""

    layer: str
    schema: GateResult
    snapshot: Snapshot
    counts_path: Path | str
    target: LayerData
    src: Mapping[str, bytes] | None
    inputs: GateInputs
    emb: EmbContext | None = None


def missing_input(name: str, what: str) -> GateResult:
    return GateResult(name, hard=True, passed=False, observed="missing input",
                      expected=what, details=(f"{name} needs {what}",))


def _count_gate(ctx: GateContext) -> GateResult:
    return check_counts(ctx.snapshot, ctx.layer, load_counts(ctx.counts_path).get(ctx.layer, {}))


def _text_gate(ctx: GateContext) -> GateResult:
    """G-TEXT under the current text policy (a stricter ASCII allow-list flags older layers);
    the registries a layer was built with are recorded by sha256 in its overlay report."""
    norm = load_normalization(Path(ctx.inputs.registries) / "normalization.yaml")
    return check_text(ctx.snapshot, norm.ascii_allowed)


def _conserve_gate(ctx: GateContext) -> GateResult:
    if ctx.src is None:
        return missing_input("G-CONSERVE", "the src layer it was built on (--dep)")
    return sourced.conserve_from_src(ctx.snapshot, ctx.src, Path(ctx.inputs.source_expect))


def _xcheck_gate(ctx: GateContext) -> GateResult:
    if ctx.inputs.pdf_dir is None:
        return missing_input("G-XCHECK", "the PDFs (--pdf-dir)")
    stored = (ctx.target.path / XCHECK_REPORT).read_bytes() \
        if XCHECK_REPORT in ctx.target.file_shas else None
    return sourced.xcheck_from_pdfs(ctx.snapshot, Path(ctx.inputs.pdf_dir), stored)


def _struct_gate(ctx: GateContext) -> GateResult:
    counter = ctx.inputs.token_counter
    if counter is None:
        try:
            counter = pinned_counter(ctx.inputs.tokenizer)
        except StageError as exc:
            return missing_input("G-STRUCT", f"the pinned BGE-M3 tokenizer ({exc})")
    return check_struct(ctx.snapshot, counter)


def _json_file(target: LayerData, name: str) -> Mapping[str, Any]:
    if name not in target.file_shas:
        raise GateInputError(f"{target.path}: an emb layer holds {name}")
    try:
        doc = json.loads((target.path / name).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateInputError(f"{target.path / name}: unreadable: {exc}") from None
    if not isinstance(doc, dict):
        raise GateInputError(f"{target.path / name}: not a JSON object")
    return MappingProxyType(doc)


def emb_context(target: LayerData, inputs: GateInputs) -> EmbContext:
    """The report, fingerprint and vectors of an emb layer, and the encoder to check them."""
    report, fp = _json_file(target, EMB_REPORT), _json_file(target, ENCODER_FINGERPRINT)
    try:
        found = vectors.decode_vectors(attach.read_attachment(target.path, vectors.NAME)[1])
        unread = None
    except StoreError as exc:
        found, unread = None, str(exc)
    encoder, error = inputs.encoder, None
    if encoder is None:
        try:
            encoder = load_encoder(inputs.tokenizer, inputs.reranker_tokenizer, inputs.device)
        except StageError as exc:
            error = str(exc)
    files = EmbFiles(report, None if found is None else found.matrix,
                     () if found is None else found.index, target.depends_on, unread)
    return EmbContext(files, StoredEncoding(fp, found), encoder, error)


def _no_encoder(name: str, ctx: GateContext) -> GateResult | None:
    if ctx.emb is not None and ctx.emb.encoder is not None:
        return None
    return missing_input(name, f"the pinned encoder ({ctx.emb.encoder_error if ctx.emb else ''})")


def _emb_gate(ctx: GateContext) -> GateResult:
    missing = _no_encoder("G-EMB", ctx)
    return missing or check_emb(ctx.snapshot, ctx.emb.files, ctx.emb.encoder.stats)


def _enc_gate(ctx: GateContext) -> GateResult:
    missing = _no_encoder("G-ENC", ctx)
    if missing:
        return missing
    options = EncOptions(Path(ctx.inputs.legacy_dir), ctx.inputs.compat_sample,
                         ctx.inputs.reencode_sample)
    return run_enc(ctx.snapshot.of("embedding_records"), ctx.emb.stored, ctx.emb.encoder,
                   options)


def stored_json(ctx: GateContext, name: str) -> Any | None:
    """A JSON document the layer's build stored beside its records (None if absent)."""
    if name not in ctx.target.file_shas:
        return None
    return json.loads((ctx.target.path / name).read_text(encoding="utf-8"))


def _kg0_gate(ctx: GateContext) -> GateResult:
    report = stored_json(ctx, KG0_REPORT)
    if report is None:
        return missing_input("G-KG0", f"the layer's {KG0_REPORT}")
    return check_kg0(ctx.snapshot, report, load_kg0_counts(ctx.inputs.kg0_counts),
                     ctx.target.depends_on)


def _event_gate(ctx: GateContext) -> GateResult:
    v1, v2 = stored_json(ctx, EVENT_REGISTRY_V1), stored_json(ctx, EVENT_REGISTRY_V2)
    if v1 is None or v2 is None:
        return missing_input("G-EVENT", f"the layer's {EVENT_REGISTRY_V1} and {EVENT_REGISTRY_V2}")
    path = Path(ctx.inputs.legacy_registry)
    legacy = path.read_bytes() if path.is_file() else None
    return check_event(ctx.snapshot, v1, v2, legacy, ctx.target.depends_on.get("struct", ""))


def _live(inputs: GateInputs, texts: list[str]) -> list[dict[str, Any]] | None:
    if inputs.live_probe is not None:
        return inputs.live_probe(texts)
    if not Path(inputs.backend_python).is_file():
        return None
    return k4_route.subprocess_probe(inputs.backend_python, inputs.backend_dir)(texts)


def _route_gate(ctx: GateContext) -> GateResult:
    report = stored_json(ctx, ROUTE_REPORT)
    if report is None or ROUTING_LEXICON not in ctx.target.file_shas:
        return missing_input("G-ROUTE", f"the layer's {ROUTING_LEXICON} and {ROUTE_REPORT}")
    frozen_path = Path(ctx.inputs.frozen_lexicon)
    frozen = frozen_path.read_bytes() if frozen_path.is_file() else None
    try:
        texts = k4_route.flatten(k4_route.probe_texts(ctx.snapshot, ctx.inputs.ground_truth))
        live = _live(ctx.inputs, texts)
    except StageError as exc:
        return missing_input("G-ROUTE", f"probe texts and live results ({exc})")
    return check_route(ctx.snapshot.of("routing_terms"), report["lexicon_rest"],
                       (ctx.target.path / ROUTING_LEXICON).read_bytes(), frozen, texts, live)


GATES: Mapping[str, Callable[[GateContext], GateResult]] = MappingProxyType({
    "G-SCHEMA": lambda ctx: ctx.schema,
    "G-COUNT": _count_gate,
    "G-REFINT": lambda ctx: check_refint(ctx.snapshot, ctx.layer),
    "G-TEXT": _text_gate,
    "G-REF": lambda ctx: check_ref(ctx.snapshot,
                                   ctx.inputs.versification or default_versification()),
    "G-CONSERVE": _conserve_gate,
    "G-XCHECK": _xcheck_gate,
    "G-STRUCT": _struct_gate,
    "G-EMB": _emb_gate,
    "G-ENC": _enc_gate,
    "G-KG0": _kg0_gate,
    "G-EVENT": _event_gate,
    "G-ROUTE": _route_gate,
    "G-PROV": lambda ctx: check_prov(dict(ctx.target.rows)),
})
SOURCED = frozenset({"G-CONSERVE", "G-XCHECK"})  # gates that re-read the sources


def implemented_gates(layer: str) -> tuple[str, ...]:
    """The required gates of ``layer`` that are built, in report order."""
    return tuple(name for name in REQUIRED_GATES[layer] if name in GATES)


def record_gates(layer: str) -> tuple[str, ...]:
    """The built gates of ``layer`` that read only the layers (no PDFs, no src)."""
    return tuple(name for name in implemented_gates(layer) if name not in SOURCED)


def not_implemented(name: str) -> GateResult:
    return GateResult(name, hard=True, passed=False, observed=NOT_IMPLEMENTED,
                      expected="implemented",
                      details=(f"{name} is required by design §8 but not built yet; "
                               "this layer cannot pass until it is",))


@dataclass(frozen=True)
class GateReport:
    layer: str
    layer_version: str
    depends_on: Mapping[str, str]
    gates: tuple[GateResult, ...]
    required: tuple[str, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        ran = {g.name for g in self.gates}
        return tuple(name for name in self.required if name not in ran)

    @property
    def passed(self) -> bool:
        return bool(self.gates) and bool(self.required) and not self.missing \
            and all(g.passed for g in self.gates if g.hard)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "layer": self.layer, "layer_version": self.layer_version,
                "depends_on": dict(self.depends_on), "pass": self.passed,
                "required_gates": list(self.required), "missing_gates": list(self.missing),
                "gates": [g.to_json() for g in self.gates]}


def _layer_of(path: Path | str) -> str | None:
    try:
        return json.loads((Path(path) / MANIFEST).read_text(encoding="utf-8")).get("layer")
    except (OSError, ValueError, AttributeError):
        return None  # read_layer reports the broken manifest


def _load_src(target: LayerData, given: Sequence[Path | str]) -> Mapping[str, bytes] | None:
    if not given:
        return None
    if len(given) > 1:
        raise GateInputError("the src layer may be given once")
    manifest, contents = verify_layer(given[0])
    if target.depends_on.get("src") != manifest["layer_version"]:
        raise GateInputError(f"{target.layer} was built on {target.depends_on.get('src')}, "
                             f"given {manifest['layer_version']}")
    return MappingProxyType(contents)


def _load_deps(target: LayerData, deps: Sequence[Path | str]
               ) -> tuple[list[LayerData], Mapping[str, bytes] | None]:
    src = [d for d in deps if _layer_of(d) in UNLOADED_DEPS]
    loaded = [read_layer(d) for d in deps if _layer_of(d) not in UNLOADED_DEPS]
    given = {d.layer: d.version for d in loaded}
    if len(given) != len(loaded):
        raise GateInputError("each dependency layer may be given once")
    required = set(REQUIRED_DEPS[target.layer])
    declared = {layer: v for layer, v in target.depends_on.items() if layer not in UNLOADED_DEPS}
    if not set(declared) <= set(LAYERS):
        raise GateInputError(f"{target.layer} declares dependencies "
                             f"{sorted(set(declared) - set(LAYERS))} that hold no records")
    if set(given) != required or set(declared) != required:
        raise GateInputError(f"{target.layer} needs dependencies {sorted(required)}; manifest "
                             f"declares {sorted(declared)}, given {sorted(given)}")
    for layer, version in given.items():
        if declared[layer] != version:
            raise GateInputError(f"{target.layer} was built on {declared[layer]}, given {version}")
    for dep in loaded:
        for layer, version in dep.depends_on.items():
            if layer in given and given[layer] != version:
                raise GateInputError(f"{dep.version} was built on {version}, given {given[layer]}")
    return loaded, _load_src(target, src)


def _check_layer_files(data: LayerData) -> None:
    for name in sorted(set(data.file_shas) - {DEPENDS_ON, *LAYER_REPORTS.get(data.layer, ())}):
        rtype = record_type_for_file(name)
        if rtype is None or rtype.layer != data.layer:
            owner = "no known layer" if rtype is None else f"the {rtype.layer} layer"
            raise GateInputError(f"{data.path}: {name} does not belong in a {data.layer} layer "
                                 f"(it belongs to {owner})")


def merge_files(layers: Sequence[LayerData]) -> dict[str, tuple[dict[str, Any], ...]]:
    """The ``.jsonl`` rows of ``layers`` by file name; each file must come from its own layer,
    so a layer can never stand in for the data of the layer it depends on."""
    files: dict[str, tuple[dict[str, Any], ...]] = {}
    for data in layers:
        _check_layer_files(data)
        for name, rows in data.rows.items():
            if name in files:
                raise GateInputError(f"{name} is given twice (again by {data.path})")
            files[name] = rows
    return files


def _gate_names(layer: str, gates: Sequence[str] | None) -> tuple[str, ...]:
    required = REQUIRED_GATES[layer]
    names = required if gates is None else tuple(gates)
    if not names or len(set(names)) != len(names) or not set(names) <= set(required):
        raise GateInputError(f"gates {list(names)} must be distinct gates of the {layer} layer "
                             f"{list(required)}")
    return names


def gate_layer(layer_dir: Path | str, layer: str, deps: Sequence[Path | str] = (),
               counts_path: Path | str = PDF_COUNTS_PATH,
               gates: Sequence[str] | None = None,
               inputs: GateInputs = GateInputs()) -> GateReport:
    """Verify, load and gate ``layer_dir`` with every required gate (or only ``gates``);
    raise GateInputError on a bad setup."""
    if layer not in LAYERS:
        raise GateInputError(f"no gates for layer {layer!r}")
    names = _gate_names(layer, gates)
    target = read_layer(layer_dir)
    if target.layer != layer:
        raise GateInputError(f"{layer_dir} holds a {target.layer} layer, not {layer}")
    record_deps, src = _load_deps(target, deps)
    loaded = [*record_deps, target]
    schema, snapshot = check_schema(merge_files(loaded), [d.layer for d in loaded])
    emb = emb_context(target, inputs) if layer == "emb" else None
    ctx = GateContext(layer, schema, snapshot, counts_path, target, src, inputs, emb)
    results = tuple(GATES[n](ctx) if n in GATES else not_implemented(n) for n in names)
    return GateReport(layer, target.version, target.depends_on, results, REQUIRED_GATES[layer])
