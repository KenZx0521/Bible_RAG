"""Startup handshake on fake stores: every kind of mismatch is refused.

A wrong build (unknown, or a schema holding another one), a point count that
differs, a contract file whose sha differs or that does not parse (an R1 build
among them), an encoder probe that differs, a KG build: each is a mismatch;
strict startup raises, non-strict startup serves no data. Missing event-registry
anchors fail startup either way.
"""

import asyncio
import hashlib
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from config import settings
from serving import context, startup
from utils.retrieval import event_registry

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
META = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))
BUILD_ID = META["build_id"]
FP_FILE = FIXTURE / "contracts" / BUILD_ID / "encoder_fingerprint.json"
CONTRACT_FP = json.loads(FP_FILE.read_text(encoding="utf-8"))
KEYS = ("tokenizer_sha", "probe_ids_sha", "unk_count", "pair_template_ok")
GOOD_FP = {name: {k: CONTRACT_FP[name][k] for k in KEYS} for name in ("bge_m3", "reranker")}
REGISTRY = event_registry.parse_registry(
    json.loads((FIXTURE / "contracts" / BUILD_ID / "event_registry.json").read_text("utf-8")))
ANCHORS = event_registry.anchor_passages(REGISTRY)
R1_CONTRACTS = FIXTURE.parent / "r1_contracts"
R1_BUILD_ID = "b20261008_1bb6912e"


class Stores:
    """What the fake PG and Qdrant hold; tests change it to make one thing wrong."""

    def __init__(self):
        self.serving = {"prod": BUILD_ID}
        self.builds = {BUILD_ID: {"build_id": BUILD_ID, "pg_schema": META["pg_schema"],
                                  "qdrant_collection": META["qdrant_collection"],
                                  "contracts_dir": f"/contracts/{BUILD_ID}", "kg_enabled": False,
                                  "points": META["points"]}}
        self.build_info = [BUILD_ID]
        self.exists, self.points = True, META["points"]
        self.passages = set(ANCHORS)
        self.unreachable = False
        self.pool_schema = None


class FakeConn:
    def __init__(self, stores):
        self.stores = stores

    async def fetchrow(self, query, *args):
        if "rag_meta.serving" in query:
            build = self.stores.serving.get(args[0])
            return None if build is None else {"build_id": build}
        return self.stores.builds.get(args[0])


@pytest.fixture
def stores(monkeypatch, tmp_path):
    s = Stores()
    shutil.copytree(FIXTURE / "contracts", tmp_path / "contracts")
    monkeypatch.setattr(settings, "contracts_root", str(tmp_path / "contracts"))
    monkeypatch.setattr(settings, "rag_env", "prod")
    monkeypatch.setattr(settings, "rag_build_id", None)
    monkeypatch.setattr(settings, "strict_build_check", True)
    pg, qd = startup.postgres, startup.qdrant_db

    @asynccontextmanager
    async def connect_meta():
        if s.unreachable:
            raise ConnectionRefusedError("connection refused")
        yield FakeConn(s)

    async def init_pool(schema):
        s.pool_schema = schema

    async def build_info_ids():
        return list(s.build_info)

    async def missing_passages(ids):
        return [i for i in ids if i not in s.passages]

    monkeypatch.setattr(pg, "connect_meta", connect_meta)
    monkeypatch.setattr(pg, "init_pool", init_pool)
    monkeypatch.setattr(pg, "build_info_ids", build_info_ids)
    monkeypatch.setattr(pg, "missing_passages", missing_passages)
    monkeypatch.setattr(qd, "init_client", lambda name: None)
    monkeypatch.setattr(qd, "collection_exists", lambda: s.exists)
    monkeypatch.setattr(qd, "count", lambda: s.points)
    s.contracts = tmp_path / "contracts" / BUILD_ID
    yield s
    context.reset()


def _start(fp=GOOD_FP):
    return asyncio.run(startup.start(fp))


def _mismatches(fp=GOOD_FP):
    active, handshake = _start(fp)
    assert active is None and not handshake.ok
    return handshake.mismatches


def test_a_consistent_build_is_served(stores):
    active, handshake = _start()

    assert handshake.ok and handshake.build_id == BUILD_ID
    assert stores.pool_schema == META["pg_schema"]
    assert active.build.contracts_dir == stores.contracts
    assert active.registry == REGISTRY and all(e.id.startswith("ev") for e in REGISTRY)
    assert active.book_ids["使徒行傳"] == "act"
    assert set(active.book_names) == set(active.book_ids) and "撒上" not in active.book_names
    assert active.lexicon.terms


def test_rag_build_id_equal_to_the_serving_build_is_served(stores, monkeypatch):
    monkeypatch.setattr(settings, "rag_build_id", BUILD_ID)

    assert _start()[1].ok


def test_a_complete_build_that_serving_does_not_name_is_refused(stores, monkeypatch):
    """RAG_BUILD_ID on a registered, consistent build is refused when serving names another."""
    other = "b20261007_68412f4f"
    stores.builds[other] = {**stores.builds[BUILD_ID], "build_id": other}
    stores.serving = {"prod": other}
    monkeypatch.setattr(settings, "rag_build_id", BUILD_ID)

    active, handshake = _start()

    assert active is None and handshake.build_id is None
    assert handshake.mismatches == (
        f"build: RAG_BUILD_ID={BUILD_ID} but rag_meta.serving(env=prod) names {other}",)


def test_rag_build_id_without_a_serving_row_is_refused(stores, monkeypatch):
    stores.serving = {}
    monkeypatch.setattr(settings, "rag_build_id", BUILD_ID)

    [problem] = _mismatches()
    assert "no row for env=prod" in problem


def test_no_serving_row_for_the_env(stores, monkeypatch):
    monkeypatch.setattr(settings, "rag_env", "staging")

    [problem] = _mismatches()
    assert "no row for env=staging" in problem


def test_a_wrong_build_id_is_refused(stores, monkeypatch):
    monkeypatch.setattr(settings, "rag_build_id", "b20990101_deadbeef")

    [problem] = _mismatches()
    assert problem == (f"build: RAG_BUILD_ID=b20990101_deadbeef "
                       f"but rag_meta.serving(env=prod) names {BUILD_ID}")


def test_a_serving_row_naming_an_unregistered_build_is_refused(stores):
    stores.serving = {"prod": "b20990101_deadbeef"}

    [problem] = _mismatches()
    assert "b20990101_deadbeef is not in rag_meta.builds" in problem


def test_a_schema_holding_another_build_is_refused(stores):
    stores.build_info = ["b20990101_deadbeef"]

    [problem] = _mismatches()
    assert "build_info names b20990101_deadbeef" in problem


def test_a_point_count_that_differs_is_refused(stores):
    stores.points = META["points"] - 1

    [problem] = _mismatches()
    assert f"holds {META['points'] - 1} points" in problem


def test_a_missing_collection_is_refused(stores):
    stores.exists = False

    [problem] = _mismatches()
    assert "does not exist" in problem


def test_a_contract_file_whose_sha_differs_is_refused(stores):
    path = stores.contracts / "event_registry.json"
    path.write_bytes(path.read_bytes() + b" ")

    [problem] = _mismatches()
    assert "event_registry.json sha256" in problem


def test_an_encoder_probe_that_differs_is_refused(stores):
    wrong = {**GOOD_FP, "reranker": {**GOOD_FP["reranker"], "probe_ids_sha": "0" * 64}}

    [problem] = _mismatches(wrong)
    assert "reranker probe_ids_sha" in problem


def test_a_kg_build_is_refused(stores):
    stores.builds[BUILD_ID]["kg_enabled"] = True

    [problem] = _mismatches()
    assert "kg_enabled=True" in problem


def test_unreachable_postgres_is_a_mismatch(stores):
    stores.unreachable = True

    [problem] = _mismatches()
    assert "postgres unreachable" in problem


def test_strict_startup_raises_and_serves_nothing(stores):
    stores.points = 0

    with pytest.raises(startup.StartupError, match="holds 0 points"):
        asyncio.run(startup.run(GOOD_FP))
    with pytest.raises(context.NoActiveBuild, match="holds 0 points"):
        context.active()


def test_non_strict_startup_reports_and_serves_nothing(stores, monkeypatch):
    stores.points = 0
    monkeypatch.setattr(settings, "strict_build_check", False)

    handshake = asyncio.run(startup.run(GOOD_FP))

    assert not handshake.ok and not handshake.strict
    assert context.handshake() is handshake
    with pytest.raises(context.NoActiveBuild):
        context.active()


def test_a_missing_registry_anchor_fails_startup_even_when_not_strict(stores, monkeypatch):
    monkeypatch.setattr(settings, "strict_build_check", False)
    stores.passages.discard(ANCHORS[-1])

    with pytest.raises(startup.StartupError, match=ANCHORS[-1]):
        asyncio.run(startup.run(GOOD_FP))


def test_strict_success_installs_the_build(stores):
    handshake = asyncio.run(startup.run(GOOD_FP))

    assert handshake.ok and context.active().build.build_id == BUILD_ID


def _rewrite(stores, name: str, data: bytes) -> None:
    """Replace a contract file and re-hash it in the manifest: only its content is wrong."""
    (stores.contracts / name).write_bytes(data)
    manifest = json.loads((stores.contracts / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(data).hexdigest()
    (stores.contracts / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("name, data, message", [
    ("routing_lexicon.json", b"{not json", "routing_lexicon.json: Expecting"),
    ("routing_lexicon.json", b'{"schema": "ragdata.routing_lexicon.v1"}',
     "routing_lexicon.json: schema must be ragdata.routing_lexicon.v2"),
    ("query_aliases.json", b"[]", "query_aliases.json: query aliases schema"),
    ("event_registry.json", b'{"schema": "ragdata.event_registry.v2", "variant": "R1"}',
     "event_registry.json: registry variant must be R2"),
])
def test_a_contract_that_does_not_parse_is_a_mismatch_not_a_crash(stores, monkeypatch, name,
                                                                   data, message):
    monkeypatch.setattr(settings, "strict_build_check", False)
    _rewrite(stores, name, data)

    handshake = asyncio.run(startup.run(GOOD_FP))

    assert not handshake.ok and len(handshake.mismatches) == 1
    assert handshake.mismatches[0].startswith(f"contracts: {name}: ")
    assert message in handshake.mismatches[0]


def test_the_r2_image_refuses_an_r1_build(stores, monkeypatch):
    """The R1 mini build's own contracts, served under its own build row."""
    r1 = json.loads((R1_CONTRACTS / R1_BUILD_ID / "manifest.json").read_text(encoding="utf-8"))
    r1_fp = json.loads((R1_CONTRACTS / R1_BUILD_ID / "encoder_fingerprint.json")
                       .read_text(encoding="utf-8"))
    monkeypatch.setattr(settings, "contracts_root", str(R1_CONTRACTS))
    stores.serving, stores.build_info = {"prod": R1_BUILD_ID}, [R1_BUILD_ID]
    stores.points = r1["points"]
    stores.builds[R1_BUILD_ID] = {"build_id": R1_BUILD_ID, "pg_schema": r1["pg_schema"],
                                  "qdrant_collection": r1["qdrant_collection"],
                                  "contracts_dir": f"/contracts/{R1_BUILD_ID}",
                                  "kg_enabled": False, "points": r1["points"]}

    mismatches = _mismatches({n: {k: r1_fp[n][k] for k in KEYS} for n in ("bge_m3", "reranker")})

    assert mismatches == (
        "contracts: manifest does not list query_aliases.json",
        "contracts: routing_lexicon.json: schema must be ragdata.routing_lexicon.v2, "
        "got 'ragdata.routing_lexicon.v1'",
        "contracts: event_registry.json: registry variant must be R2, got 'R1'")
