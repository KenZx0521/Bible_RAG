"""Every mini layer a release names, built into one store, plus a mini GT v2 and its freeze.

``build(root)`` writes text and struct (mini_build), emb (stand-in encoder), kg0, events and
route (mini_kg and mini_route registries) into ``root/store`` and returns them by layer.
The mini text layer has no src layer under it, so a mini release names no src.
``MiniRelease.checks`` gates the mini layers when a release is assembled: the mini counts,
grid, token counts, registries and the stand-in encoder.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import fake_encoder
import mini_build
import mini_emb
import mini_kg
import mini_route
from ragdata import paths
from ragdata.kg import k0_build, k1_build, k4_build
from ragdata.gates.runner import GateInputs
from ragdata.release.gating import ReleaseChecks
from ragdata.stages.s05_struct.tokens import TokenCounter
from ragdata.stages.s06_emb.build import build_emb
from ragdata.store import StoredLayer

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
TOP = ("emb", "kg0", "events", "route")
GT_GOLD = {"Q1": ["mat.18.1", "mat.18.2", "mat.18.4"], "Q2": ["eph.6.2", "eph.6.3"]}
GT_OMITTED = {"Q1": ["mat.18.3"], "Q2": []}


@dataclass(frozen=True)
class MiniRelease:
    root: Path
    store: Path
    layers: Mapping[str, StoredLayer]
    gt: Path
    freeze: Path

    @property
    def top(self) -> list[str]:
        return [self.layers[name].version for name in TOP]

    @property
    def checks(self) -> ReleaseChecks:
        inputs = GateInputs(versification=mini_build.versification(),
                            token_counter=TokenCounter(mini_build.count_tokens, {}),
                            registries=self.root / "registries",
                            kg0_counts=self.root / "kg0_counts.yaml", encoder=encoder())
        return ReleaseChecks(MINI_COUNTS, inputs)


def _built(result, layer: str) -> StoredLayer:
    if not result.passed:
        raise AssertionError([g.to_json() for g in result.gates if not g.passed])
    return result.layers[layer]


def _kg0(root: Path, store: Path, text: StoredLayer, struct: StoredLayer) -> StoredLayer:
    versions = mini_kg.write_registries(root / "registries")
    counts = root / "kg0_counts.yaml"
    counts.write_bytes(mini_kg.dump(mini_kg.kg0_counts(versions, text.version, struct.version)))
    return _built(k0_build.build_kg0(text.path, struct.path, store, root / "registries",
                                     counts), "kg0")


def _events(root: Path, store: Path, text: StoredLayer, struct: StoredLayer) -> StoredLayer:
    events_yaml = mini_kg.write_events_yaml(root / "events.yaml")
    return _built(k1_build.build_events(text.path, struct.path, store, events_yaml,
                                        MINI_COUNTS), "events")


def _route(root: Path, store: Path, layers: Mapping[str, StoredLayer]) -> StoredLayer:
    """K4 over the mini layers, with the mini registries plus query_aliases.yaml (and the
    repo's normalization.yaml beside them: the release gates G-TEXT with that directory)."""
    mini_route.write_query_aliases(root / "registries")
    shutil.copy(paths.REGISTRIES / "normalization.yaml", root / "registries")
    return _built(k4_build.build_route(layers["text"].path, layers["kg0"].path,
                                       layers["events"].path, store, root / "registries",
                                       MINI_COUNTS), "route")


def write_gt(root: Path, slot_universe: str, gold=GT_GOLD, omitted=GT_OMITTED) -> tuple[Path, Path]:
    """A GT v2 shaped file over the mini slots and the freeze record naming its sha256."""
    questions = [{"question_id": qid, "gold_slots": gold[qid], "omitted_slots": omitted[qid]}
                 for qid in gold]
    data = json.dumps({"metadata": {"gt_version": "v2", "slot_universe": slot_universe},
                       "questions": questions}, ensure_ascii=False).encode("utf-8")
    gt, freeze = root / "ground_truth.v2.json", root / "gt_v2_freeze.json"
    gt.write_bytes(data)
    freeze.write_text(json.dumps({"sha256": hashlib.sha256(data).hexdigest(),
                                  "slot_universe": slot_universe}), encoding="utf-8")
    return gt, freeze


def build(root: Path) -> MiniRelease:
    root.mkdir(parents=True, exist_ok=True)
    store = root / "store"
    text, struct = mini_build.write_layers(store)
    emb = _built(build_emb(struct.path, text.path, store, counts_path=MINI_COUNTS,
                           inputs=mini_emb.inputs(root)), "emb")
    layers = {"text": text, "struct": struct, "emb": emb,
              "kg0": _kg0(root, store, text, struct), "events": _events(root, store, text, struct)}
    layers["route"] = _route(root, store, layers)
    gt, freeze = write_gt(root, text.version)
    return MiniRelease(root, store, layers, gt, freeze)


def encoder():
    """The stand-in encoder the mini emb layer was encoded with."""
    return fake_encoder.make()


PYTHON = Path(sys.executable)
