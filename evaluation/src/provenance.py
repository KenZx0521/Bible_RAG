"""What a run scored and where its answers came from: recorded in every result's meta.

* ``data_build_id``: the backend's /api/v1/health ``build_id``. A backend that
  reports none serves the legacy build, ``legacy-20261004``. A contracts
  directory given on the CLI names the build instead (its manifest); a health
  report naming another build is refused.
* ``gt_version`` / ``gt_sha``: the ground truth the run scored with.
* ``encoder_fingerprint``: the health report's ``encoder`` (null when it has
  none, or none initialised).

A full-pipeline checkpoint keeps the backend's part in run_meta.json beside
raw_responses.json; a checkpoint without one predates the record and came
from the legacy build. Any build other than legacy-20261004 is scored only
against the frozen GT v2, whose ruler (slot_coverage) every run then carries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import httpx
from ragcommon import ids

from .config import settings
from .data_loader import GroundTruthSet
from .slot_coverage import SlotRuler, build_ruler

LEGACY_BUILD_ID = ids.LEGACY_BUILD_ID
RUN_META = "run_meta.json"


class ProvenanceError(ValueError):
    """A build id or contracts directory that does not add up, or a GT the build may not use."""


@dataclass(frozen=True)
class Provenance:
    data_build_id: str
    encoder_fingerprint: Mapping[str, Any] | None = None

    def meta(self) -> dict[str, Any]:
        encoder = None if self.encoder_fingerprint is None else dict(self.encoder_fingerprint)
        return {"data_build_id": self.data_build_id, "encoder_fingerprint": encoder}


def _build_id(value: object) -> str:
    try:
        return ids.validate(value, "build").raw
    except ids.IdError as exc:
        raise ProvenanceError(f"not a build id: {exc}") from None


def from_health(health: Mapping[str, Any]) -> Provenance:
    """Provenance from a /api/v1/health body (legacy backends report no build_id)."""
    raw = health.get("build_id")
    build_id = LEGACY_BUILD_ID if raw is None else _build_id(raw)
    encoder = health.get("encoder")
    if not isinstance(encoder, Mapping) or all(v is None for v in encoder.values()):
        encoder = None
    return Provenance(build_id, None if encoder is None else MappingProxyType(dict(encoder)))


def fetch_health(backend_url: str) -> dict[str, Any]:
    response = httpx.get(f"{backend_url}/api/v1/health", timeout=30.0)
    response.raise_for_status()
    return response.json()


def write_run_meta(directory: Path, provenance: Provenance) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RUN_META).write_text(json.dumps(provenance.meta(), ensure_ascii=False, indent=2),
                                      encoding="utf-8")


def read_run_meta(directory: Path) -> Provenance:
    """The provenance a checkpoint directory recorded (legacy when it predates the record)."""
    path = directory / RUN_META
    if not path.exists():
        return Provenance(LEGACY_BUILD_ID)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read {path}: {exc}") from None
    return from_health({"build_id": data.get("data_build_id"),
                        "encoder": data.get("encoder_fingerprint")})


@dataclass(frozen=True)
class RunContext:
    gt: GroundTruthSet
    provenance: Provenance
    ruler: SlotRuler | None      # GT v2 only

    def meta(self) -> dict[str, Any]:
        prov = self.provenance.meta()
        return {"data_build_id": prov["data_build_id"], **self.gt.meta(),
                "encoder_fingerprint": prov["encoder_fingerprint"]}


def _contracts(provenance: Provenance, contracts_dir: Path | None) -> tuple[Provenance, Path | None]:
    if contracts_dir is None:
        build_id = provenance.data_build_id
        default = None if build_id == LEGACY_BUILD_ID else settings.rag_store / "contracts" / build_id
        return provenance, default
    path = contracts_dir / "manifest.json"
    try:
        named = _build_id(json.loads(path.read_text(encoding="utf-8")).get("build_id"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read {path}: {exc}") from None
    reported = provenance.data_build_id
    if reported not in (LEGACY_BUILD_ID, named):
        raise ProvenanceError(f"/health reports build {reported}, {contracts_dir} holds {named}")
    return replace(provenance, data_build_id=named), contracts_dir


def make_context(gt: GroundTruthSet, provenance: Provenance,
                 contracts_dir: Path | None = None) -> RunContext:
    """Bind the GT, the build and its ruler; refuse a new build scored against GT v1."""
    provenance, directory = _contracts(provenance, contracts_dir)
    if provenance.data_build_id != LEGACY_BUILD_ID and gt.version != "v2":
        raise ProvenanceError(f"build {provenance.data_build_id} is scored only against the "
                              "frozen GT v2 (--gt v2)")
    ruler = (build_ruler(gt.slot_universe, provenance.data_build_id, directory)
             if gt.version == "v2" else None)
    return RunContext(gt, provenance, ruler)
