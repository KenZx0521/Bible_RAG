"""The graph layer over the mini snapshot: schema, determinism, the store, the release.

The mini text names no kin (no Person), so the kinship side is tested in test_kin_extract.py,
test_person_identity.py and over the real layers in test_graph_golden.py."""

from __future__ import annotations

import json
import math
import re

import pytest

import mini_release
from ragcommon import ids
from ragdata import cli
from ragdata.contract.registry import GRAPH_REPORT, KG_EDGES, KG_META, KG_NODES
from ragdata.gates.runner import gate_layer
from ragdata.kg import graph_names
from ragdata.kg.graph_build import build_graph
from ragdata.kg.graph_schema import SCHEMA_VERSION
from ragdata.kg.person_aliases import load
from ragdata.pipeline.steps import ORDER
from ragdata.release import assemble as rel
from ragdata.release.contracts import CONTRACT_FILES
from ragdata.store import read_layer, write_layer
from ragdata.store import versions as store_versions
from ragdata.stages.errors import StageError

DATE = "20261008"


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("graph"))


def _build(mini, store=None):
    return build_graph(*(mini.layers[k].path for k in ("text", "struct", "kg0", "events")),
                       store or mini.store, mini.root / "registries")


@pytest.fixture(scope="module")
def built(mini):
    result = _build(mini)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    return result.layers["graph"]


@pytest.fixture(scope="module")
def layer(built):
    return read_layer(built.path)


def _nodes(layer, kind):
    return {r["id"]: r["props"] for r in layer.rows[KG_NODES] if r["kind"] == kind}


def _edges(layer, edge_type, src_kind=None):
    return [r for r in layer.rows[KG_EDGES] if r["type"] == edge_type
            and src_kind in (None, r["src_kind"])]


def _pairs(rows):
    return {(r["src"], r["dst"]) for r in rows}


def test_a_stored_graph_layer_holds_its_four_files_and_depends_on_four_layers(mini, built, layer):
    assert re.fullmatch(r"graph@[0-9a-f]{12}", built.version) and built.path.parent.name == "graph"
    assert set(layer.file_shas) - {"depends_on.json"} == {KG_NODES, KG_EDGES, KG_META, GRAPH_REPORT}
    assert dict(layer.depends_on) == {k: mini.layers[k].version for k in ("text", "struct", "kg0", "events")}


def test_ragcommon_does_not_know_the_graph_layer_and_the_store_does(built):
    assert "graph" not in ids.LAYERS            # a new name there would move metric_version
    assert not ids.is_valid(built.version, "layer_version")
    assert store_versions.layer_of(built.version) == "graph"
    assert store_versions.layer_of("planet@000000000000") is None
    assert store_versions.layer_of("text@000000000000") == "text"
    assert store_versions.layer_version("graph", "ab" * 32) == "graph@" + "ab" * 6


def test_two_builds_give_the_same_bytes(mini, built, tmp_path):
    again = _build(mini, tmp_path / "again").layers["graph"]
    assert again.version == built.version
    for name in (KG_NODES, KG_EDGES, KG_META, GRAPH_REPORT):
        assert (again.path / name).read_bytes() == (built.path / name).read_bytes()


def test_rows_are_sorted_by_kind_and_id_and_edges_by_type_and_ends(layer):
    nodes = [(r["kind"], r["id"]) for r in layer.rows[KG_NODES]]
    assert len(set(nodes)) == len(nodes)
    assert [r["kind"] for r in layer.rows[KG_NODES]][0] == "Book"
    ids_of_verses = [i for k, i in nodes if k == "Verse"]
    assert ids_of_verses == sorted(ids_of_verses)
    edges = [(r["type"], r["src"], r["dst"]) for r in layer.rows[KG_EDGES] if r["type"] == "HAS_VERSE"]
    assert edges == sorted(edges)


def test_the_structure_comes_from_text_and_struct(mini, layer):
    assert set(_nodes(layer, "Book")["mat"]) == {"name", "ord", "testament"}
    assert _nodes(layer, "Chapter")["act.9"] == {"book_id": "act", "num": 9}
    assert _nodes(layer, "Verse")["act.9.3"]["book_id"] == "act"
    assert set(_nodes(layer, "Verse")["act.9.3"]) == {"book_id", "chapter", "ord"}
    passage = _nodes(layer, "Passage")["ps:act.9.3b"]
    assert passage == {"pericope_id": "pc:act.9.3b", "book_id": "act", "chapter": 9, "title": "天上的光",
                       "start_key": "act.9.3b", "end_key": "act.9.3b"}
    pericope = _nodes(layer, "Pericope")["pc:act.9.1"]
    assert set(pericope) == {"title", "section_title", "book_id", "start_slot", "end_slot"}
    assert pericope["title"] == "掃羅歸主－在路上" and pericope["start_slot"] == "act.9.1"
    assert _nodes(layer, "Pericope")["pc:sng.1.1"]["title"] is None
    assert ("act", "act.9") in _pairs(_edges(layer, "HAS_CHAPTER"))
    assert ("act.9", "ps:act.9.1") in _pairs(_edges(layer, "HAS_PASSAGE", "Chapter"))
    assert ("pc:act.9.1", "ps:act.9.1") in _pairs(_edges(layer, "HAS_PASSAGE", "Pericope"))


def test_a_stacked_section_heading_gives_the_section_title(layer):
    titled = {k: v["section_title"] for k, v in _nodes(layer, "Pericope").items() if v["section_title"]}
    assert titled == {"pc:act.9.1": "掃羅歸主"}


def test_a_verse_a_heading_cuts_belongs_to_both_its_passages(layer):
    verses = _pairs(_edges(layer, "HAS_VERSE"))
    assert ("ps:act.9.1", "act.9.3") in verses and ("ps:act.9.3b", "act.9.3") in verses


def test_next_stays_inside_a_book_and_follows_the_struct_order(layer):
    passages = _pairs(_edges(layer, "NEXT", "Passage"))
    assert ("ps:act.9.1", "ps:act.9.3b") in passages and ("ps:act.9.3b", "ps:act.10.1") in passages
    assert not any(a[3:6] != b[3:6] for a, b in passages)
    pericopes = _pairs(_edges(layer, "NEXT", "Pericope"))
    assert ("pc:act.9.1", "pc:act.9.3b") in pericopes
    assert not any(a[3:6] != b[3:6] for a, b in pericopes)


def test_a_merge_group_is_one_mention_of_one_name_and_counts_add_up(layer):
    salt_sea = ids.name_id("鹽海")
    mentions = [r for r in _edges(layer, "MENTIONS") if r["dst"] == salt_sea]
    assert {(r["src_kind"], r["src"], r["props"]["count"]) for r in mentions} == {
        ("Verse", "act.9.2", 1), ("Passage", "ps:act.9.1", 1)}
    saul = ids.name_id("掃羅")
    assert {(r["src"], r["props"]["count"]) for r in _edges(layer, "MENTIONS", "Passage") if r["dst"] == saul} == {
        ("ps:act.9.1", 2)}


def test_a_name_knows_how_many_passages_mention_it(layer):
    names = _nodes(layer, "Name")
    saul = names[ids.name_id("掃羅")]
    n = len(_nodes(layer, "Passage"))
    assert saul["label"] == "掃羅" and saul["surfaces"] == ["掃羅"] and saul["df"] == 1
    assert saul["idf"] == pytest.approx(round(math.log(n), 6))


def test_a_span_after_the_cut_goes_to_the_passage_that_owns_those_characters():
    spans = [{"container_id": "act.9.3", "region": "body", "merge_group": None, "start": 2, "end": 4,
              "surface": "掃羅", "norm_key": "掃羅"},
             {"container_id": "act.9.3", "region": "body", "merge_group": None, "start": 20, "end": 22,
              "surface": "掃羅", "norm_key": "掃羅"}]
    passages = [{"passage_id": "ps:act.9.1", "unit_refs": [{"unit_key": "act.9.3", "from": 0, "to": 12}]},
                {"passage_id": "ps:act.9.3b", "unit_refs": [{"unit_key": "act.9.3", "from": 12, "to": None}]}]
    counts = graph_names.mention_counts(spans, passages, {"掃羅": "nm:1"})
    assert counts.by_verse == {("act.9.3", "nm:1"): 2}
    assert counts.by_passage == {("ps:act.9.1", "nm:1"): 1, ("ps:act.9.3b", "nm:1"): 1}


def test_a_span_no_passage_owns_stops_the_build():
    spans = [{"container_id": "act.9.3", "region": "body", "merge_group": None, "start": 2, "end": 4,
              "surface": "掃羅", "norm_key": "掃羅"}]
    with pytest.raises(StageError, match="act.9.3"):
        graph_names.mention_counts(spans, [], {"掃羅": "nm:1"})


def test_a_span_the_kg0_names_left_out_is_no_mention():
    spans = [{"container_id": "act.9.3", "region": "body", "merge_group": None, "start": 2, "end": 4,
              "surface": "舍客勒", "norm_key": "舍客勒"}]
    passages = [{"passage_id": "ps:act.9.1", "unit_refs": [{"unit_key": "act.9.3", "from": 0, "to": None}]}]
    assert graph_names.mention_counts(spans, passages, {}).by_verse == {}


def test_title_mentions_read_the_headings_names_and_the_section_headings_for_its_pericopes():
    extra = [{"container_id": "hd:act.9.1#1", "region": "heading", "source": "lexicon", "surface": "掃羅"},
             {"container_id": "hd:act.9.1#1", "region": "heading", "source": "lexicon", "surface": "掃羅"},
             {"container_id": "sp:psa.42", "region": "superscription", "source": "lexicon", "surface": "可拉"},
             {"container_id": "hd:none#1", "region": "heading", "source": "lexicon", "surface": "掃羅"}]
    pericopes = [{"pericope_id": "pc:act.9.1", "heading_id": "hd:act.9.1#1", "section_heading_id": None},
                 {"pericope_id": "pc:act.9.3b", "heading_id": "hd:act.9.3#1", "section_heading_id": "hd:act.9.1#1"}]
    found = graph_names.title_mentions(extra, [], pericopes, {"掃羅": "nm:1", "可拉": "nm:2"})
    assert found.pairs == {("pc:act.9.1", "nm:1"), ("pc:act.9.3b", "nm:1")}
    assert found.unplaced == 1


def test_mini_title_mentions_and_parallels_and_events(layer, mini):
    titles = _pairs(_edges(layer, "TITLE_MENTIONS"))
    assert ("pc:act.9.1", ids.name_id("掃羅")) in titles
    assert all(a.startswith("pc:") and b.startswith("nm:") for a, b in titles)
    parallels = _edges(layer, "PARALLEL")
    assert parallels and all(r["props"]["pr_id"].startswith("pr:") for r in parallels)
    events = _nodes(layer, "Event")
    anchored = _pairs(_edges(layer, "ANCHORED_AT"))
    assert events and {a for a, _ in anchored} == set(events)
    assert all(set(v) == {"name"} for v in events.values())


def test_the_meta_counts_every_kind_and_type_and_names_the_shas(layer):
    meta = json.loads((layer.path / KG_META).read_text(encoding="utf-8"))
    assert meta["schema_version"] == SCHEMA_VERSION
    assert sum(meta["counts"]["nodes"].values()) == len(layer.rows[KG_NODES])
    assert sum(meta["counts"]["edges"].values()) == len(layer.rows[KG_EDGES])
    assert meta["nodes_sha256"] == layer.file_shas[KG_NODES]
    assert meta["edges_sha256"] == layer.file_shas[KG_EDGES]


def test_the_report_names_the_alias_registry_and_the_rows_read(mini, layer):
    report = json.loads((layer.path / GRAPH_REPORT).read_text(encoding="utf-8"))
    assert report["aliases"] == load(mini.root / "registries").version
    assert report["kin"]["rows"] == 0 and report["identity"]["persons"] == 0


def test_the_stored_layer_passes_its_gate_with_its_dependencies(mini, built):
    deps = [mini.layers[k].path for k in ("text", "struct", "kg0", "events")]
    report = gate_layer(built.path, "graph", deps, mini_release.MINI_COUNTS, inputs=mini.checks.inputs)
    assert report.passed, report.to_json()


def test_a_kg0_built_on_another_text_is_refused(mini, tmp_path):
    other = write_layer(tmp_path, "kg0", {name: (mini.layers["kg0"].path / name).read_bytes()
                                          for name in ("names.jsonl", "extra_spans.jsonl",
                                                       "parallel_links.jsonl", "kg0_report.json")},
                        depends_on={"text": "text@000000000000", "struct": mini.layers["struct"].version})
    with pytest.raises(StageError, match="built on"):
        build_graph(mini.layers["text"].path, mini.layers["struct"].path, other.path,
                    mini.layers["events"].path, tmp_path, mini.root / "registries")


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_the_cli_builds_and_gates_the_layer(mini, built, tmp_path, capsys):
    deps = {k: mini.layers[k].path for k in ("text", "struct", "kg0", "events")}
    code, out = _cli(capsys, "build", "graph", "--text", deps["text"], "--struct", deps["struct"], "--kg0", deps["kg0"],
                     "--events", deps["events"], "--store", tmp_path, "--registries", mini.root / "registries")
    assert code == 0 and json.loads(out.out)["layers"]["graph"]["version"] == built.version
    code, out = _cli(capsys, "gate", "graph", tmp_path / "graph" / built.version, *(a for d in deps.values() for a in ("--dep", d)),
                     "--counts", mini_release.MINI_COUNTS, "--registries", mini.root / "registries")
    assert code == 0 and json.loads(out.out)["pass"] is True


def test_the_cli_refuses_a_graph_build_without_its_layers(mini, tmp_path, capsys):
    code, out = _cli(capsys, "build", "graph", "--text", mini.layers["text"].path, "--store", tmp_path)
    assert code == 2 and "--struct" in out.err


def test_the_pipeline_builds_the_graph_layer_last():
    assert ORDER[-1] == "graph"


def test_a_release_without_the_graph_layer_is_what_it_was(mini):
    release = rel.assemble(mini.store, mini.top, DATE, mini.checks)
    assert release.doc["contract_version"] == "1.1.0" and release.doc["kg_enabled"] is False
    assert "graph" not in release.doc["layers"] and set(release.doc["contracts"]) == set(CONTRACT_FILES)


def test_a_release_with_the_graph_layer_turns_kg_on_and_carries_kg_meta(mini, built):
    plain = rel.assemble(mini.store, mini.top, DATE, mini.checks)
    release = rel.assemble(mini.store, [*mini.top, built.version], DATE, mini.checks)
    assert release.doc["contract_version"] == "1.4.0" and release.doc["kg_enabled"] is True
    assert release.doc["layers"]["graph"] == built.version
    meta = (built.path / KG_META).read_bytes()
    assert release.contracts["kg_meta.json"] == meta
    assert release.doc["contracts"]["kg_meta.json"] == rel.sha256_bytes(meta)
    assert set(release.doc["contracts"]) == {*CONTRACT_FILES, "kg_meta.json"}
    assert release.doc["counts"] == plain.doc["counts"]         # the graph holds no records
    for key in ("depends_on", "layer_digests"):
        rest = {k: v for k, v in release.doc[key].items() if k != "graph"}
        assert rest == plain.doc[key]


def test_a_release_with_the_graph_layer_reads_back_byte_for_byte(mini, built, tmp_path):
    release = rel.assemble(mini.store, [*mini.top, built.version], DATE, mini.checks)
    path = rel.write_release(release, tmp_path)
    assert rel.read_release(path, mini.store, mini.checks).data == release.data


def test_a_graph_layer_built_on_another_kg0_breaks_the_release_closure(mini, built, tmp_path):
    other = dict(json.loads((built.path / "depends_on.json").read_text()), kg0="kg0@000000000000")
    stranger = write_layer(mini.store, "graph",
                           {n: (built.path / n).read_bytes() for n in (KG_NODES, KG_EDGES, KG_META, GRAPH_REPORT)},
                           depends_on=other)
    with pytest.raises(rel.ReleaseError):
        rel.assemble(mini.store, [*mini.top, stranger.version], DATE, mini.checks)
