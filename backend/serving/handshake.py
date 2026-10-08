"""The handshake checks (design §7.8): the stores and the contract against the build row.

Each check takes what was observed and returns its mismatches as sentences; none
raises and none repairs. ``serving.startup`` gathers them: any mismatch makes
/api/v1/health answer 503, and with STRICT_BUILD_CHECK the startup fails. There is
no image-digest check (rag_meta.serving only records the digest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from serving.build import Build

FINGERPRINT_KEYS = ("tokenizer_sha", "probe_ids_sha", "unk_count", "pair_template_ok")
ENCODERS = ("bge_m3", "reranker")


@dataclass(frozen=True)
class Handshake:
    build_id: str | None
    mismatches: tuple[str, ...]
    strict: bool

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_json(self) -> dict[str, Any]:
        return {"build_id": self.build_id, "ok": self.ok, "strict": self.strict,
                "mismatches": list(self.mismatches)}


def check_pg(build: Build, build_info_ids: Sequence[str]) -> list[str]:
    where = f"postgres: {build.pg_schema}.build_info"
    if not build_info_ids:
        return [f"{where}: no build_info row"]
    if len(build_info_ids) > 1:
        return [f"{where}: {len(build_info_ids)} build_info rows"]
    if build_info_ids[0] != build.build_id:
        return [f"{where} names {build_info_ids[0]}, not {build.build_id}"]
    return []


def check_qdrant(build: Build, exists: bool, count: int | None) -> list[str]:
    if not exists:
        return [f"qdrant: collection {build.qdrant_collection} does not exist"]
    if count != build.points:
        return [f"qdrant: {build.qdrant_collection} holds {count} points, "
                f"rag_meta.builds says {build.points}"]
    return []


def check_manifest(build: Build, manifest: Mapping[str, Any]) -> list[str]:
    expected = {"pg_schema": build.pg_schema, "qdrant_collection": build.qdrant_collection,
                "points": build.points}
    return [f"contracts: manifest {key} is {manifest.get(key)!r}, rag_meta.builds says {value!r}"
            for key, value in expected.items() if manifest.get(key) != value]


def check_kg(build: Build, manifest: Mapping[str, Any]) -> list[str]:
    """This backend has no KG: a build that enables it cannot be served (D-09)."""
    flags = {"rag_meta.builds": build.kg_enabled}
    if "kg_enabled" in manifest:
        flags["manifest"] = manifest["kg_enabled"]
    return [f"kg: {where} kg_enabled={flag!r}, this backend serves only kg_enabled=false"
            for where, flag in flags.items() if flag is not False]


def _fingerprint(name: str, contract: Any, runtime: Any) -> list[str]:
    if not isinstance(contract, Mapping):
        return [f"encoder: the contract has no {name} fingerprint"]
    if not isinstance(runtime, Mapping):
        return [f"encoder: {name} has no runtime fingerprint (not loaded)"]
    return [f"encoder: {name} {key} {runtime.get(key)!r} != contract {contract.get(key)!r}"
            for key in FINGERPRINT_KEYS if runtime.get(key) != contract.get(key)]


def check_encoders(contract: Mapping[str, Any], runtime: Mapping[str, Any]) -> list[str]:
    """The startup probes of BGE-M3 and the reranker against the contract fingerprint."""
    return [p for name in ENCODERS for p in _fingerprint(name, contract.get(name), runtime.get(name))]
