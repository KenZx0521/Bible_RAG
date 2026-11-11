"""The Cypher templates against a real Neo4j holding a real build; off unless asked for.

The other graph tests run on a fake driver and cannot tell whether a template parses or computes what
it should. Here the walk is compared with the same arithmetic done in plain Python on the graph layer's
files, and a few cards with what the text says. To run them:

    BACKEND_TEST_NEO4J_BUILD=<a build with a graph> \
    BACKEND_TEST_GRAPH_LAYER=/mnt/ollama-data/bible_rag_store/layers/graph/graph@<its version> \
    pytest backend/tests/test_cypher_live.py
"""

import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

import graph_fakes as G
from config import settings
from database import neo4j_db
from ragcommon import routing
from utils.kg import kin_card
from utils.retrieval import graph_walk

BUILD = os.environ.get("BACKEND_TEST_NEO4J_BUILD")
LAYER = os.environ.get("BACKEND_TEST_GRAPH_LAYER")
pytestmark = pytest.mark.skipif(not (BUILD and LAYER), reason="set BACKEND_TEST_NEO4J_BUILD and BACKEND_TEST_GRAPH_LAYER")


def _rows(name: str):
    return [json.loads(line) for line in (Path(LAYER) / name).open(encoding="utf-8")]


@pytest.fixture(scope="module")
def small() -> G.SmallGraph:
    """The whole graph as the fake's walk reads it."""
    nodes, edges = _rows("kg_nodes.jsonl"), _rows("kg_edges.jsonl")
    names = {r["id"]: (r["props"]["label"], r["props"]["df"], r["props"]["idf"]) for r in nodes if r["kind"] == "Name"}
    mentions: dict[str, list[str]] = defaultdict(list)
    for r in edges:
        if r["type"] == "MENTIONS" and r["src_kind"] == "Passage":
            mentions[r["src"]].append(r["dst"])
    pericope = {r["id"]: r["props"]["pericope_id"] for r in nodes if r["kind"] == "Passage"}
    members: dict[str, set[str]] = defaultdict(set)
    for passage, owner in pericope.items():
        members[owner].add(passage)
    across: dict[str, set[str]] = defaultdict(set)
    for r in edges:
        if r["type"] == "PARALLEL":
            across[r["src"]].add(r["dst"])
            across[r["dst"]].add(r["src"])
    parallel = {p: tuple(sorted(q for o in across[owner] for q in members[o])) for p, owner in pericope.items()}
    return G.SmallGraph({p: tuple(held) for p, held in mentions.items()}, names, parallel)


def _lexicon() -> routing.RoutingLexicon:
    path = Path("/mnt/ollama-data/bible_rag_store/contracts") / BUILD / "routing_lexicon.json"
    return routing.parse_lexicon(json.loads(path.read_text(encoding="utf-8")))


def _live(coroutine_of):
    async def go():
        try:
            return await coroutine_of()
        finally:
            await neo4j_db.close_driver()
    return asyncio.run(go())


@pytest.mark.parametrize("seeds, names", [
    ((("ps:exo.18.1", 1.0), ("ps:exo.3.1", 0.5), ("ps:gen.1.1", 1 / 3)), ("nm:3d123178122e",)),
    ((("ps:mat.1.1", 1.0), ("ps:luk.3.23", 0.5), ("ps:rut.4.13", 1 / 3)), ("nm:5c77d0047b58", "nm:45dbc0e74282")),
    ((("ps:1sa.9.1", 1.0),), ()),
    ((), ("nm:a4601de1b669", "nm:1216b4d0d4c6")),
])
def test_the_walk_on_the_server_is_the_arithmetic_on_the_files(small, monkeypatch, seeds, names):
    live = _live(lambda: graph_walk.walk(seeds, names, BUILD))
    assert live.skip_reason is None and live.n_cypher == 2

    G.use(monkeypatch, G.FakeGraph({"walk_round": G.walk_round(small)}))
    plain = asyncio.run(graph_walk.walk(seeds, names, BUILD))

    assert [p for p, _ in live.passages] == [p for p, _ in plain.passages]
    assert [s for _, s in live.passages] == pytest.approx([s for _, s in plain.passages], abs=1e-6)
    assert dict(live.names) == dict(plain.names)


@pytest.mark.parametrize("question, says, verses", [
    ("大衛和路得是什麼關係？", "耶西 是 俄備得 的子女，俄備得 是 路得 的子女（共 3 跳）", ()),
    ("雅各的祖父是誰？", "亞伯拉罕 是 以撒 的父母之一（創世記 21:3）", ("gen.25.26", "gen.27.6", "gen.28.1", "gen.32.1")),
    ("掃羅的孫子是誰？", "約拿單 是 米非波設 的父母之一（撒母耳記下 4:4）", ("1sa.9.3", "1sa.10.11", "1sa.14.1", "1sa.15.11")),
    ("撒母耳的母親是誰", "哈拿 是 撒母耳 的母親（撒母耳記上 1:20）", ("1sa.1.20", "1sa.2.18", "1sa.3.1", "1sa.3.4")),
    ("該隱的弟弟是誰", "該隱 與 亞伯 是兄弟姊妹（創世記 4:2）", ()),
    ("便雅憫人掃羅的父親是誰", "基士 是 掃羅 的父母之一", ("1sa.9.3", "1sa.10.11", "1sa.14.1", "1sa.15.11")),
])
def test_a_card_on_the_real_graph_says_what_the_text_says(question, says, verses):
    pool = [{"id": "x", "unit_refs": [{"unit_key": unit} for unit in verses]}]

    card = _live(lambda: kin_card.build(question, pool, _lexicon(), BUILD))

    assert card.skip_reason is None and says in card.text and len(card.text) <= settings.kin_card_max_chars
    assert "父親" not in card.text and card.evidence and card.passages


@pytest.mark.parametrize("question, says, never", [
    ("施洗約翰的父親是誰", "撒迦利亞", "西庇太"),
    ("猶大王希西家的父親是誰", "亞哈斯", "瑪拿西"),
    ("以色列王亞哈的父親是誰", "暗利", "以撒"),
    ("亞伯拉罕的兒子以撒的妻子是誰", "以撒 與 利百加 是配偶", "基土拉"),
    ("掃羅的兒子約拿單的兒子是誰", "米非波設", "亦施韋"),
    ("雅各和以掃的母親是誰", "以掃 與 雅各 是兄弟姊妹", "基土拉"),
    ("閃的兒子是誰", "以攔", "迦南"),
])
def test_what_review_caught_the_card_getting_wrong(question, says, never):
    card = _live(lambda: kin_card.build(question, [], _lexicon(), BUILD))
    assert card.skip_reason is None and says in card.text and never not in card.text


@pytest.mark.parametrize("question, first, second", [
    ("馬利亞和約瑟是什麼關係", "馬利亞", "約瑟"), ("西庇太和雅各是什麼關係", "西庇太", "雅各"),
    ("羅波安和亞比雅是什麼關係", "羅波安", "亞比雅"), ("撒迦利亞和約翰是什麼關係", "撒迦利亞", "約翰"),
])
def test_two_names_get_the_pair_one_edge_apart(question, first, second):
    card = _live(lambda: kin_card.build(question, [], _lexicon(), BUILD))
    assert card.hops == 1 and "共 1 跳" in card.text and first in card.text and second in card.text


def test_the_cited_verse_of_absalom_writes_both_names():
    card = _live(lambda: kin_card.build("押沙龍的父親是誰", [], _lexicon(), BUILD))
    assert "大衛 是 押沙龍 的父母之一（撒母耳記下 3:2）" not in card.text


def test_no_person_of_that_name_gives_no_card():
    card = _live(lambda: kin_card.build("葉忒羅的父親是誰", [], _lexicon(), BUILD))
    assert card.text is None and card.skip_reason == kin_card.NO_PERSON and card.n_cypher == 1


def test_a_large_family_still_fits_the_card():
    card = _live(lambda: kin_card.build("雅各的後代有誰", [], _lexicon(), BUILD))
    assert card.lines <= settings.kin_card_max_rows and len(card.text) <= settings.kin_card_max_chars


def test_the_server_says_its_version_and_the_build_is_complete():
    async def both():
        return await neo4j_db.server_version(), await neo4j_db.build_info(BUILD)
    version, info = _live(both)
    assert version.startswith("5.") and info["complete"] is True
