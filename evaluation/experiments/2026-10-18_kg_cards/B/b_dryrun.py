"""dry-run (CPU, no Ollama): freeze items, write seed jobs, simulate seeds with gold surfaces,
measure edge tables / cards / prompts (K0 slot cap), write the K0 review files and appendix_B.md.
Also checks that the base draw reproduces the K0-checked v0 items (store v0_k0checked/)."""
from __future__ import annotations

import collections
import hashlib
import json
import statistics

import b_appendix
import b_arms as A
import b_build as Bd
import b_card as Cd
import b_items as I
import b_k0 as K0
import b_lib as L
from b_lib import cc

ITEMS, DRYRUN = L.OUT / "items.json", L.OUT / "dryrun.json"
EXCLUSIONS = L.OUT / "gold_exclusions.json"
V0_ITEMS = L.OUT / "v0_k0checked/items.json"
PROMPTS = {"SYSTEM_PROMPT": cc.SYSTEM_PROMPT, "USER_TEMPLATE": cc.USER_TEMPLATE,
           "ANSWER_INSTRUCTION": cc.ANSWER_INSTRUCTION, "AUX_LABEL": cc.AUX_LABEL,
           "SEED_SYSTEM": A.SEED_SYSTEM, "SEED_USER": A.SEED_USER, "CHAIN_INSTRUCTION": A.CHAIN_INSTRUCTION,
           "TABLE_HEAD": A.TABLE_HEAD, "SLOT_HEAD": A.SLOT_HEAD}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dist(xs) -> dict:
    xs = sorted(xs)
    return dict(n=len(xs), min=xs[0], median=statistics.median(xs), max=xs[-1]) if xs else dict(n=0)


def user_chars(job: dict, cap: int) -> int:
    return len(job["user"]) if "user" in job else len(job["user_template"]) - len(A.SLOT) + cap


def code_shas() -> dict:
    files = sorted(L.HERE.glob("*.py")) + [L.HERE.parent / "cards_common.py"]
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def stats(items: list[dict], cards: dict, jobs: list[dict], seed_jobs: list[dict], cap: int) -> dict:
    aux = [A.aux_blocks(it) for it in items]
    by_arm = collections.defaultdict(list)
    for j in jobs:
        by_arm[f"{j['arm']}:{j['kind']}"].append(user_chars(j, cap))
    counts = collections.Counter(f"{j['arm']}:{j['kind']}:r{j['rep']}" for j in jobs)
    g = [c["G"] for c in cards.values()]
    return dict(
        edge_table_chars=dist([a["table_chars"] for a in aux]), n_edges=dist([a["n_edges"] for a in aux]),
        oracle_table_chars=dist([a["otable_chars"] for a in aux]),
        context_chars=dist([len(it["context"]) for it in items]),
        G_card_chars=dist([len(c["text"]) for c in g if c["status"] == "fire"]),
        GO_card_chars=dist([len(c["GO"]["text"]) for c in cards.values() if c["GO"]["status"] == "fire"]),
        G_fired=sum(c["status"] == "fire" for c in g),
        GO_fired=sum(c["GO"]["status"] == "fire" for c in cards.values()),
        G_card_vs_gold=dict(collections.Counter(c["card_judge"]["why"] for c in g if c["status"] == "fire")),
        G_abstain=dict(collections.Counter(c["reason"] for c in g if c["status"] != "fire")),
        layout=dict(collections.Counter(it["layout"]["cls"] for it in items)),
        n_dispersed=sum(it["layout"]["dispersed"] for it in items),
        user_chars_max={k: max(v) for k, v in sorted(by_arm.items())},
        user_chars_max_all=max(max(v) for v in by_arm.values()),
        seed_user_chars_max=max(len(j["user"]) for j in seed_jobs),
        jobs_by_arm=dict(sorted(counts.items())), n_arm_jobs=len(jobs), n_seed_jobs=len(seed_jobs),
        n_jobs_total=len(jobs) + len(seed_jobs))


def base_check(meta: dict) -> dict:
    """Base draw (v0 gold) vs the K0-checked v0 items.json, slot by slot."""
    if not V0_ITEMS.exists():
        return dict(v0=None)
    v0 = [I.item_uid(it) for it in L.load_json(V0_ITEMS)["items"]]
    return dict(v0=hashlib.sha256(V0_ITEMS.read_bytes()).hexdigest(), same=v0 == meta["base_uids"],
                n=len(v0))


def context_check(items: list[dict]) -> dict:
    """Every gold hop verse inside the item's context verses (R5 forces the gold units in)."""
    bad = [it["id"] for it in items if not set(it["hop_verses"]) <= set(it["verses"])]
    return dict(n=len(items), hop_verses_outside_context=bad)


def file_sha(path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def port_check(items: list[dict], cards: dict) -> dict:
    """Ported card vs the probe's own R5 card (verification only, read after selection)."""
    idx = {(r["pericope"], r["type"], tuple(r["ids"])): r["R5"]["card"] for r in L.items_eval()}
    same = 0
    for it in items:
        old, new = idx[(it["pericope"], it["type"], tuple(it["ids"]))], cards[it["id"]]["G"]["res"]
        same += (old["status"], old.get("reason"), old.get("sig")) == (new["status"], new.get("reason"), new.get("sig"))
    return dict(n=len(items), same=same)


def freeze_items(payload: dict) -> None:
    same = ITEMS.exists() and L.load_json(ITEMS) == json.loads(json.dumps(payload, ensure_ascii=False))
    if (L.OUT / "seeds.jsonl").exists() and ITEMS.exists() and not same:
        raise SystemExit("seeds.jsonl exists and the rebuilt items differ from items.json; refusing")
    cc.write_json(ITEMS, payload)


def run() -> dict:
    excluded = set(L.load_json(EXCLUSIONS)) if EXCLUSIONS.exists() else set()
    items, meta = Bd.build(excluded)
    freeze_items(dict(meta=meta, items=items))
    seed_jobs = [A.seed_job(it) for it in items]
    cc.write_json(L.OUT / "seed_jobs.json", seed_jobs)
    cards = {it["id"]: A.cards(it, A.simulated_seed(it)) for it in items}
    cap = A.longest_card(cards)
    jobs = A.arm_jobs(items, cards, cap)
    k0c, k0auto = K0.cards_sample(items, cards, meta["dev_pericopes"])
    gold20, gold48 = K0.gold_check(items)
    for name, obj in (("k0_cards_sample", k0c), ("k0_cards_auto", k0auto), ("k0_gold_check", gold20),
                      ("k0_gold_check_all", gold48)):
        cc.write_json(L.OUT / f"{name}.json", obj)
    dry = dict(meta=meta, slot_cap_chars_k0=cap, slot_max_lines=Cd.CARD_MAX_LINES,
               stats=dict(stats(items, cards, jobs, seed_jobs, cap), port_check=port_check(items, cards),
                          base_check=base_check(meta), context_check=context_check(items)),
               k0_cards=dict(n=k0c["n"], n_dev=k0c["n_dev"], recheck=k0c["recheck"], lost_from_v0=k0c["lost_from_v0"],
                             status={st: sum(c["status_vs_checked"] == st for c in k0c["cards"])
                                     for st in ("carried", "changed", "new")}),
               k0_gold=dict(recheck_20=gold20["recheck"], recheck_48=gold48["recheck"], status_48=gold48["status"]),
               sha256={"items.json": file_sha(ITEMS), "seed_jobs.json": file_sha(L.OUT / "seed_jobs.json"),
                       "gold_fixes.json": file_sha(L.GOLD_FIXES), "gold_exclusions.json": file_sha(EXCLUSIONS),
                       "prompts": {k: sha(v) for k, v in PROMPTS.items()}, "code": code_shas()},
               gold_fixes=dict(n_edges=L.gold_fixes()["n_edges"], n_labels=L.gold_fixes()["n_labels"]))
    cc.write_json(DRYRUN, dry)
    (L.HERE / "appendix_B.md").write_text(b_appendix.render(dry), encoding="utf-8")
    print(json.dumps({k: dry["stats"][k] for k in ("edge_table_chars", "G_card_chars", "user_chars_max_all",
                                                   "n_jobs_total", "G_fired", "GO_fired")}, ensure_ascii=False))
    return dry
