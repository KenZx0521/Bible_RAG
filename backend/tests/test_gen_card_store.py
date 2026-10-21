"""The Genesis age card on the store's data (plan 2026-10-21 §3: A1 (a), (c), (d), A2 (2), A3).

The layer is the confirmation set's: gen_layer.json (reports/arith_stage0_20261020) and gen_names.json
(reports/gen_confirm_20261020) at their pinned sha256, read by ``gen_card.parse_files``; they also pass
``gen_card.load`` against build b20261019_a86f2b06's manifest (the text layer and routing lexicon they
were read from). The served build is b20261019_a86f2b06 with its regnal layer and lexicon, as in prod.

- A1 (a): the six files of utils/gencard are the F1 manifest's.
- A1 (c): the card /api/v1/query attaches to each of the 58 frozen confirmation questions is run/cards.json's
  ``g`` g_block where ``g`` is a card (48), and there is none where it is None (10); ``gref`` is never read.
  On stage-0's 18 GEN items the F1/F5 14 are its cards.json g_block and the 4 F3 items have none (stage-0's
  F3 cards are gold-seed cards the rule never writes).
- A1 (d): the generator's messages on those questions, with run/items.json's passages as the retrieval,
  are ``generator.build_messages`` on them, and on the 48 cards run/jobs.json's G prompts (rep 1).
- A2 (2): test_regnal_r4_cards' 62 pins again with this GEN layer served too: the same pins, every card
  regnal or none, and the GEN rule runs on exactly the items the regnal trigger does not take (D3).
- A3: the GEN rule fires on none of GT v1/v2 (500 each), experiment A's dev 30 and confirm 32, the regnal
  question sets p1/p2 and stage-0's dynasty items; the regnal trigger on none of the GEN confirm 58, P1,
  P2 and stage-0 GEN items; so no question takes both.

Question and card text stay in the store: assertions compare counts, ids and sha256 only, a count bound
to a name first (pytest prints the collection under a failing ``len(...) == n``). Skipped where the
store is absent. No LLM: the generator's is a fake that records its messages.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import test_regnal_r4_cards as R4
from ragcommon import routing
from routers import query
from serving import context
from serving.handshake import Handshake
from utils import gen_card, generator
from utils.regnal import card as card_mod
from utils.regnal.layer import parse_layer, with_lexicon
from utils.regnal.trigger import trigger as regnal_trigger

STORE = Path("/mnt/ollama-data/bible_rag_store")
REPO = Path(__file__).resolve().parents[2]
PKG = Path(gen_card.__file__).with_name("gencard")
GENC, STAGE0 = STORE / "reports/gen_confirm_20261020", STORE / "reports/arith_stage0_20261020"
GEN_LAYER, GEN_NAMES = STAGE0 / "gen_layer.json", GENC / "gen_names.json"
GEN_LAYER_SHA = "46d87abb29000d1210d0ee6fd5e045f7bf6ac08a2f1c034374a61c5e9c1aead5"
GEN_NAMES_SHA = "9e622e309615729011c8afa83beab739e5b68945bde10532bbf23f1738d0fe2d"
EXPERIMENT_PKG = "evaluation/experiments/2026-10-20_gen_confirm/gencard"
KG_CARDS, QSET = STORE / "reports/kg_cards_20261018", STORE / "reports/regnal_qset_20261019"
NEEDED = (GEN_LAYER, GEN_NAMES, GENC / "f1_manifest.json", GENC / "questions_frozen.json", GENC / "run/cards.json",
          GENC / "run/items.json", GENC / "run/jobs.json", GENC / "qset/p1/items.json", GENC / "qset/p2/items.json",
          STAGE0 / "items.json", STAGE0 / "cards.json", KG_CARDS / "A/items.json",
          KG_CARDS / "A_confirm/questions_frozen.json", QSET / "p1/items.json", QSET / "p2/items.json",
          R4.LAYER, R4.LEXICON, R4.CONTRACTS / "manifest.json")
pytestmark = pytest.mark.skipif(not all(p.is_file() for p in NEEDED),
                                reason="the GEN confirmation records or build b20261019_a86f2b06 not in the store")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _prompt_sha(system: str, user: str) -> str:
    return _sha(json.dumps([system, user], ensure_ascii=False))


@pytest.fixture(scope="module")
def gen():
    data, names = GEN_LAYER.read_bytes(), GEN_NAMES.read_bytes()
    assert (_sha(data), _sha(names)) == (GEN_LAYER_SHA, GEN_NAMES_SHA)
    return gen_card.parse_files(data, names)


@pytest.fixture(scope="module")
def regnal():
    """Build b20261019_a86f2b06's regnal layer with its lexicon attached, as make_active serves it."""
    return with_lexicon(parse_layer(R4.LAYER.read_bytes()), routing.load_lexicon(R4.LEXICON))


# ---------------------------------------------------------------- A1 (a) and the files
def test_the_six_files_are_the_f1_manifests():
    pins = _read(GENC / "f1_manifest.json")["files"]
    want = {Path(k).name: v for k, v in pins.items() if k.startswith(EXPERIMENT_PKG + "/")}
    files = sorted(p for p in PKG.iterdir() if p.name != "__pycache__")
    assert len(want) == 6 and {p.name: _sha(p.read_bytes()) for p in files} == want


def test_the_files_are_build_a86f2b06s_gen_layer(gen):
    manifest = _read(R4.CONTRACTS / "manifest.json")
    manifest = {**manifest, "files": {**manifest["files"], gen_card.LAYER_FILE: GEN_LAYER_SHA,
                                      gen_card.NAMES_FILE: GEN_NAMES_SHA}}
    files = {gen_card.LAYER_FILE: GEN_LAYER.read_bytes(), gen_card.NAMES_FILE: GEN_NAMES.read_bytes()}
    loaded = gen_card.load(manifest, files)
    assert loaded.gen_layer_sha256 == gen.gen_layer_sha256 == GEN_LAYER_SHA
    assert gen_card.chain_size(loaded) == {5: 10, 11: 9}


# ---------------------------------------------------------------- A1 (c), (d): the confirmation set
@pytest.fixture(scope="module")
def confirm(gen, regnal):
    """{sid: (aux_card, generator messages, item)} of the 58 frozen questions through /api/v1/query."""
    frozen = _read(GENC / "questions_frozen.json")["questions"]
    items = {it["sid"]: it for it in _read(GENC / "run/items.json")["items"]}
    n, same = len(frozen), sum(items[q["sid"]]["question"] == q["question"] for q in frozen)
    assert (n, same) == (58, 58)
    now: dict = {}

    async def intent(question):
        return {"type": "person", "entities": [], "verse_refs": [], "keywords": [], "rejected_refs": []}

    async def retrieve(**kwargs):
        return [dict(s) for s in now["sources"]], {"strategies_used": ["semantic"], "route_used": "R4"}

    class RecordingLlm:
        async def chat(self, messages, temperature, max_tokens):
            now["chats"].append(messages)
            return "答案：（假）"

    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(query, "classify_intent", intent)
        mp.setattr(query, "retrieve_and_rerank", retrieve)
        mp.setattr(card_mod, "get_llm_client", lambda: RecordingLlm())
        mp.setattr(generator, "get_llm_client", lambda: RecordingLlm())
        # make_active attaches the lexicon to the regnal layer itself
        context.install(context.make_active(R4.BUILD, routing.load_lexicon(R4.LEXICON), (),
                                            parse_layer(R4.LAYER.read_bytes()), gen),
                        Handshake(R4.BUILD.build_id, (), True))
        try:
            http = TestClient(main.app)
            for q in frozen:
                it = items[q["sid"]]
                now.update(sources=it["sources"], chats=[])
                body = http.post("/api/v1/query", json={"question": it["question"], "include_sources": False}).json()
                calls = len(now["chats"])
                assert calls == 1, f"{q['sid']}: {calls} LLM calls"
                out[q["sid"]] = (body["aux_card"], now["chats"][0], it)
        finally:
            context.reset()
    return out


def test_the_cards_are_the_confirmation_runs_g_cards(confirm):
    cards = _read(GENC / "run/cards.json")["cards"]
    outcome = Counter()
    for sid, (aux, _msgs, _it) in confirm.items():
        g = cards[sid]["g"]
        if g is None:
            outcome["none" if aux is None else f"{sid}: a card where g is None"] += 1
        elif aux is not None and aux["kind"] == "gen" and _sha(aux["text"]) == _sha(g["g_block"]) \
                and aux["kings"] == g["seeds"] and aux["lines"] == len(g["lines"]) \
                and aux["layer_sha256"] == GEN_LAYER_SHA and aux["seed_source"] == "rule":
            outcome["card"] += 1
        else:
            outcome[f"{sid}: not the g card"] += 1
    assert outcome == {"card": 48, "none": 10}


def test_the_stage0_gen_items_f1_f5_cards_and_f3_none(gen):
    items = [it for it in _read(STAGE0 / "items.json")["items"] if it["family"] == "GEN"]
    cards = _read(STAGE0 / "cards.json")["cards"]
    outcome = Counter()
    for it in items:
        c = gen_card.card_of(it["question"], gen)
        if it["qtype"] == "F3":
            outcome["F3 none" if c is None else f"{it['id']}: F3 card"] += 1
        else:
            same = c is not None and _sha(c.g_block) == _sha(cards[it["id"]]["g_block"])
            outcome["F1/F5 equal" if same else f"{it['id']}: differs"] += 1
    assert outcome == {"F1/F5 equal": 14, "F3 none": 4}


def test_the_prompts_are_build_messages_and_the_runs_g_prompts(confirm):
    jobs = {j["item"]: j for j in _read(GENC / "run/jobs.json") if j["arm"] == "G" and j["rep"] == 1}
    n_jobs = len(jobs)
    assert n_jobs == 48
    built = equal = 0
    for sid, (aux, msgs, it) in confirm.items():
        want = generator.build_messages(it["question"], generator.build_context(it["sources"]),
                                        aux["text"] if aux else None)
        built += msgs == want
        if sid in jobs:
            equal += _prompt_sha(msgs[0]["content"], msgs[1]["content"]) == \
                _prompt_sha(jobs[sid]["system"], jobs[sid]["user"])
    assert (built, equal) == (58, 48)
    assert sum(msgs[0]["content"] == generator.SYSTEM_PROMPT for aux, msgs, _it in confirm.values()
               if aux is None) == 10


# ---------------------------------------------------------------- A2 (2): the regnal pins, GEN served too
@pytest.fixture(scope="module", params=sorted(R4.RUNS))
def served_with_gen(request, gen):
    """(set, test_regnal_r4_cards.serve's items with the GEN layer served too, the items the GEN rule read)."""
    ran, real = [], gen_card.trigger

    def recording(question, L):
        ran.append(_sha(question))
        return real(question, L)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen_card, "trigger", recording)
        out = R4.serve(request.param, parse_layer(R4.LAYER.read_bytes()), gen)
    return request.param, out, ran


def test_the_regnal_pins_hold_with_the_gen_layer_served(served_with_gen):
    name, out, _ran = served_with_gen
    assert R4.pins_of((name, out)) == _read(R4.PINS)["cards"][name]
    assert {aux["kind"] for aux, *_rest in out.values() if aux is not None} == {"regnal"}


def test_the_gen_rule_reads_exactly_the_items_the_regnal_trigger_does_not_take(served_with_gen, regnal, gen):
    name, out, ran = served_with_gen
    silent = [i for i, (*_r, it) in out.items()
              if not regnal_trigger(it["question"], regnal.names, regnal.blockers).fired]
    assert [i for i, (*_r, it) in out.items() if _sha(it["question"]) in ran] == silent
    assert len(ran) == len(silent) == {"confirm": 0, "dev": 3}[name]


# ---------------------------------------------------------------- A3: the trigger lists
def _gt(name: str) -> list[tuple[str, str]]:
    return [(str(q.get("id", i)), q["question"]) for i, q in enumerate(_read(REPO / name)["questions"])]


def _regnal_sets() -> dict[str, list[tuple[str, str]]]:
    return {"gt_v1": _gt("ground_truth.json"), "gt_v2": _gt("ground_truth.v2.json"),
            "A_dev": [(x["id"], x["question"]) for x in _read(KG_CARDS / "A/items.json")["items"]],
            "A_confirm": [(x["id"], x["question"]) for x in
                          _read(KG_CARDS / "A_confirm/questions_frozen.json")["questions"]],
            "qset_p1": [(x["item_id"], x["question"]) for x in _read(QSET / "p1/items.json")["items"]],
            "qset_p2": [(x["item_id"], x["question"]) for x in _read(QSET / "p2/items.json")["items"]],
            "stage0_dynasty": [(x["id"], x["question"]) for x in _read(STAGE0 / "items.json")["items"]
                               if x["family"] != "GEN"]}


def _gen_sets() -> dict[str, list[tuple[str, str]]]:
    return {"gen_confirm": [(q["sid"], q["question"]) for q in _read(GENC / "questions_frozen.json")["questions"]],
            "gen_p1": [(x["item_id"], x["question"]) for x in _read(GENC / "qset/p1/items.json")["items"]],
            "gen_p2": [(x["item_id"], x["question"]) for x in _read(GENC / "qset/p2/items.json")["items"]],
            "stage0_gen": [(x["id"], x["question"]) for x in _read(STAGE0 / "items.json")["items"]
                           if x["family"] == "GEN"]}


def test_the_gen_rule_fires_on_no_question_outside_its_own_sets(gen):
    sets = _regnal_sets()
    assert {k: len(v) for k, v in sets.items()} == {"gt_v1": 500, "gt_v2": 500, "A_dev": 30, "A_confirm": 32,
                                                    "qset_p1": 75, "qset_p2": 63, "stage0_dynasty": 34}
    fired = {k: [i for i, q in v if gen_card.trigger(q, gen).fired or gen_card.card(q, gen) is not None]
             for k, v in sets.items()}
    assert fired == {k: [] for k in sets}


def test_the_regnal_trigger_fires_on_no_gen_question_and_no_question_takes_both(gen, regnal):
    sets = _gen_sets()
    assert {k: len(v) for k, v in sets.items()} == {"gen_confirm": 58, "gen_p1": 70, "gen_p2": 70, "stage0_gen": 18}
    fired = {k: [i for i, q in v if regnal_trigger(q, regnal.names, regnal.blockers).fired] for k, v in sets.items()}
    assert fired == {k: [] for k in sets}
    both = {k: [i for i, q in v if regnal_trigger(q, regnal.names, regnal.blockers).fired
                and gen_card.trigger(q, gen).fired] for k, v in (_regnal_sets() | sets).items()}
    assert both == {k: [] for k in both}
    assert sum(gen_card.trigger(q, gen).fired for q in (q for _i, q in sets["gen_confirm"])) == 48
