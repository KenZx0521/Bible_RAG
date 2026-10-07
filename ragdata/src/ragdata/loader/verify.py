"""S14: G-PROJ (design §7.7) and G-SCHEMA's PG part over a loaded build. Read-only.

Everything is read back from PG, Qdrant and the contract directory and compared
with the release's snapshot (its layers, verified by the store):

- C1 build_id: ``build_info`` (one row), ``rag_meta.builds`` (with the release
  file's sha, schema and collection), the collection name, every point's payload
  and the contract ``manifest.json`` all name the release's build;
- C2 ids: every table's id set equals the snapshot's, and the Qdrant points are
  exactly the embedding records (point id ``uuid5(record_id)``);
- C3 fields: every row and every payload hashes (normalized, ``projection``) to
  its snapshot record, but for the fields ``projection_exempt_fields.yaml`` lists;
- C4 vectors: each point's ``text_sha`` is PG's, its vector the attachment's row
  (cos >= 0.99999), and 200 records sampled with a fixed seed, encoded again from
  PG's text by the pinned encoder, give their point's vector back (cos >= 0.99999);
- C5 contracts: the directory holds exactly the release's contract files (by
  sha) and its manifest; every event anchor's passage and slots are in PG and its
  passage in Qdrant; every routing term carries provenance and a source;
- C6 GT: the frozen GT v2 (sha and slot universe as its freeze record says, the
  universe being the release's text layer) has its gold slots among PG's present
  or merged slots and its omitted slots among the omitted ones;
- G-SCHEMA.pg: every table has its primary key, unique and foreign key constraints.
C7 (roles) is not built: this setup has one database role (精簡版).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ragcommon import ids
from ragdata import paths
from ragdata.gates.base import GateResult, capped
from ragdata.gates.vectors import DET_COS, query_rows, rowwise_cos
from ragdata.loader import projection as proj_mod
from ragdata.loader.contracts_emit import MANIFEST, read_contracts
from ragdata.loader.load import Targets, read_vectors, record_files, targets
from ragdata.loader.plan import Point
from ragdata.loader.sql import unique_name
from ragdata.loader.tables import BUILD_INFO, TABLES, Table
from ragdata.release.assemble import Release
from ragdata.stages.errors import StageError
from ragdata.stages.s06_emb.encoder import Encoder, encode_texts, load_encoder
from ragdata.store.cas import sha256_bytes

REPORT_SCHEMA = "ragdata.projection_report.v1"
REENCODE = 200
GOLD_STATUS = frozenset({"present", "merged"})
Files = Mapping[str, Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class VerifyInputs:
    gt: Path = paths.GT_V2
    freeze: Path = paths.GT_V2_FREEZE
    exempt: Path = proj_mod.EXEMPT_PATH
    sample: int = REENCODE
    encoder: Encoder | None = None       # None: the pinned BGE-M3 (``device``, ``tokenizer``)
    device: str | None = None
    tokenizer: Path | None = None


@dataclass(frozen=True)
class Projection:
    """What the build's targets hold, read back."""

    tables: Mapping[str, list[dict[str, Any]]]     # by table; a missing schema holds none
    build_row: Mapping[str, Any] | None
    constraints: frozenset[tuple[str, str, str]]
    collection: bool
    points: tuple[Point, ...]
    contracts: Mapping[str, bytes] | None


@dataclass(frozen=True)
class ProjectionReport:
    build_id: str
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates if g.hard)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "build_id": self.build_id, "pass": self.passed,
                "gates": [g.to_json() for g in self.gates]}


def read_projection(t: Targets, pg: Any, qdrant: Any) -> Projection:
    schema = pg.schema_exists(t.schema)
    tables = {tb.name: pg.fetch(t.schema, tb) for tb in (*TABLES, BUILD_INFO)} if schema else {}
    collection = qdrant.exists(t.collection)
    return Projection(tables, pg.build_row(t.build_id),
                      frozenset(pg.constraints(t.schema)) if schema else frozenset(),
                      collection, tuple(qdrant.points(t.collection)) if collection else (),
                      read_contracts(t.contracts_dir))


def _gate(name: str, violations: Sequence[str], observed: Mapping[str, Any]) -> GateResult:
    return GateResult(name, hard=True, passed=not violations,
                      observed={**observed, "violations": len(violations)},
                      expected={"violations": 0}, details=capped(list(violations)))


def _manifest(proj: Projection) -> Mapping[str, Any]:
    raw = (proj.contracts or {}).get(MANIFEST)
    try:
        doc = json.loads(raw) if raw else {}
    except ValueError:
        doc = {}
    return doc if isinstance(doc, dict) else {}


def check_c1(release: Release, t: Targets, proj: Projection) -> GateResult:
    bid, out = release.build_id, []
    info = [r["build_id"] for r in proj.tables.get("build_info", [])]
    out += [] if info == [bid] else [f"build_info holds {info}, expected [{bid}]"]
    want = {"build_id": bid, "manifest_sha": sha256_bytes(release.data), "pg_schema": t.schema,
            "qdrant_collection": t.collection}
    row = proj.build_row or {}
    out += [f"rag_meta.builds {k} is {row.get(k)!r}, expected {v!r}" for k, v in want.items()
            if row.get(k) != v]
    out += [] if proj.collection else [f"no Qdrant collection {t.collection}"]
    wrong = [p.payload.get("record_id") for p in proj.points if p.payload.get("build_id") != bid]
    out += [f"payload build_id of {r} is not {bid}" for r in wrong]
    found = _manifest(proj).get("build_id")
    out += [] if found == bid else [f"contracts manifest.json names {found!r}, expected {bid}"]
    return _gate("G-PROJ.C1", out, {"build_id": bid, "points_checked": len(proj.points)})


def expected_rows(table: Table, files: Files) -> dict[str, Mapping[str, Any]]:
    rows = files[f"{table.source}.jsonl"] if table.source else table.rows(files)
    return {table.row_id(r): r for r in rows}


def _payloads(proj: Projection) -> dict[str, Mapping[str, Any]]:
    return {str(p.payload.get("record_id")): p.payload for p in proj.points}


def check_c2(files: Files, proj: Projection) -> GateResult:
    out, counts = [], {}
    for table in TABLES:
        found = [table.row_id(r) for r in proj.tables.get(table.name, [])]
        counts[table.name] = len(found)
        out += proj_mod.id_violations(table.name, expected_rows(table, files), found)
    records = [r["record_id"] for r in files["embedding_records.jsonl"]]
    out += proj_mod.id_violations("qdrant", records,
                                  [str(p.payload.get("record_id")) for p in proj.points])
    out += [f"qdrant point {p.id} is not uuid5 of {p.payload.get('record_id')}"
            for p in proj.points if not _uuid_of(p)]
    return _gate("G-PROJ.C2", out, {"rows": counts, "points": len(proj.points)})


def _uuid_of(point: Point) -> bool:
    record = point.payload.get("record_id")
    return isinstance(record, str) and ids.is_valid(record) and point.id == ids.point_id(record)


def check_c3(files: Files, proj: Projection, exempt: Mapping[str, Mapping[str, Any]]
             ) -> GateResult:
    out, pg_exempt = [], exempt.get("pg", {})
    for table in TABLES:
        found = {table.row_id(r): r for r in proj.tables.get(table.name, [])}
        out += proj_mod.row_violations(table.name, expected_rows(table, files), found,
                                       pg_exempt.get(table.name, proj_mod.NONE))
    payloads = {r["record_id"]: r["payload"] for r in files["embedding_records.jsonl"]}
    out += proj_mod.row_violations("qdrant payload", payloads, _payloads(proj),
                                   exempt.get("qdrant", {}).get("payload", proj_mod.NONE))
    return _gate("G-PROJ.C3", out, {"tables": len(TABLES) + 1})


def _encoder(inputs: VerifyInputs) -> tuple[Encoder | None, str | None]:
    if inputs.encoder is not None:
        return inputs.encoder, None
    try:
        return load_encoder(inputs.tokenizer, device=inputs.device), None
    except StageError as exc:
        return None, str(exc)


def _reencode(records: Sequence[Mapping[str, Any]], pg_text: Mapping[str, str],
              by_record: Mapping[str, Point], encoder: Encoder, sample: int
              ) -> tuple[list[str], dict[str, Any]]:
    picked = [records[i]["record_id"] for i in query_rows(len(records), sample)]
    present = [r for r in picked if r in by_record and r in pg_text]
    if not present:
        return ["no sampled record is in both PG and Qdrant"], {"reencoded": 0}
    fresh = encode_texts(encoder, [pg_text[r] for r in present])
    cos = rowwise_cos(fresh, np.stack([by_record[r].vector for r in present]))
    out = [f"re-encoded {r}: cos {c:.7f} < {DET_COS}" for r, c in zip(present, cos) if c < DET_COS]
    return out, {"reencoded": len(present), "min_cos": float(cos.min())}


def _stored_vector_violations(records: Sequence[Mapping[str, Any]],
                               by_record: Mapping[str, Point], matrix: np.ndarray) -> list[str]:
    """Each point's vector is its record's row of the vectors attachment."""
    rows = [(i, r["record_id"]) for i, r in enumerate(records) if r["record_id"] in by_record]
    if not rows:
        return []
    stored = matrix[[i for i, _ in rows]]
    cos = rowwise_cos(stored, np.stack([by_record[r].vector for _, r in rows]))
    return [f"{r}: point vector is not the layer's (cos {c:.7f})"
            for (_, r), c in zip(rows, cos) if c < DET_COS]


def check_c4(files: Files, proj: Projection, matrix: np.ndarray, inputs: VerifyInputs
             ) -> GateResult:
    records = files["embedding_records.jsonl"]
    pg_rows = {r["record_id"]: r for r in proj.tables.get("embedding_records", [])}
    by_record = {str(p.payload.get("record_id")): p for p in proj.points}
    out = [f"{r}: payload text_sha is not PG's" for r, p in sorted(by_record.items())
           if pg_rows.get(r, {}).get("text_sha") != p.payload.get("text_sha")]
    out += _stored_vector_violations(records, by_record, matrix)
    encoder, error = _encoder(inputs)
    if encoder is None:
        return _gate("G-PROJ.C4", [*out, f"no pinned encoder: {error}"], {"reencoded": 0})
    more, observed = _reencode(records, {r: row["text"] for r, row in pg_rows.items()},
                               by_record, encoder, inputs.sample)
    return _gate("G-PROJ.C4", out + more, {"points": len(by_record), **observed})


def _anchor_violations(registry: Mapping[str, Any], proj: Projection) -> list[str]:
    passages = {r["passage_id"] for r in proj.tables.get("passages", [])}
    slots = {r["slot_key"] for r in proj.tables.get("verse_slots", [])}
    in_qdrant = {p.payload.get("passage_id") for p in proj.points
                 if p.payload.get("kind") in ("passage", "chunk")}
    out = []
    for event in registry.get("events", []):
        for a in event.get("anchors", []):
            where = f"event {event.get('event_id')} anchor {a.get('passage_id')}"
            out += [f"{where}: passage not in PG"] if a.get("passage_id") not in passages else []
            out += [f"{where}: passage not in Qdrant"] if a.get("passage_id") not in in_qdrant \
                else []
            out += [f"{where}: slot {s} not in PG" for s in (a.get("start_slot"),
                                                             a.get("end_slot")) if s not in slots]
    return out


def _lexicon_violations(lexicon: Mapping[str, Any]) -> list[str]:
    return [f"routing_lexicon.json {category}[{i}]: no provenance_class/source"
            for category in ("persons", "places", "events", "books")
            for i, entry in enumerate(lexicon.get(category, []))
            if not (isinstance(entry, dict) and entry.get("provenance_class")
                    and entry.get("source"))]


def _json_contract(contracts: Mapping[str, bytes], name: str) -> Mapping[str, Any]:
    try:
        doc = json.loads(contracts.get(name, b"{}"))
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def check_c5(release: Release, proj: Projection) -> GateResult:
    contracts = proj.contracts
    if contracts is None:
        return _gate("G-PROJ.C5", ["no contract directory"], {})
    want = dict(release.doc["contracts"])
    out = [f"contract files {sorted(set(contracts) ^ {*want, MANIFEST})} differ from the release"
           ] if set(contracts) != {*want, MANIFEST} else []
    out += [f"{name}: sha256 is not the release's" for name in sorted(want)
            if name in contracts and sha256_bytes(contracts[name]) != want[name]]
    if _manifest(proj).get("files") != want:
        out.append("manifest.json files are not the release's contract shas")
    out += _anchor_violations(_json_contract(contracts, "event_registry.json"), proj)
    out += _lexicon_violations(_json_contract(contracts, "routing_lexicon.json"))
    return _gate("G-PROJ.C5", out, {"files": len(contracts)})


def _gt(inputs: VerifyInputs, text_version: str) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        data = Path(inputs.gt).read_bytes()
        freeze = json.loads(Path(inputs.freeze).read_text(encoding="utf-8"))
        doc = json.loads(data)
    except (OSError, ValueError) as exc:
        return [], [f"GT v2 or its freeze record unreadable: {exc}"]
    universe = doc.get("metadata", {}).get("slot_universe")
    out = [] if hashlib.sha256(data).hexdigest() == freeze.get("sha256") else [
        f"{inputs.gt} is not the frozen GT v2 ({freeze.get('sha256')})"]
    out += [] if universe == freeze.get("slot_universe") == text_version else [
        f"GT slot_universe {universe} / freeze {freeze.get('slot_universe')} is not the "
        f"release's text layer {text_version}"]
    return list(doc.get("questions", [])), out


def check_c6(release: Release, proj: Projection, inputs: VerifyInputs) -> GateResult:
    questions, out = _gt(inputs, release.doc["layers"]["text"])
    status = {r["slot_key"]: r["status"] for r in proj.tables.get("verse_slots", [])}
    gold = omitted = 0
    for q in questions:
        for slot in q.get("gold_slots", []):
            gold += 1
            if status.get(slot) not in GOLD_STATUS:
                out.append(f"{q.get('question_id')}: gold slot {slot} is {status.get(slot)}")
        for slot in q.get("omitted_slots", []):
            omitted += 1
            if status.get(slot) != "omitted_variant":
                out.append(f"{q.get('question_id')}: omitted slot {slot} is {status.get(slot)}")
    return _gate("G-PROJ.C6", out, {"questions": len(questions), "gold_slots": gold,
                                    "omitted_slots": omitted})


def check_pg_schema(proj: Projection) -> GateResult:
    want = set()
    for table in (*TABLES, BUILD_INFO):
        want.add((table.name, f"pk_{table.name}", "p"))
        want |= {(table.name, unique_name(table, u), "u") for u in table.unique}
        want |= {(table.name, key.name(table.name), "f") for key in table.fks}
    missing = sorted(want - set(proj.constraints))
    return _gate("G-SCHEMA.pg", [f"{t}: no constraint {n} ({k})" for t, n, k in missing],
                 {"constraints": len(want)})


def verify(release: Release, pg: Any, qdrant: Any, contracts_root: Path = paths.CONTRACTS,
           inputs: VerifyInputs = VerifyInputs()) -> ProjectionReport:
    t = targets(release.build_id, contracts_root)
    files = record_files(release)
    proj = read_projection(t, pg, qdrant)
    matrix = read_vectors(release, files).found.matrix
    exempt = proj_mod.load_exempt(inputs.exempt)
    gates = (check_pg_schema(proj), check_c1(release, t, proj), check_c2(files, proj),
             check_c3(files, proj, exempt), check_c4(files, proj, matrix, inputs),
             check_c5(release, proj), check_c6(release, proj, inputs))
    return ProjectionReport(release.build_id, gates)
