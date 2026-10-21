"""The r4 cards on the fixed regnal layer (relations@ee8e78c043d2, sha 252e0955…), pinned.

Every question of experiment A's confirmation set (32) and development set (30) goes through
/api/v1/query on a served build b20261019_a86f2b06 (its fixed layer and route lexicon, attached by
``make_active``): the router, ``card.chronology_card`` (trigger, rule seeds, the real ``seed_call``
only where the rules abstain, the S4 guard on) and ``generator.generate_answer``. Only the intent
call, retrieval (it returns the item's recorded passages) and the LLM are fakes; the LLM records
the messages it gets and answers a seed call with the run's recorded seed output, as Ollama returned
it. The card's seed source and text, and the generator's messages with it, must hash to
fixtures/regnal_r4_cards.json; the seed call must run only where the rules abstain, with
experiment A's seed prompt (``test_regnal_parity`` pins that prompt to the run's). The pins were
written from this code on 2026-10-19, after Kay's spot check of the layer; the cards and prompts are
the seed regression's (store reports/regnal_seed_20261019/dry_run, rule arm rep 1, its prompts put
together with experiment A's cards_common: 59/59 the same). The guard is recorded on the served
cards as in test_regnal_parity: it takes off born lines only, on the items GUARDED names.
In-sample: the rules were written after reading these questions. The fixture holds ids and sha256
only; card and question text stay in the store. Skipped where it is absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from ragcommon import routing
from ragcommon.regnal import born_guard
from routers import query
from serving import context
from serving.build import Build
from serving.handshake import Handshake
from utils import generator
from utils.regnal import card as card_mod
from utils.regnal import engine
from utils.regnal.layer import parse_layer
from utils.regnal.seeds import SEED_SYSTEM, seed_user

STORE = Path("/mnt/ollama-data/bible_rag_store")
CONTRACTS = STORE / "contracts/b20261019_a86f2b06"
LAYER, LEXICON = CONTRACTS / "regnal_layer.json", CONTRACTS / "routing_lexicon.json"
BUILD = Build("b20261019_a86f2b06", "bb20261019_a86f2b06", "passages__b20261019_a86f2b06", CONTRACTS, False,
              34058)
RUNS = {"confirm": STORE / "reports/kg_cards_20261018/A_confirm",
        "dev": STORE / "reports/kg_cards_20261018/A"}
PINS = Path(__file__).parent / "fixtures/regnal_r4_cards.json"
pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in (LAYER, LEXICON, *RUNS.values())),
    reason="experiment A records or the r4 build's contract files not in the store")
# the rules abstain on one question (the king is described, not named): the gemma fallback
SEED_CALLS = {"confirm": [], "dev": ["N_SUC_05"]}
# The S4 guard on the served cards: item -> {seed whose born line it takes off: born_guard's
# reason}. A15 is 亞哈謝 (J; 22 → 約沙法 against 42 → 亞撒), A38 約雅斤 (18 → 約西亞 against 8 →
# 約雅敬). The regnal-year dating of 約西亞 that took lines off 約哈斯 and 約雅敬 on the old layer
# is fixed by R10, so those lines stay. The gemma seeds of QJ3s2a1, QJ5s2a2 and T_S1_15 also
# name a guarded king; their rule seeds do not.
GUARDED = {"confirm": {"QJ1s2a2": {"A15": "alt:A15:age"}},
           "dev": {"T_S1_02": {"A15": "alt:A15:age"}, "T_S4_01": {"A15": "alt:A15:age"},
                   "T_S4_05": {"A38": "alt:A38:age"}}}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def layer():
    return parse_layer(LAYER.read_bytes())


@pytest.fixture(scope="module", params=sorted(RUNS))
def served(request, layer):
    """(set, {item: (aux_card, generator messages, seed-call messages, item)}) through /api/v1/query."""
    return request.param, serve(request.param, layer)


def serve(name: str, layer, gen_layer=None) -> dict:
    """One set's {item: (aux_card, generator messages, seed-call messages, item)}, with a GEN layer
    served too when given (test_gen_card_store)."""
    d = RUNS[name]
    items = json.loads((d / "items.json").read_text(encoding="utf-8"))["items"]
    seeds = {r["item"]: r.get("content") or "" for r in _jsonl(d / "gen_seed.jsonl") if r.get("type") == "answer"}
    now: dict = {}

    async def intent(question):
        return {"type": "person", "entities": [], "verse_refs": [], "keywords": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        return [dict(s) for s in now["sources"]], {"strategies_used": ["semantic"], "route_used": "R4"}

    class RecordingLlm:
        async def chat(self, messages, temperature, max_tokens):
            now["chats"].append(messages)
            return now["seed"] if messages[0]["content"] == SEED_SYSTEM else "答案：（假）"

    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(query, "classify_intent", intent)
        mp.setattr(query, "retrieve_and_rerank", retrieve)
        mp.setattr(card_mod, "get_llm_client", lambda: RecordingLlm())
        mp.setattr(generator, "get_llm_client", lambda: RecordingLlm())
        context.install(context.make_active(BUILD, routing.load_lexicon(LEXICON), (), layer, gen_layer),
                        Handshake(BUILD.build_id, (), True))
        try:
            http = TestClient(main.app)
            for it in items:
                now.update(sources=it["sources"], seed=seeds[it["id"]], chats=[])
                # include_sources only shapes the response's source list, not the card or the prompt
                body = http.post("/api/v1/query", json={"question": it["question"], "include_sources": False}).json()
                seed_chats = [m for m in now["chats"] if m[0]["content"] == SEED_SYSTEM]
                gen = [m for m in now["chats"] if m[0]["content"] != SEED_SYSTEM]
                assert len(gen) == 1, f"{name} {it['id']}: {len(gen)} generator calls"
                out[it["id"]] = (body["aux_card"], gen[0], seed_chats, it)
        finally:
            context.reset()
    return out


def pins_of(served) -> dict:
    """The fixture's entries for one set: {item: {seed_source, card_sha256, prompt_sha256} | None}."""
    _name, out = served
    pins = {}
    for item, (aux, gen, _seed_chats, _it) in out.items():
        if aux is None:
            pins[item] = None
            continue
        pins[item] = {"seed_source": aux["seed_source"], "card_sha256": _sha(aux["text"]),
                      "prompt_sha256": _sha(json.dumps([gen[0]["content"], gen[1]["content"]], ensure_ascii=False))}
    return pins


LAYER_SHA = "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"


def test_the_layer_is_the_fixed_one(layer):
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    assert layer.sha256 == pins["layer_sha256"] == LAYER_SHA
    assert hashlib.sha256(LEXICON.read_bytes()).hexdigest() == pins["lexicon_sha256"]


def test_the_cards_and_prompts_are_pinned(served):
    name, out = served
    assert pins_of(served) == json.loads(PINS.read_text(encoding="utf-8"))["cards"][name]
    for item, (aux, gen, _s, _it) in out.items():
        assert aux is None or aux["layer_sha256"] == LAYER_SHA, item
        system = generator.SYSTEM_PROMPT if aux is None else generator.SYSTEM_PROMPT_AUX
        assert gen[0]["content"] == system, f"{name} {item}"


def test_the_seed_call_runs_only_where_the_rules_abstain_with_the_experiments_prompt(served):
    name, out = served
    called = [i for i, (_a, _g, seed_chats, _it) in out.items() if seed_chats]
    assert called == SEED_CALLS[name]
    assert [i for i, (aux, *_rest) in out.items() if aux and aux["seed_source"] == "gemma"] == called
    for item in called:
        _aux, _gen, seed_chats, it = out[item]
        assert seed_chats == [[{"role": "system", "content": SEED_SYSTEM},
                               {"role": "user", "content": seed_user(generator.build_context(it["sources"]),
                                                                     it["question"])}]], item


def test_the_s4_guard_takes_off_born_lines_only_on_the_recorded_items(served, layer):
    name, out = served
    blocked = {}
    for item, (aux, *_rest) in out.items():
        if aux is None:
            continue
        on, off = engine.cards(layer.view, aux["kings"]), engine.cards(layer.view, aux["kings"], guard=False)
        assert aux["text"] == on["g_block"], f"{name} {item}: the card path is not guarded"
        lost = [t for t in off["tags"] if t not in on["tags"]]
        assert all(t[0] == "born" for t in lost), f"{name} {item}: {lost}"
        if lost:
            blocked[item] = {t[1]: born_guard(layer.view, t[1]) for t in lost}
    assert blocked == GUARDED[name]
