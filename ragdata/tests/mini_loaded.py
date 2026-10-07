"""The mini release loaded into a FakePg, an in-memory Qdrant and a contract directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient

import mini_release
from fake_pg import FakePg
from ragdata.loader import load as loader
from ragdata.loader.qdrant import QdrantDb
from ragdata.loader.verify import VerifyInputs, verify
from ragdata.release import assemble as rel

DATE = "20261008"


@dataclass
class Loaded:
    mini: mini_release.MiniRelease
    release: rel.Release
    pg: FakePg
    qdrant: QdrantDb
    contracts: Path
    report: dict

    @property
    def targets(self) -> loader.Targets:
        return loader.targets(self.release.build_id, self.contracts)

    def inputs(self, **changes) -> VerifyInputs:
        fields = {"gt": self.mini.gt, "freeze": self.mini.freeze,
                  "encoder": mini_release.encoder(), "sample": 5}
        return VerifyInputs(**{**fields, **changes})

    def verify(self, **changes):
        return verify(self.release, self.pg, self.qdrant, self.contracts, self.inputs(**changes))


def assembled(mini: mini_release.MiniRelease) -> rel.Release:
    path = rel.write_release(rel.assemble(mini.store, mini.top, DATE, mini.checks),
                             mini.root / "releases")
    return rel.read_release(path, mini.store, mini.checks)


def load(root: Path, mini: mini_release.MiniRelease | None = None) -> Loaded:
    mini = mini or mini_release.build(root / "mini")
    release = assembled(mini)
    pg, qdrant = FakePg(), QdrantDb(QdrantClient(location=":memory:"))
    contracts = root / "contracts"
    report = loader.load(release, pg, qdrant, contracts)
    return Loaded(mini, release, pg, qdrant, contracts, report)


def red(report) -> set[str]:
    return {g.name for g in report.gates if g.hard and not g.passed}
