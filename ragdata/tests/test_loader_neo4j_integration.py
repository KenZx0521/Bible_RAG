"""The projection against a real Neo4j: set RAGDATA_TEST_NEO4J=1 (uses NEO4J_* from the environment
or the repository's ``.env``). Each test writes a build id no release can have and deletes it, also
when it fails; nothing else on the server is touched. Without the variable every test is skipped.
"""

from __future__ import annotations

import os

import pytest

from ragdata import paths
from ragdata.kg.graph_schema import edge, meta_doc, node, sorted_edges, sorted_nodes
from ragdata.kg.layers import encode_json
from ragdata.loader import cli as loader_cli
from ragdata.loader import graph_load as gl
from ragdata.loader import neo4j_db
from ragdata.store.cas import sha256_bytes

pytestmark = pytest.mark.skipif(not os.environ.get("RAGDATA_TEST_NEO4J"),
                                reason="RAGDATA_TEST_NEO4J not set")
BUILD, OTHER = "b19990101_00000001", "b19990101_00000002"
NAMES = 1203


def _source(build_id: str = BUILD, names: int = NAMES) -> gl.GraphSource:
    nodes = sorted_nodes([
        node("Pericope", "pc:a", book_id="gen", section_title=None, title=None, start_slot="gen.1.1",
             end_slot="gen.1.2"),
        node("Pericope", "pc:b", book_id="gen", section_title="創造", title="第二段", start_slot="gen.1.3",
             end_slot="gen.1.4"),
        node("Person", "e1", label="甲", surfaces=["甲", "甲甲"], kin_conflict=False, mentions=1,
             mention_units=["gen.1.1"]),
        node("Person", "e2", label="乙", surfaces=[], kin_conflict=True, mentions=0, mention_units=[]),
        *(node("Name", f"nm:{i:04d}", label=f"名{i}", surfaces=[f"名{i}", f"異{i}"], df=i + 1,
               idf=0.1 + i / 7) for i in range(names)),
    ])
    edges = sorted_edges([
        edge("PARALLEL", "Pericope", "pc:a", "Pericope", "pc:b", pr_id="pr:1"),
        edge("PARALLEL", "Pericope", "pc:a", "Pericope", "pc:b", pr_id="pr:2"),
        edge("PARENT_OF", "Person", "e1", "Person", "e2", role="P", provenance_class="pdf_rule",
             evidence_units=["gen.4.25", "gen.5.3"], patterns=["begot"]),
        *(edge("TITLE_MENTIONS", "Pericope", "pc:a", "Name", f"nm:{i:04d}") for i in range(names)),
    ])
    meta = meta_doc(nodes, edges)
    return gl.GraphSource(build_id, "graph@" + "0" * 12, sha256_bytes(encode_json(meta)), meta,
                          tuple(nodes), tuple(edges))


@pytest.fixture()
def db():
    found = loader_cli.connect_neo4j(loader_cli.environment(paths.REPO / ".env"))
    for build_id in (BUILD, OTHER):
        found.delete_build(build_id)
    try:
        yield found
    finally:
        for build_id in (BUILD, OTHER):
            found.delete_build(build_id)
        found.close()


def test_project_read_back_run_again_and_delete(db):
    source = _source()
    report = gl.project(source, db)
    assert report["written"] is True and db.build_info(BUILD)["complete"] is True
    assert gl.projection_violations(source, db) == []
    assert db.schema_missing() == []
    assert gl.project(source, db)["written"] is False
    assert db.delete_build(BUILD) == NAMES + 4
    assert db.build_info(BUILD) is None and not gl.read_back(BUILD, db).nodes


def test_an_interrupted_projection_finishes_on_the_next_run(db):
    source = _source()
    db.ensure_schema()
    db.open_build(BUILD, gl.build_info_props(source))
    db.merge_nodes(BUILD, "Name", [{"id": r["id"], "props": r["props"]}
                                   for r in source.nodes if r["kind"] == "Name"][:500])
    assert db.build_info(BUILD)["complete"] is False
    assert gl.project(source, db)["written"] is True
    assert gl.projection_violations(source, db) == []


def test_two_builds_with_the_same_ids_live_side_by_side(db):
    first, second = _source(BUILD), _source(OTHER, names=9)
    gl.project(first, db)
    gl.project(second, db)
    assert gl.projection_violations(first, db) == []
    assert gl.projection_violations(second, db) == []
    db.delete_build(OTHER)
    assert gl.projection_violations(first, db) == []
    assert db.build_info(OTHER) is None


def test_another_graph_under_the_same_build_is_refused(db):
    gl.project(_source(), db)
    with pytest.raises(gl.ProjectionError, match="kg_sha256"):
        gl.project(_source(names=9), db)


def test_a_tampered_node_is_found_and_the_two_parallels_are_two(db):
    source = _source()
    gl.project(source, db)
    rows = db.read_edges(BUILD, "PARALLEL", "Pericope", "Pericope")
    assert sorted(r["props"]["pr_id"] for r in rows) == ["pr:1", "pr:2"]
    db.run_write("MATCH (n:Person {build_id:$b, id:'e1'}) SET n.label = '別人'", b=BUILD)
    assert any("nodes_sha256" in v for v in gl.projection_violations(source, db))


