"""Rule seeds (utils.regnal.seeds.rule_seeds) and the trigger's blockers.

On a small two-kingdom layer with the real chains' traps (cross- and same-kingdom homonyms,
names inside names, aliases, a king off the chain): a father marker only splits homonyms, the
anchor is the name nearest before the cue, the guards abstain, and only chain nodes come out.
Through /query: rule seeds make the card with no seed call, an abstention falls back to the
gemma seed call, a question whose names are all blocked takes no card. The store-backed tests
at the end replay experiment A's question sets and the 500-question GT; they are in-sample
(the rules were written after reading those questions).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from ragcommon import routing
from ragcommon.tests.lexicon_doc import document, event, name
from router_fakes import BOOK_TERMS
from routers import query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import generator
from utils.regnal import card as card_mod
from utils.regnal import engine
from utils.regnal.layer import parse_layer, with_blockers
from utils.regnal.seeds import MAX_SEEDS, rule_seeds
from utils.regnal.trigger import trigger

# "name|alias<father"; ids are I01.., J01.. in chain order
ISRAEL = ("耶羅波安", "拿答<耶羅波安", "巴沙", "以拉<巴沙", "暗利", "亞哈<暗利", "亞哈謝<亞哈", "約蘭<亞哈",
          "耶戶", "約哈斯<耶戶", "約阿施<約哈斯", "耶羅波安<約阿施", "撒迦利雅<耶羅波安", "沙龍", "米拿現",
          "比加轄<米拿現", "比加", "何細亞")
JUDAH = ("羅波安<所羅門", "亞比央|亞比雅<羅波安", "亞撒<亞比央", "約沙法<亞撒", "約蘭<約沙法", "亞哈謝<約蘭",
         "約阿施", "亞瑪謝<約阿施", "亞撒利雅|烏西雅<亞瑪謝", "約坦<亞撒利雅", "亞哈斯<約坦", "希西家<亞哈斯",
         "瑪拿西<希西家", "亞們<瑪拿西", "約西亞<亞們", "約哈斯<約西亞", "約雅敬|以利亞敬<約西亞", "約雅斤<約雅敬",
         "西底家")
# the lexicon: names holding a chain name (blockers), one holding none, a chain name, and an
# event naming a chain king (no blocker)
LEXICON = routing.parse_lexicon(document(
    names=[name(s, f"nm:5b00000000{i:02d}", "Person")
           for i, s in enumerate(("押沙龍", "以利亞撒", "亞哈隨魯", "以拉他", "掃羅", "亞哈"))],
    events=[event("亞哈之戰", "ev0099", "亞哈之戰")], books=BOOK_TERMS))
BUILD =Build("b20261019_0123abcd", "bb20261019_0123abcd", "passages__b", Path("/c"), False, 22)


def _node(nid: str, kd: str, spec: str, order: int) -> dict:
    head, _, father = spec.partition("<")
    nm, *aliases = head.split("|")
    fields = {"reign": [10 + order % 7, f"2ki.{order}.1", "ki"],
              "age": [20 + order % 9, f"2ki.{order}.2", "ki"]}
    if father:
        fields["father"] = [father, f"2ki.{order}.3", "succ"]
    return {"id": nid, "kingdom": kd, "name": nm, "aliases": aliases, "fields": fields,
            "evidence": [f"2ki.{order}.1"], "pending": False, "order": order, "created_by": "t",
            "has_acc": kd != "U"}


def _layer_doc(unchained: str = "所羅門") -> dict:
    """Israel I01..I18 and Judah J01..J19, each a chain of son edges, and one king off both
    chains (kingdom U, as the 2026-10 layer has Solomon)."""
    nodes, edges = [_node("U00", "U", unchained, 0)], []
    for kd, specs in (("I", ISRAEL), ("J", JUDAH)):
        for i, spec in enumerate(specs, 1):
            nodes.append(_node(f"{kd}{i:02d}", kd, spec, len(nodes)))
            if i > 1:
                edges.append([f"{kd}{i - 1:02d}", f"{kd}{i:02d}", "son", "2ki.1.1"])
    return {"policy": "occ", "fn_rule": "slot", "nodes": nodes, "edges": edges, "fallback_edges": [],
            "syncs": [], "conflicts": [], "log": [], "occ_alias": [], "union_classes": None}


def _parse(doc: dict):
    return with_blockers(parse_layer(json.dumps(doc, ensure_ascii=False).encode("utf-8")), LEXICON)


@pytest.fixture(scope="module")
def layer():
    return _parse(_layer_doc())


def test_blockers_are_lexicon_words_holding_a_chain_name(layer):
    assert layer.blockers == ("亞哈隨魯", "以利亞撒", "以拉他", "押沙龍")
    assert parse_layer(json.dumps(_layer_doc(), ensure_ascii=False).encode("utf-8")).blockers == ()


@pytest.mark.parametrize("question, ids", [
    ("耶羅波安（約阿施的兒子）之前第三位王叫什麼？", ("I12",)),     # a chain-name father: no seed, it splits
    ("約阿施的兒子耶羅波安之後的第二位王是誰？", ("I12",)),
    ("耶羅波安，父親約阿施，之後的第二位王是誰？", ("I12",)),
    ("耶羅波安（尼八的兒子）以後第三任的王是誰？", ("I01",)),       # a father off the chain: the fatherless one
    ("耶羅波安(約阿施的兒子)之前第三位王叫什麼?", ("I12",)),        # half-width, as NFKC makes it
    ("耶羅波安(尼八的兒子)以後第三任的王是誰?", ("I01",)),
    ("耶羅波安二世之後的第一位王是誰？", ("I12",)),
    ("猶大王約蘭之後的第二位王是誰？", ("J05",)),                    # the kingdom prefix binds
    ("以色列王約蘭之後的第二位王是誰？", ("I08",)),
    ("約蘭之後第三位猶大王叫什麼？", ("J05",)),                      # the question's one kingdom word splits
    ("猶大王約沙法在位時，亞哈之後的第二位王是誰？", ("I06",)),      # ... but never moves a unique name
    ("亞哈的兒子約蘭之後的第二位王是誰？", ("I08",)),               # a father marker splits across kingdoms
    ("約沙法的兒子約蘭出生時，在位的王是誰？", ("J05",)),
    ("約西亞的兒子約哈斯之前的第三位王是誰？", ("J16",)),
    ("耶戶的兒子約哈斯之後的第二位王是誰？", ("I10",)),
    ("約沙法的兒子耶戶之後的第三位王是誰？", ("I09",)),             # 2ki.9.2: that 約沙法 is no seed
    ("亞哈斯之後的第二位王是誰？", ("J11",)),                        # names inside names: the longest
    ("以色列王亞哈謝之後的第二位王是誰？", ("I07",)),
    ("比加轄之前的第二位王是誰？", ("I16",)),
    ("比加之前的第二位王是誰？", ("I17",)),
    ("亞撒利雅之後的第二位王是誰？", ("J09",)),
    ("亞撒之後的第二位王是誰？", ("J03",)),
    ("羅波安之後的第二位王是誰？", ("J01",)),
    ("烏西雅之後的第二位王是誰？", ("J09",)),                        # an alias
    ("亞哈之後的第二位王是約蘭嗎？", ("I06",)),                      # a name after the cue is no seed
    ("約蘭是不是亞哈之後的第二位王？", ("I06",)),                    # the nearest name before the cue
    ("猶大王亞撒在位時，以色列王巴沙作王；巴沙之後的第二位王是誰？", ("I03",)),
    ("從猶大王亞撒到猶大王約蘭，王位交接了幾次？", ("J03", "J05")),  # S1b: the span's two ends, in order
    ("從亞比央到亞哈謝，猶大的王位交接了幾次？", ("J02", "J06")),
    ("從亞撒到羅波安，王位交接了幾次？", ("J03", "J01")),
    ("從羅波安到亞撒，猶大王亞比央在中間，王位交接了幾次？", ("J01", "J03")),
    ("從亞撒到約沙法再到約蘭，王位交接了幾次？", ("J03", "J04")),
    ("羅波安和亞撒之間，王位交接了幾次？", ("J01", "J03")),         # no span: exactly two names
    ("亞撒和亞哈斯相隔幾代？", ("J03", "J11")),
])
def test_rule_seeds_pick_the_named_king(layer, question, ids):
    got = rule_seeds(layer, question)
    assert got == (ids, None) and len(got.ids) <= MAX_SEEDS
    assert trigger(question, layer.names, layer.blockers).fired


@pytest.mark.parametrize("question, reason", [
    ("耶羅波安之後第三位以色列王叫什麼？", "homonym"),             # same kingdom, no father
    ("約蘭之後的第二位王是誰？", "homonym"),                        # two kingdoms, no kingdom word
    ("猶大王耶戶之後的第二位王是誰？", "no node"),                  # the prefix is a hard condition
    ("亞哈的兒子之後的第二位王是誰？", "the anchor's relative"),
    ("亞哈斯在位時有一位先知；這位王之後的第二位王是誰？", "a referring phrase"),
    ("之後的第二位王是誰？從亞哈算起。", "no anchor before the cue"),
    ("希勒家的兒子以利亞敬出生時在位的王是誰？", "father contradicts the layer"),
    ("耶何耶大的兒子撒迦利雅之後的第二位王是誰？", "father contradicts the layer"),
    ("從羅波安、亞比央到亞撒，王位交接了幾次？", "S1b"),           # two names in the span's from-slot
    ("亞撒、約沙法和約蘭之間王位交接了幾次？", "S1b"),
    ("亞撒之後王位交接了幾次？", "S1b"),
    ("亞哈一共作王多少年？", "no cue"),
])
def test_rule_seeds_abstain(layer, question, reason):
    got = rule_seeds(layer, question)
    assert got.ids == () and got.reason.startswith(reason)


@pytest.mark.parametrize("question", [
    "亞哈隨魯之後的第二位王是誰？", "押沙龍出生的時候，在位的王是誰？", "以利亞撒之後的第二位王是誰？",
    "以拉他之後的第二位王是誰？", "瑪拿西支派的人出生時在位的王是誰？", "瑪拿西半支派之後的第二位王是誰？",
    "所羅門之後的第二位王是誰？",                                   # off the chain (kingdom U)
])
def test_blocked_names_and_tribes_are_no_king_and_take_no_card(layer, question):
    assert not trigger(question, layer.names, layer.blockers).fired
    assert rule_seeds(layer, question) == ((), "no chain name")


def test_without_blockers_the_trigger_reads_the_name_inside(layer):
    hit = trigger("押沙龍之後的第二位王是誰？", layer.names)
    assert hit.fired and hit.kings == ("沙龍",)


def test_the_unchained_king_is_never_a_name_or_a_seed():
    lay = _parse(_layer_doc(unchained="亞們"))     # a U node bearing a chain king's name
    assert lay.view.nodes["U00"]["kingdom"] == "U" and "U00" not in lay.view.chain.get("U", [])
    ids, reason = rule_seeds(lay, "亞們之後的第二位王是誰？")
    assert (ids, reason) == (("J14",), None)
    card = card_mod.card_from_rule(lay, ids)
    assert card.seeds == (("J", "亞們"),) and "U00" not in card.text


def test_rule_seeds_are_deterministic_and_call_no_llm(layer, monkeypatch):
    def no_llm():
        raise AssertionError("the rule path called an LLM")
    monkeypatch.setattr(card_mod, "get_llm_client", no_llm)
    q = "約阿施的兒子耶羅波安之後的第二位王是誰？"
    cards = [asyncio.run(card_mod.chronology_card(q, "[1] 經文", layer)) for _ in range(3)]
    assert cards[0] == cards[1] == cards[2] and cards[0].seed_source == "rule"
    assert cards[0].seeds == (("I", "耶羅波安"),) and cards[0].kings == ("I12",)
    assert cards[0].text == engine.cards(layer.view, ["I12"])["g_block"]


# --- /query -------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    lay = parse_layer(json.dumps(_layer_doc(), ensure_ascii=False).encode("utf-8"))
    context.install(context.make_active(BUILD, LEXICON, (), lay), Handshake(BUILD.build_id, (), True))
    seen = {"chats": []}

    async def intent(question):
        return {"type": "person", "entities": [], "verse_refs": [], "keywords": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        hit = {"id": "ps:1ki.22.40", "kind": "passage", "book_name": "列王紀上", "chapter_num": 22,
               "title": "亞哈", "verse_range": "40", "content": "40 經文", "found_by": ["semantic"]}
        return [hit], {"strategies_used": ["semantic"], "route_used": "R4"}

    class FakeLlm:
        async def chat(self, messages, temperature, max_tokens):
            seen["chats"].append(messages)
            return "以色列｜亞哈" if messages[0]["content"] == card_mod.SEED_SYSTEM else "推理\n答案：約蘭"

    monkeypatch.setattr(query, "classify_intent", intent)
    monkeypatch.setattr(query, "retrieve_and_rerank", retrieve)
    monkeypatch.setattr(card_mod, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(generator, "get_llm_client", lambda: FakeLlm())
    yield TestClient(main.app), seen
    context.reset()


def test_the_active_build_attaches_the_lexicons_blockers(client):
    assert context.active().regnal.blockers == ("亞哈隨魯", "以利亞撒", "以拉他", "押沙龍")


def test_rule_seeds_make_the_card_without_a_seed_call(client):
    http, seen = client
    body = http.post("/api/v1/query", json={"question": "亞哈之後的第二位王是哪一位？"}).json()
    card = body["aux_card"]
    assert card["seed_source"] == "rule" and card["seeds"] == ["以色列｜亞哈"] and card["kings"] == ["I06"]
    assert len(seen["chats"]) == 1 and seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT_AUX
    assert card["text"] in seen["chats"][0][1]["content"]


def test_an_abstention_falls_back_to_the_gemma_seed_call(client):
    http, seen = client
    body = http.post("/api/v1/query", json={"question": "亞哈的兒子之後的第二位王是哪一位？"}).json()
    card = body["aux_card"]
    assert card["seed_source"] == "gemma" and card["seeds"] == ["以色列｜亞哈"] and card["kings"] == ["I06"]
    assert len(seen["chats"]) == 2 and seen["chats"][0][0]["content"] == card_mod.SEED_SYSTEM


def test_a_failed_fallback_seed_call_answers_the_ordinary_way(client, monkeypatch):
    http, seen = client

    async def boom(question, context):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(card_mod, "seed_call", boom)
    body = http.post("/api/v1/query", json={"question": "亞哈的兒子之後的第二位王是哪一位？"}).json()
    assert body["aux_card"] is None and body["answer"] == "推理\n答案：約蘭"
    assert len(seen["chats"]) == 1 and seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT


@pytest.mark.parametrize("question", ["押沙龍之後的第二位王是誰？", "所羅門之後的第二位王是誰？"])
def test_blocked_or_unchained_names_take_no_card_and_no_seed_call(client, question):
    http, seen = client
    body = http.post("/api/v1/query", json={"question": question}).json()
    assert body["aux_card"] is None
    assert len(seen["chats"]) == 1 and seen["chats"][0][0]["content"] == generator.SYSTEM_PROMPT


# --- store-backed (in-sample) -------------------------------------------------------------

STORE = Path("/mnt/ollama-data/bible_rag_store")
STORE_LAYER = STORE / "layers/relations/relations@a04b67a301dc/regnal_layer.json"
ROUTE_LEXICON = STORE / "layers/route/route@c31c88e4681e/routing_lexicon.json"   # b20261019_18aa84ad's
RUN_A = STORE / "reports/kg_cards_20261018/A"
CONFIRM = STORE / "reports/kg_cards_20261018/A_confirm"
REPO = Path(__file__).resolve().parents[2]
# measured on the 500-question GT (v1 and v2 alike): questions naming a chain king without the
# blockers, with them; and the blockers the lexicon gives that layer
NAMED = {"932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab": (21, 19, 28)}
needs_store = pytest.mark.skipif(
    not all(p.exists() for p in (STORE_LAYER, ROUTE_LEXICON, RUN_A / "items.json", CONFIRM / "items.json",
                                 RUN_A / "ref_layer.json")),
    reason="experiment A records, the regnal layer or the route lexicon not in the store")


@pytest.fixture(scope="module")
def store_layer():
    return with_blockers(parse_layer(STORE_LAYER.read_bytes()), routing.load_lexicon(ROUTE_LEXICON))


def _items(run: Path) -> list[dict]:
    return json.loads((run / "items.json").read_text(encoding="utf-8"))["items"]


def _gold(it: dict) -> list[tuple[str, str, int]]:
    """The item's gold seeds (reference-layer ids) as (kingdom, name, rank among that name)."""
    ref = json.loads((RUN_A / "ref_layer.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in ref}
    out = []
    for rid in it["seeds"]:
        r = by_id[rid]
        same = [s["id"] for s in ref if (s["kingdom"], s["name"]) == (r["kingdom"], r["name"])]
        out.append((r["kingdom"], r["name"], same.index(rid)))
    return out


def _named(V, ids) -> list[tuple[str, str, int]]:
    out = []
    for x in ids:
        n = V.nodes[x]
        same = [y for y in V.chain[n["kingdom"]] if V.nodes[y]["name"] == n["name"]]
        out.append((n["kingdom"], n["name"], same.index(x)))
    return out


@needs_store
def test_store_confirmation_set_rule_seeds_are_the_gold_seeds(store_layer):
    items = _items(CONFIRM)
    assert len(items) == 32
    for it in items:
        assert trigger(it["question"], store_layer.names, store_layer.blockers).fired, it["id"]
        ids, reason = rule_seeds(store_layer, it["question"])
        assert _named(store_layer.view, ids) == _gold(it), (it["id"], reason)


@needs_store
def test_store_dev_set_rule_seeds_are_the_gold_seeds_but_one_abstention(store_layer):
    items = _items(RUN_A)
    fired = [it for it in items if trigger(it["question"], store_layer.names, store_layer.blockers).fired]
    assert len(items) == 30 and {it["id"] for it in items} - {it["id"] for it in fired} == \
        {"SUC_01", "N_SUC_01", "N_KIN_14"}
    abstained = set()
    for it in fired:
        ids, _reason = rule_seeds(store_layer, it["question"])
        if not ids:
            abstained.add(it["id"])
            continue
        assert _named(store_layer.view, ids) == _gold(it), it["id"]
    assert abstained == {"N_SUC_05"}     # the king is described, not named: the gemma fallback


@needs_store
@pytest.mark.parametrize("gt", ["ground_truth.json", "ground_truth.v2.json"])
def test_store_gt_takes_no_card_and_the_blockers_drop_false_names(store_layer, gt):
    questions = [q["question"] for q in json.loads((REPO / gt).read_text(encoding="utf-8"))["questions"]]
    assert len(questions) == 500
    lay = store_layer
    assert not any(trigger(q, lay.names, lay.blockers).fired for q in questions)
    named = (sum(bool(trigger(q, lay.names).kings) for q in questions),
             sum(bool(trigger(q, lay.names, lay.blockers).kings) for q in questions), len(lay.blockers))
    assert named == NAMED[lay.sha256]
