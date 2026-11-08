"""``ragdata kg-project``: the graph layer in Neo4j, read back and compared before it counts."""

from __future__ import annotations

import json

import pytest

import mini_release
from fake_neo4j import FakeNeo4j
from ragdata import cli
from ragdata.contract.registry import KG_META
from ragdata.kg.graph_build import build_graph
from ragdata.kg.graph_schema import edge, meta_doc, node, sorted_edges, sorted_nodes
from ragdata.kg.layers import encode_json
from ragdata.loader import cli as loader_cli
from ragdata.loader import config
from ragdata.loader import graph_load as gl
from ragdata.loader.neo4j_db import SCHEMA_NAMES, Neo4jDbError
from ragdata.release import assemble as rel
from ragdata.store import encode_jsonl
from ragdata.store.cas import sha256_bytes

DATE = "20261008"
BUILD, OTHER = "b20261102_aaaaaaaa", "b20261102_bbbbbbbb"


def _source(build_id: str = BUILD, names: int = 1203) -> gl.GraphSource:
    """Past one batch of names, nulls that cannot be stored, two PARALLELs between one pair."""
    nodes = sorted_nodes([
        node("Pericope", "pc:a", book_id="gen", section_title=None, title=None, start_slot="gen.1.1",
             end_slot="gen.1.2"),
        node("Pericope", "pc:b", book_id="gen", section_title="創造", title="第二段", start_slot="gen.1.3",
             end_slot="gen.1.4"),
        node("Person", "e000001", label="亞當", surfaces=["亞當"], kin_conflict=False, mentions=2,
             mention_units=["gen.2.7", "gen.3.20"]),
        node("Person", "e000002", label="塞特", surfaces=[], kin_conflict=True, mentions=0,
             mention_units=[]),
        *(node("Name", f"nm:{i:04d}", label=f"名{i}", surfaces=[f"名{i}"], df=i + 1,
               idf=0.1 + i / 7) for i in range(names)),
    ])
    edges = sorted_edges([
        edge("PARALLEL", "Pericope", "pc:a", "Pericope", "pc:b", pr_id="pr:1"),
        edge("PARALLEL", "Pericope", "pc:a", "Pericope", "pc:b", pr_id="pr:2"),
        edge("PARENT_OF", "Person", "e000001", "Person", "e000002", role="P", provenance_class="pdf_rule",
             evidence_units=["gen.4.25"], patterns=["begot"]),
        *(edge("TITLE_MENTIONS", "Pericope", "pc:a", "Name", f"nm:{i:04d}") for i in range(names)),
    ])
    meta = meta_doc(nodes, edges)
    return gl.GraphSource(build_id, "graph@" + "0" * 12, sha256_bytes(encode_json(meta)), meta,
                          tuple(nodes), tuple(edges))


@pytest.fixture()
def db():
    return FakeNeo4j()


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("graph_load"))


@pytest.fixture(scope="module")
def release(mini):
    dirs = (mini.layers[k].path for k in ("text", "struct", "kg0", "events"))
    graph = build_graph(*dirs, mini.store, mini.root / "registries").layers["graph"]
    return rel.assemble(mini.store, [*mini.top, graph.version], DATE, mini.checks)


# ---------------------------------------------------------------- projection
def test_a_projection_holds_every_row_and_ends_complete(db):
    source = _source()
    report = gl.project(source, db)
    info = db.infos[BUILD]
    assert info["complete"] is True and info["kg_sha256"] == source.kg_sha256
    assert info["schema_version"] == source.meta["schema_version"]
    assert info["nodes_Name"] == 1203 and info["edges_PARALLEL"] == 2
    assert info["nodes_sha256"] == source.meta["nodes_sha256"]
    assert info["edges_sha256"] == source.meta["edges_sha256"]
    assert report["written"] is True and report["build_id"] == BUILD
    assert report["counts"] == source.meta["counts"]
    assert set(db.schema) == set(SCHEMA_NAMES)


def test_complete_is_set_only_after_the_read_back(db):
    gl.project(_source(), db)
    calls = db.calls
    assert calls.index("open_build") < calls.index("merge_nodes") < calls.index("merge_edges")
    last_read = max(i for i, call in enumerate(calls) if call.startswith("read_"))
    assert last_read < calls.index("mark_complete")


def test_every_write_is_a_batch_of_at_most_500_rows(db):
    gl.project(_source(), db)
    assert max(size for _, size in db.writes) == gl.BATCH == 500
    names = [size for what, size in db.writes if what == "Name"]
    assert names == [500, 500, 203]


def test_a_null_is_not_stored_and_reads_back_to_the_same_bytes(db):
    source = _source()
    gl.project(source, db)
    stored = db.nodes[(BUILD, "Pericope", "pc:a")]
    assert "title" not in stored and "section_title" not in stored
    back = gl.read_back(BUILD, db)
    assert sha256_bytes(encode_jsonl(back.nodes)) == source.meta["nodes_sha256"]
    assert sha256_bytes(encode_jsonl(back.edges)) == source.meta["edges_sha256"]


def test_two_parallels_between_one_pair_stay_two_edges(db):
    gl.project(_source(), db)
    found = {k[-1] for k in db.edges if k[1] == "PARALLEL"}
    assert found == {("pr:1",), ("pr:2",)}


def test_running_again_writes_nothing_and_reads_everything_back(db):
    source = _source()
    gl.project(source, db)
    writes, db.calls = len(db.writes), []
    report = gl.project(source, db)
    assert report["written"] is False and len(db.writes) == writes
    assert "read_nodes" in db.calls and "open_build" not in db.calls


def test_an_interrupted_projection_is_not_complete_and_running_again_finishes_it(db):
    source = _source()
    db.fail_at_write = 2
    with pytest.raises(Neo4jDbError):
        gl.project(source, db)
    assert db.infos[BUILD]["complete"] is False
    db.fail_at_write = None
    assert gl.project(source, db)["written"] is True
    assert db.infos[BUILD]["complete"] is True
    assert gl.projection_violations(source, db) == []


def test_a_build_info_of_another_graph_is_refused_and_nothing_is_written(db):
    gl.project(_source(), db)
    other = _source(names=9)
    writes = len(db.writes)
    with pytest.raises(gl.ProjectionError, match="kg_sha256"):
        gl.project(other, db)
    assert len(db.writes) == writes and db.infos[BUILD]["complete"] is True


def test_an_unfinished_build_info_of_another_graph_is_refused_too(db):
    db.fail_at_write = 1
    with pytest.raises(Neo4jDbError):
        gl.project(_source(), db)
    db.fail_at_write = None
    with pytest.raises(gl.ProjectionError, match="kg_sha256"):
        gl.project(_source(names=9), db)


def test_rows_lost_on_the_way_in_leave_the_build_incomplete(db):
    db.lose_kind = "Name"
    with pytest.raises(gl.ProjectionError, match="nodes Name: 0 in Neo4j, 1203 in kg_meta.json"):
        gl.project(_source(), db)
    assert db.infos[BUILD]["complete"] is False


def test_a_complete_build_that_no_longer_reads_back_is_marked_incomplete_and_refused(db):
    source = _source()
    gl.project(source, db)
    db.nodes[(BUILD, "Person", "e000001")]["label"] = "別人"
    writes = len(db.writes)
    with pytest.raises(gl.ProjectionError, match="nodes_sha256"):
        gl.project(source, db)
    assert db.infos[BUILD]["complete"] is False and len(db.writes) == writes


def test_builds_share_a_server_and_ids_without_touching_each_other(db):
    first, second = _source(BUILD), _source(OTHER, names=9)
    gl.project(first, db)
    gl.project(second, db)
    assert gl.projection_violations(first, db) == []
    assert gl.projection_violations(second, db) == []
    assert db.delete_build(BUILD) == 1207
    assert gl.projection_violations(second, db) == []
    assert not gl.read_back(BUILD, db).nodes


def test_an_edge_into_another_build_is_a_violation(db):
    source = _source()
    gl.project(source, db)
    real = db.read_edges

    def leaking(build_id, edge_type, src_kind, dst_kind):
        rows = real(build_id, edge_type, src_kind, dst_kind)
        return [{**r, "props": {**r["props"], "build_id": OTHER}} if edge_type == "PARENT_OF" else r
                for r in rows]
    db.read_edges = leaking
    assert any("another build" in v for v in gl.projection_violations(source, db))


# ---------------------------------------------------------------- what is checked
def _red(source, db, **info) -> list[str]:
    db.infos[source.build_id] = {**db.infos[source.build_id], **info}
    return gl.projection_violations(source, db)


@pytest.mark.parametrize("change, reason", [
    ({"complete": False}, "complete"),
    ({"kg_sha256": "0" * 64}, "kg_sha256"),
    ({"nodes_Name": 1}, "nodes_Name"),
    ({"edges_PARALLEL": 1}, "edges_PARALLEL"),
])
def test_the_build_info_must_say_complete_and_name_this_graph(db, change, reason):
    source = _source()
    gl.project(source, db)
    assert any(reason in v for v in _red(source, db, **change))


def test_no_build_info_is_a_violation(db):
    assert "no BuildInfo" in gl.projection_violations(_source(), db)[0]


def test_a_missing_constraint_or_index_is_a_violation(db):
    source = _source()
    gl.project(source, db)
    db.schema.discard("kg_name_label")
    assert any("kg_name_label" in v for v in gl.projection_violations(source, db))


def test_a_node_that_is_gone_is_named(db):
    source = _source()
    gl.project(source, db)
    del db.nodes[(BUILD, "Person", "e000002")]
    found = "\n".join(gl.projection_violations(source, db))
    assert "nodes Person: 1 in Neo4j, 2 in kg_meta.json" in found and "e000002" in found


def test_a_node_that_should_not_be_there_is_named(db):
    source = _source()
    gl.project(source, db)
    db.nodes[(BUILD, "Person", "e000099")] = {"label": "多的"}
    assert any("e000099" in v for v in gl.projection_violations(source, db))


# ---------------------------------------------------------------- the release's graph layer
def test_the_source_of_a_release_is_its_graph_layer(release):
    source = gl.source_of_release(release)
    assert source.build_id == release.build_id
    assert source.version == release.doc["layers"]["graph"]
    assert source.kg_sha256 == release.doc["contracts"][KG_META]
    assert source.kg_sha256 == sha256_bytes(release.contracts[KG_META])
    assert source.meta == json.loads(release.contracts[KG_META])
    assert sha256_bytes(encode_jsonl(source.nodes)) == source.meta["nodes_sha256"]


def test_a_release_without_the_graph_layer_has_no_source(mini):
    plain = rel.assemble(mini.store, mini.top, DATE, mini.checks)
    with pytest.raises(gl.ProjectionError, match="no graph layer"):
        gl.source_of_release(plain)


def test_the_real_mini_graph_projects_and_reads_back_byte_for_byte(db, release):
    source = gl.source_of_release(release)
    assert gl.project(source, db)["written"] is True
    assert gl.projection_violations(source, db) == []


def test_the_source_read_from_the_store_is_the_one_the_release_pins(mini, release, tmp_path):
    path = rel.write_release(release, tmp_path / "releases")
    source = gl.source_of_build(release.build_id, tmp_path / "releases", mini.store)
    assert source == gl.source_of_release(release)
    doc = json.loads(path.read_text(encoding="utf-8"))
    bad = tmp_path / "bad"
    bad.mkdir()
    doc["contracts"][KG_META] = "0" * 64
    (bad / f"{release.build_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(gl.ProjectionError, match="does not hash to what the release pins"):
        gl.source_of_build(release.build_id, bad, mini.store)


def test_a_build_with_no_release_file_is_refused(mini, tmp_path):
    with pytest.raises(gl.ProjectionError, match="no release"):
        gl.source_of_build(BUILD, tmp_path, mini.store)


# ---------------------------------------------------------------- the command line
@pytest.fixture()
def cli_setup(mini, release, tmp_path, monkeypatch, db):
    releases = tmp_path / "releases"
    rel.write_release(release, releases)
    monkeypatch.setattr(loader_cli, "connect_neo4j", lambda env: db)
    return ["--build", release.build_id, "--store", str(mini.store), "--releases", str(releases),
            "--env-file", str(tmp_path / "none")]


def test_kg_project_prints_what_it_did_and_a_second_run_writes_nothing(cli_setup, capsys, db, release):
    assert cli.main(["kg-project", *cli_setup]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["build_id"] == release.build_id and first["written"] is True
    assert first["kg_sha256"] == release.doc["contracts"][KG_META]
    assert cli.main(["kg-project", *cli_setup]) == 0
    assert json.loads(capsys.readouterr().out)["written"] is False
    assert db.closed


def test_kg_project_on_a_server_that_is_down_is_bad_input(cli_setup, capsys, db):
    db.unreachable = True
    assert cli.main(["kg-project", *cli_setup]) == 2
    assert "ServiceUnavailable" in capsys.readouterr().err and db.closed


def test_kg_project_of_an_unknown_build_is_bad_input(mini, tmp_path, capsys):
    argv = ["kg-project", "--build", BUILD, "--store", str(mini.store),
            "--releases", str(tmp_path), "--env-file", str(tmp_path / "none")]
    assert cli.main(argv) == 2
    assert "no release" in capsys.readouterr().err


def test_kg_project_needs_the_password_and_has_no_default(mini, release, tmp_path, capsys, monkeypatch):
    for key in config.NEO4J_KEYS:
        monkeypatch.delenv(key, raising=False)
    rel.write_release(release, tmp_path / "releases")
    env = tmp_path / ".env"
    env.write_text("NEO4J_URI=bolt://nowhere:7687\nNEO4J_USER=neo4j\n", encoding="utf-8")
    argv = ["kg-project", "--build", release.build_id, "--store", str(mini.store),
            "--releases", str(tmp_path / "releases"), "--env-file", str(env)]
    assert cli.main(argv) == 2
    assert "NEO4J_PASSWORD" in capsys.readouterr().err


def test_the_neo4j_settings_come_from_the_env_and_the_password_is_never_printed():
    env = {"NEO4J_URI": "bolt://h:7687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "s3cret-value"}
    found = config.neo4j_settings(env)
    assert (found.uri, found.user, found.password) == ("bolt://h:7687", "neo4j", "s3cret-value")
    assert "s3cret-value" not in repr(found)
    for key in env:
        with pytest.raises(config.ConfigError, match=key):
            config.neo4j_settings({k: v for k, v in env.items() if k != key})


def test_the_process_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("NEO4J_URI=bolt://file:7687\nNEO4J_USER=fromfile\n", encoding="utf-8")
    monkeypatch.setenv("NEO4J_URI", "bolt://process:7687")
    monkeypatch.delenv("NEO4J_USER", raising=False)
    found = loader_cli.environment(env)
    assert found["NEO4J_URI"] == "bolt://process:7687" and found["NEO4J_USER"] == "fromfile"


@pytest.mark.parametrize("build_id", ["../releases/b20261102_fc86a69b", "b20261102", "legacy", ""])
def test_a_build_id_that_is_no_build_id_is_refused_before_anything_is_read(build_id, tmp_path):
    with pytest.raises(gl.ProjectionError, match="not a release build id"):
        gl.source_of_build(build_id, tmp_path, tmp_path)


def test_a_release_file_of_another_build_is_refused(tmp_path):
    (tmp_path / "b20261102_00000000.json").write_text('{"build_id": "b20261102_11111111", "layers": {}}', encoding="utf-8")
    with pytest.raises(gl.ProjectionError, match="b20261102_11111111"):
        gl.source_of_build("b20261102_00000000", tmp_path, tmp_path)
