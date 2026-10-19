"""Plan A1: the backend's card path sends experiment A's prompts byte for byte.

For every question of the blind confirmation set (32) and the development set (30), the
recorded seed output and passages go through the backend (parse_seeds, engine, generator)
and must give the G-auto arm's recorded system and user prompts exactly; where the arm
abstained, the backend makes no card. The seed prompts must hash to the run's recorded
prompts_sha256. Reads the store's experiment records; skipped where they are absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from utils import generator
from utils.regnal.card import card_from_seeds
from utils.regnal.layer import parse_layer
from utils.regnal.seeds import SEED_SYSTEM, seed_user

STORE = Path("/mnt/ollama-data/bible_rag_store")
LAYER = STORE / "layers/relations/relations@a04b67a301dc/regnal_layer.json"
RUNS = {"confirm": STORE / "reports/kg_cards_20261018/A_confirm",
        "dev": STORE / "reports/kg_cards_20261018/A"}
pytestmark = pytest.mark.skipif(not LAYER.is_file() or not all(d.is_dir() for d in RUNS.values()),
                                reason="experiment A records or the regnal layer not in the store")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def layer():
    return parse_layer(LAYER.read_bytes())


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


def test_the_card_prompts_are_the_g_auto_arms(run, layer):
    name, items, seeds, g_auto, _meta = run
    same, abstained = 0, 0
    for it in items:
        rec = seeds[it["id"]]
        text = "" if rec.get("done_reason") == "length" else rec.get("content") or ""
        card = card_from_seeds(layer, it["question"], text)
        if card is None:
            assert it["id"] not in g_auto, f"{name} {it['id']}: the arm wrote a card, the backend none"
            abstained += 1
            continue
        job = g_auto[it["id"]]
        system, user = generator.build_messages(it["question"], generator.build_context(it["sources"]), card.text)
        assert (system["content"], user["content"]) == (job["system"], job["user"]), f"{name} {it['id']}"
        same += 1
    assert same + abstained == len(items) and same == len(g_auto)
