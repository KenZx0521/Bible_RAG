"""``ragdata pipeline run`` over the mini snapshot.

The mini snapshot has no PDFs, so its text step writes the hand-built text layer and is
gated with the gates a stored layer can run without them. Every later step is the real
``steps.layer_steps`` with the mini inputs: the legacy output/ (struct's old pericopes and
chunks, emb's old vectors), the stand-in token counter and encoder, the mini registries
(with query_aliases.yaml) and event registry (``mini_release.build`` lays those out).
The derived files are mini ones naming the mini text and struct layers; G-GT is a
stand-in (the mini GT v2 holds only slots). Load and verify go to a FakePg, an in-memory
Qdrant and a contract directory under ``root``.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from qdrant_client import QdrantClient

import fake_encoder
import mini_build
import mini_emb
import mini_kg
import mini_release
import mini_route
import ref_dirs
from fake_pg import FakePg
from ragdata import paths
from ragdata.gates.base import GateResult
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.gt.gate import GtReport
from ragdata.loader.qdrant import QdrantDb
from ragdata.loader.verify import VerifyInputs, verify
from ragdata.pipeline import derived
from ragdata.pipeline.cli import load_once, release_step
from ragdata.pipeline.run import Databases, Pipeline
from ragdata.pipeline.steps import Sources, Step, layer_steps
from ragdata.release.gating import ReleaseChecks, release_gates
from ragdata.stages.result import BuildResult
from ragdata.stages.s05_struct.build import StructInputs, build_struct
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.store import encode_jsonl, write_layer

DATE = "20261008"
COUNTER = TokenCounter(mini_build.count_tokens, {"tokenizer": "mini"})
PASS = GateResult("G-MINI", True, True, {}, {}, ())


def _legacy(root: Path) -> Path:
    directory = mini_emb.legacy_dir(root)
    for name, rows in (("pericopes.jsonl", mini_build.legacy_pericopes()),
                       ("chunks.jsonl", mini_build.legacy_chunks())):
        (directory / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                              for r in rows), encoding="utf-8")
    return ref_dirs.sign(directory)


def text_files() -> dict[str, bytes]:
    return {f"{name}.jsonl": encode_jsonl(rows) for name, rows in mini_build.text_layer().items()}


def text_step(store: Path, sources: Sources, full_gates: bool = False) -> Step:
    """Writes the mini text layer; gated with the record gates (all required: ``full_gates``,
    which then miss G-CONSERVE and G-XCHECK)."""
    def build(built):
        layer = write_layer(store, "text", text_files(), exist_ok=True)
        return BuildResult({"text": layer}, (PASS,), {})

    def gate(built):
        names = release_gates("text")
        report = gate_layer(built["text"].path, "text", [], sources.counts, gates=names,
                            inputs=sources.gate)
        return report if full_gates else dataclasses.replace(report, required=names)
    return Step("text", build, gate)


@dataclass
class Mini:
    root: Path
    sources: Sources
    files: derived.DerivedFiles
    text_version: str
    struct_version: str
    pg: FakePg
    qdrant: QdrantDb

    @property
    def contracts(self) -> Path:
        return self.root / "contracts"

    @property
    def releases(self) -> Path:
        return self.root / "releases"

    def verify_inputs(self, **changes: Any) -> VerifyInputs:
        return VerifyInputs(**{"gt": self.files.gt, "freeze": self.files.freeze,
                               "encoder": fake_encoder.make(), "sample": 5, **changes})

    def databases(self, load: bool = True, verify_inputs: VerifyInputs | None = None,
                  connect: Callable[[], tuple[Any, Any]] | None = None) -> Databases:
        inputs = verify_inputs or self.verify_inputs()
        return Databases(connect or (lambda: (self.pg, self.qdrant)),
                         load_once(self.contracts) if load else None,
                         lambda r, pg, q: verify(r, pg, q, self.contracts, inputs))

    def pipeline(self, store: str = "store", gt: Callable | None = None,
                 sources: Sources | None = None, databases: Databases | None = None,
                 text: Step | None = None) -> Pipeline:
        store_dir, sources = self.root / store, sources or self.sources
        steps = (text or text_step(store_dir, sources), *layer_steps(store_dir, sources)[1:])
        checks = ReleaseChecks(sources.counts, sources.gate)
        return Pipeline(store_dir, steps, self.files,
                        gt or (lambda built: GtReport(built["text"].version, (PASS,))),
                        release_step(store_dir, self.releases, DATE, checks),
                        databases if databases is not None else self.databases())


def _struct_version(root: Path, legacy: Path) -> tuple[str, str]:
    text = write_layer(root / "scratch", "text", text_files())
    result = build_struct(text.path, root / "scratch", mini_release.MINI_COUNTS,
                          StructInputs(legacy_dir=legacy, counter=COUNTER))
    return text.version, result.layers["struct"].version


def _files(root: Path, text: str, struct: str) -> derived.DerivedFiles:
    versions = mini_kg.write_registries(root / "registries")
    mini_route.write_query_aliases(root / "registries")
    shutil.copy(paths.REGISTRIES / "normalization.yaml", root / "registries")  # G-TEXT
    kg0 = root / "kg0_counts.yaml"
    kg0.write_bytes(mini_kg.dump(mini_kg.kg0_counts(versions, text, struct)))
    grid = root / "versification.json"
    grid.write_text(json.dumps({"source": {"layer_version": text}}), encoding="utf-8")
    gt, freeze = mini_release.write_gt(root, text)
    return derived.DerivedFiles(versification=grid, kg0_counts=kg0, gt=gt, freeze=freeze,
                                gt_changes=root / "changes.jsonl")


def make(root: Path) -> Mini:
    ref = root / "ref"
    mini_release.build(ref)
    legacy = _legacy(root / "legacy")
    text, struct = _struct_version(root, legacy)
    files = _files(root, text, struct)
    gate = GateInputs(versification=mini_build.versification(), token_counter=COUNTER,
                      legacy_dir=legacy, compat_sample=mini_emb.SAMPLE, encoder=fake_encoder.make(),
                      registries=root / "registries", kg0_counts=files.kg0_counts)
    sources = Sources(gate=gate, counts=mini_release.MINI_COUNTS, events_yaml=ref / "events.yaml")
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    pg.close = qdrant.close = lambda: None
    return Mini(root, sources, files, text, struct, pg, qdrant)

