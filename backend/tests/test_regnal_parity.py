"""Plan A1: with the S4 guard off, the backend's card path sends experiment A's prompts byte for byte.

For every question of the blind confirmation set (32) and the development set (30), the
recorded seed output and passages go through the backend (parse_seeds, engine with
``guard=False``, generator) and must give the G-auto arm's recorded system and user prompts
exactly; where the arm abstained, the backend makes no card. The seed prompts must hash to the
run's recorded prompts_sha256. The guard (on by default, 2026-10-19) is recorded on the same
cards: it takes off born lines only, on the items and for the reasons GUARDED names. Reads the
store's experiment records; skipped where they are absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ragcommon.regnal import born_guard
from utils import generator
from utils.regnal import engine
from utils.regnal.card import card_from_seeds
from utils.regnal.layer import parse_layer
from utils.regnal.seeds import SEED_SYSTEM, seed_user

STORE = Path("/mnt/ollama-data/bible_rag_store")
LAYER = STORE / "layers/relations/relations@a04b67a301dc/regnal_layer.json"
RUNS = {"confirm": STORE / "reports/kg_cards_20261018/A_confirm",
        "dev": STORE / "reports/kg_cards_20261018/A"}
pytestmark = pytest.mark.skipif(not LAYER.is_file() or not all(d.is_dir() for d in RUNS.values()),
                                reason="experiment A records or the regnal layer not in the store")
# The S4 guard on this layer: item -> {seed whose born line it takes off: born_guard's reason}. A
# record, not a set-up to serve. 約西亞's reign conflict here (A36, 18) is a regnal-year dating
# (fixed by the layer rule R10), so 約哈斯 (A37) and 約雅敬 (A38) lose right lines besides 亞哈謝
# (A15) and 約雅斤 (A39); dev T_S4_02's is one the G-auto arm answered 2/2. 亞撒's dating (A04, 39)
# moves no king. The guard ships only with the fixed layer, in one image and release (integration
# plan §6), never with this one.
GUARD_A36 = "alt:A36:reign"
GUARDED = {"confirm": {"QJ1s2a2": {"A15": "alt:A15:age"}, "QJ3s2a1": {"A15": "alt:A15:age"},
                       "QJ4s1a1": {"A37": GUARD_A36}, "QJ4s2a1": {"A37": GUARD_A36, "A38": GUARD_A36},
                       "QJ5s1a2": {"A38": GUARD_A36}, "QJ5s2a2": {"A39": "alt:A39:age"}},
           "dev": {"N_TO_08": {"A37": GUARD_A36, "A38": GUARD_A36}, "T_S1_02": {"A15": "alt:A15:age"},
                   "T_S1_05": {"A37": GUARD_A36}, "T_S1_12": {"A38": GUARD_A36}, "T_S1_15": {"A15": "alt:A15:age"},
                   "T_S4_02": {"A38": GUARD_A36}, "T_S4_05": {"A39": "alt:A39:age"}}}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def layer():
    return parse_layer(LAYER.read_bytes())


@pytest.fixture
def unguarded(monkeypatch):
    """The card path's engine without the S4 guard, as experiment A ran it."""
    cards = engine.cards
    monkeypatch.setattr(engine, "cards", lambda V, seeds, **kw: cards(V, seeds, **{**kw, "guard": False}))


def _seed_text(rec: dict) -> str:
    return "" if rec.get("done_reason") == "length" else rec.get("content") or ""


@pytest.fixture(scope="module", params=sorted(RUNS))
def run(request):
    d = RUNS[request.param]
    items = json.loads((d / "items.json").read_text(encoding="utf-8"))["items"]
    seeds = {r["item"]: r for r in _jsonl(d / "gen_seed.jsonl") if r.get("type") == "answer"}
    jobs = json.loads((d / "arms_jobs.json").read_text(encoding="utf-8"))
    g_auto = {j["item"]: j for j in jobs if j["arm"] == "G-auto" and j["rep"] == 1}
    meta = json.loads((d / "run_meta_seeds.json").read_text(encoding="utf-8"))
    return request.param, items, seeds, g_auto, meta


def test_the_layer_is_the_audited_one(layer):
    assert layer.sha256 == "932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab"


def test_the_seed_prompts_are_the_experiments(run):
    name, items, _seeds, _g, meta = run
    prompts = [[f"A|{it['id']}|seed|1", SEED_SYSTEM, seed_user(generator.build_context(it["sources"]), it["question"])]
               for it in items]
    sha = hashlib.sha256(json.dumps(prompts, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert sha == meta["prompts_sha256"], name


def test_the_card_prompts_are_the_g_auto_arms(run, layer, unguarded):
    name, items, seeds, g_auto, _meta = run
    same, abstained = 0, 0
    for it in items:
        card = card_from_seeds(layer, it["question"], _seed_text(seeds[it["id"]]))
        if card is None:
            assert it["id"] not in g_auto, f"{name} {it['id']}: the arm wrote a card, the backend none"
            abstained += 1
            continue
        job = g_auto[it["id"]]
        system, user = generator.build_messages(it["question"], generator.build_context(it["sources"]), card.text)
        assert (system["content"], user["content"]) == (job["system"], job["user"]), f"{name} {it['id']}"
        same += 1
    assert same + abstained == len(items) and same == len(g_auto)


def test_the_s4_guard_takes_off_born_lines_only_on_the_recorded_items(run, layer):
    name, items, seeds, _g, _meta = run
    blocked = {}
    for it in items:
        card = card_from_seeds(layer, it["question"], _seed_text(seeds[it["id"]]))
        if card is None:
            continue
        on, off = engine.cards(layer.view, list(card.kings)), engine.cards(layer.view, list(card.kings), guard=False)
        assert card.text == on["g_block"], f"{name} {it['id']}: the card path is not guarded"
        lost = [t for t in off["tags"] if t not in on["tags"]]
        assert all(t[0] == "born" for t in lost), f"{name} {it['id']}: {lost}"
        assert on["lines"] == [ln for ln, t in zip(off["lines"], off["tags"]) if t in on["tags"]], f"{name} {it['id']}"
        assert set(off["rows"]) <= set(on["rows"]), f"{name} {it['id']}"
        if lost:
            blocked[it["id"]] = {t[1]: born_guard(layer.view, t[1]) for t in lost}
    assert blocked == GUARDED[name]
