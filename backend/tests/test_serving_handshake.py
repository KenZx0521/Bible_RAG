"""Build selection and the handshake checks (design §7.8, strict from R1).

The build comes from rag_meta.serving for RAG_ENV, or from RAG_BUILD_ID; every
check compares what the stores and the contract hold with the build row, and
each kind of mismatch is reported, never repaired.
"""

import asyncio
from pathlib import Path

import pytest

from serving import build as build_mod
from serving import handshake as hs

BUILD_ROW = {"build_id": "b20261008_1bb6912e", "pg_schema": "bb20261008_1bb6912e",
             "qdrant_collection": "passages__b20261008_1bb6912e",
             "contracts_dir": "/contracts/b20261008_1bb6912e", "kg_enabled": False, "points": 22}
FP = {"tokenizer_sha": "t", "probe_ids_sha": "p", "unk_count": 3, "pair_template_ok": True}
CONTRACT_FP = {"bge_m3": {**FP, "dim": 8, "model": "BAAI/bge-m3"},
               "reranker": {**FP, "unk_count": 2}, "schema": "x"}
RUNTIME_FP = {"bge_m3": dict(FP), "reranker": {**FP, "unk_count": 2}}


class FakeConn:
    def __init__(self, serving=None, builds=None, error=None):
        self.serving, self.builds, self.error, self.calls = serving or {}, builds or {}, error, []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if self.error:
            raise self.error
        if "rag_meta.serving" in query:
            build_id = self.serving.get(args[0])
            return None if build_id is None else {"build_id": build_id}
        return self.builds.get(args[0])


def _resolve(conn, env="prod", build_id=None, root=None):
    return asyncio.run(build_mod.resolve(conn, env, build_id, root))


def test_the_serving_row_of_the_env_names_the_build():
    conn = FakeConn({"staging": BUILD_ROW["build_id"]}, {BUILD_ROW["build_id"]: BUILD_ROW})

    found = _resolve(conn, env="staging", root="/srv/contracts")

    assert found == build_mod.Build("b20261008_1bb6912e", "bb20261008_1bb6912e",
                                    "passages__b20261008_1bb6912e",
                                    Path("/srv/contracts/b20261008_1bb6912e"), False, 22)
    assert conn.calls[0][1] == ("staging",)


def test_rag_build_id_bypasses_serving():
    conn = FakeConn({}, {BUILD_ROW["build_id"]: BUILD_ROW})

    assert _resolve(conn, build_id=BUILD_ROW["build_id"]).build_id == BUILD_ROW["build_id"]
    assert all("rag_meta.serving" not in q for q, _ in conn.calls)


@pytest.mark.parametrize("conn, message", [
    (FakeConn({}, {}), "no row for env=prod"),
    (FakeConn({"prod": "b20990101_deadbeef"}, {}), "b20990101_deadbeef is not in rag_meta.builds"),
    (FakeConn({"prod": "b1"}, {"b1": {**BUILD_ROW, "pg_schema": "x; drop"}}), "not a schema name"),
    (FakeConn(error=OSError("connection refused")), "connection refused"),
])
def test_an_unresolvable_build_raises(conn, message):
    with pytest.raises(build_mod.BuildSelectionError, match=message):
        _resolve(conn)


def _build(**changes):
    row = {**BUILD_ROW, **changes}
    return build_mod.Build(row["build_id"], row["pg_schema"], row["qdrant_collection"],
                           Path(row["contracts_dir"]), row["kg_enabled"], row["points"])


def test_pg_build_info_must_name_the_build():
    build = _build()

    assert hs.check_pg(build, [build.build_id]) == []
    assert "names b20990101_deadbeef" in hs.check_pg(build, ["b20990101_deadbeef"])[0]
    assert "no build_info" in hs.check_pg(build, [])[0]
    assert "2 build_info rows" in hs.check_pg(build, [build.build_id, build.build_id])[0]


def test_qdrant_collection_must_exist_with_the_registered_point_count():
    build = _build()

    assert hs.check_qdrant(build, True, 22) == []
    assert "does not exist" in hs.check_qdrant(build, False, None)[0]
    assert "21 points" in hs.check_qdrant(build, True, 21)[0]


def test_the_manifest_must_describe_the_registered_build():
    build = _build()
    manifest = {"pg_schema": build.pg_schema, "qdrant_collection": build.qdrant_collection,
                "points": 22, "kg_enabled": False}

    assert hs.check_manifest(build, manifest) == []
    assert "points" in hs.check_manifest(build, {**manifest, "points": 23})[0]
    assert "qdrant_collection" in hs.check_manifest(build, {**manifest, "qdrant_collection": "x"})[0]


def test_a_kg_build_cannot_be_served_by_this_backend():
    assert hs.check_kg(_build(), {"kg_enabled": False}) == []
    assert "kg_enabled" in hs.check_kg(_build(kg_enabled=True), {"kg_enabled": False})[0]
    assert "kg_enabled" in hs.check_kg(_build(), {"kg_enabled": True})[0]


def test_encoder_probes_must_equal_the_contract_fingerprint():
    assert hs.check_encoders(CONTRACT_FP, RUNTIME_FP) == []

    wrong = {**RUNTIME_FP, "bge_m3": {**FP, "probe_ids_sha": "other"}}
    [problem] = hs.check_encoders(CONTRACT_FP, wrong)
    assert "bge_m3" in problem and "probe_ids_sha" in problem

    assert "reranker" in hs.check_encoders(CONTRACT_FP, {**RUNTIME_FP, "reranker": None})[0]
    assert "bge_m3" in hs.check_encoders({"reranker": CONTRACT_FP["reranker"]}, RUNTIME_FP)[0]


def test_handshake_ok_only_without_mismatches():
    assert hs.Handshake("b1", (), strict=True).ok
    assert not hs.Handshake("b1", ("x",), strict=True).ok
    assert hs.Handshake(None, ("x",), strict=False).to_json() == {
        "build_id": None, "ok": False, "strict": False, "mismatches": ["x"]}
