"""The Cypher the Neo4j adapter sends: closed over the graph schema, always inside one build."""

from __future__ import annotations

import re

import pytest

from ragdata.kg.graph_schema import EDGE_ENDS, EDGE_KEY_PROPS, NODE_KINDS
from ragdata.loader import neo4j_db as db

EVERY_EDGE = [(t, s, d) for t, ends in EDGE_ENDS.items() for s, d in ends]


def _all_templates() -> list[str]:
    return [*(db.node_merge(k) for k in NODE_KINDS), *(db.node_read(k) for k in NODE_KINDS),
            *(db.edge_merge(*e) for e in EVERY_EDGE), *(db.edge_read(*e) for e in EVERY_EDGE),
            *(db.delete_batch(k) for k in (db.BUILD_INFO, *NODE_KINDS)),
            db.READ_BUILD_INFO, db.OPEN_BUILD, db.MARK_COMPLETE]


@pytest.mark.parametrize("template", _all_templates())
def test_every_template_stays_inside_its_build_and_has_no_open_ended_walk(template):
    assert "build_id" in template and "$b" in template
    assert not re.search(r"\[[^\]]*\*", template), "no variable-length pattern"
    assert "elementId" not in template and " id(" not in template


def test_a_node_merges_on_its_build_and_id_and_a_null_clears_nothing_it_needs():
    assert db.node_merge("Verse") == ("UNWIND $rows AS row MERGE (n:Verse {build_id:$b, id:row.id}) "
                                      "SET n += row.props")


def test_an_edge_matches_both_ends_in_the_build_and_merges_on_its_type():
    template = db.edge_merge("MENTIONS", "Verse", "Name")
    assert "MATCH (a:Verse {build_id:$b, id:row.src})" in template
    assert "MATCH (c:Name {build_id:$b, id:row.dst})" in template
    assert "MERGE (a)-[r:MENTIONS {build_id:$b}]->(c)" in template
    assert template.endswith("SET r += row.props")


def test_a_parallel_also_merges_on_its_pr_id():
    assert EDGE_KEY_PROPS == {"PARALLEL": ("pr_id",)}
    assert "MERGE (a)-[r:PARALLEL {build_id:$b, pr_id:row.props.pr_id}]->(c)" in db.edge_merge(
        "PARALLEL", "Pericope", "Pericope")


@pytest.mark.parametrize("make, args", [
    (db.node_merge, ("Verse) DETACH DELETE n //",)),
    (db.node_read, ("Nope",)),
    (db.delete_batch, ("Person`",)),
    (db.edge_merge, ("MENTIONS", "Person", "Name")),
    (db.edge_merge, ("NOPE", "Verse", "Name")),
    (db.edge_read, ("HAS_VERSE", "Verse", "Passage")),
])
def test_a_name_outside_the_schema_never_reaches_a_template(make, args):
    with pytest.raises(db.Neo4jDbError, match="not in the graph schema"):
        make(*args)


def test_the_schema_has_a_composite_key_per_label_and_the_label_lookups():
    statements = db.schema_statements()
    for kind in NODE_KINDS:
        assert (f"CREATE CONSTRAINT kg_{kind.lower()}_key IF NOT EXISTS FOR (n:{kind}) "
                "REQUIRE (n.build_id, n.id) IS UNIQUE") in statements
    assert ("CREATE CONSTRAINT kg_buildinfo_key IF NOT EXISTS FOR (n:BuildInfo) "
            "REQUIRE n.build_id IS UNIQUE") in statements
    for kind in ("Name", "Person"):
        assert (f"CREATE INDEX kg_{kind.lower()}_label IF NOT EXISTS FOR (n:{kind}) "
                "ON (n.build_id, n.label)") in statements
    assert all("IF NOT EXISTS" in s for s in statements)
    assert set(db.SCHEMA_NAMES) == {re.search(r"kg_\w+", s).group(0) for s in statements}


def test_a_driver_error_comes_out_as_a_loader_error_without_the_settings():
    from neo4j.exceptions import ServiceUnavailable

    def fails():
        raise ServiceUnavailable("Couldn't connect to nowhere:7687")
    with pytest.raises(db.Neo4jDbError, match="ServiceUnavailable"):
        db.guarded(fails)
