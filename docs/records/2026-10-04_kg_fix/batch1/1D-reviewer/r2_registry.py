"""R2 (reviewer, independent): registry under the 1D alias-ambiguity filter.

Source: staging Neo4j (bolt://localhost:7688, READ session only) = batch-0 equivalent of live.
Not the planner's JSONL projection. Applies the plan's C8 rule to every entity:
  alias a of e is ambiguous if  |owners(a)| >= 2  OR  a == canonical of another entity
                             OR  a belongs to >= 2 dictionary entries (P/P/G dicts)
Variants: (1) curated (entity, alias) pairs exempt, (2) no exemption.
Registry recomputed with the real export_event_registry.registry_from_rows.
Also: which registry triggers are aliases at all (vs canonical names).
"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
from collections import defaultdict
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(BIBLE_RAG_ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
import export_event_registry as exr  # real code (read-only use)
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
from neo4j import GraphDatabase, READ_ACCESS

env = dotenv_values(ROOT / ".env")
drv = GraphDatabase.driver("bolt://localhost:7688", auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
                           notifications_min_severity="OFF")


def q(cy, **p):
    with drv.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(cy, **p)])


ents = q("MATCH (e:Entity) RETURN e.entity_id AS id, e.canonical_name AS name, coalesce(e.aliases,[]) AS aliases")
curated = exr.curated_event_ids()
anchor_rows = q(exr._ANCHOR_QUERY, ids=sorted(curated))
drv.close()

cur_pairs = set()
for eid, al in ALIAS_INJECTIONS.items():
    cur_pairs |= {(eid, a) for a in al}
for ev in NEW_EVENTS:
    cur_pairs |= {(ev["entity_id"], a) for a in ev["aliases"]}
for line in (ROOT / "config/curated/manual_graph_patches.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if r.get("kind") == "node":
        cur_pairs |= {(r["entity_id"], a) for a in r["props"].get("aliases") or []}

dict_owner = defaultdict(set)
for t, d in (("Person", PERSON_DICT), ("Place", PLACE_DICT), ("Group", GROUP_DICT)):
    for k, v in d.items():
        for a in {k, *v}:
            dict_owner[a].add((t, k))

owners, canon = defaultdict(set), defaultdict(set)
for e in ents:
    canon[e["name"]].add(e["id"])
    for a in e["aliases"]:
        owners[a].add(e["id"])


def filtered_aliases(exempt: bool):
    out = {}
    moved = []
    for e in ents:
        keep = []
        for a in e["aliases"]:
            amb = len(owners[a]) > 1 or bool(canon.get(a, set()) - {e["id"]}) or len(dict_owner.get(a, ())) > 1
            if amb and not (exempt and (e["id"], a) in cur_pairs):
                moved.append((e["id"], a))
            else:
                keep.append(a)
        out[e["id"]] = keep
    return out, moved


committed = json.loads((ROOT / "backend/data/event_registry.json").read_text(encoding="utf-8"))
kw, order = exr.event_keywords(), exr.load_book_order()
res = {}
for exempt in (True, False):
    al, moved = filtered_aliases(exempt)
    rows = [{**r, "aliases": al.get(r["id"], r["aliases"])} for r in anchor_rows]
    reg = exr.registry_from_rows(rows, curated, kw, order)
    lost = sorted({e["id"] for e in committed["events"]} - {e["id"] for e in reg["events"]})
    trig_changed = sorted(e["id"] for e in reg["events"]
                          if e["triggers"] != next(c for c in committed["events"] if c["id"] == e["id"])["triggers"])
    res["exempt" if exempt else "no_exempt"] = {
        "moved_pairs": len(moved), "moved_entities": len({m[0] for m in moved}),
        "moved": sorted(moved) if len(moved) < 40 else sorted(moved)[:40],
        "events": len(reg["events"]), "equals_committed": exr._comparable(reg) == exr._comparable(committed),
        "events_lost": lost, "events_with_changed_triggers": trig_changed,
    }
# which committed triggers rely on an alias (not on the canonical name)
alias_only = []
names = {r["id"]: r["name"] for r in anchor_rows}
for e in committed["events"]:
    for t in e["triggers"]:
        if t != names[e["id"]]:
            alias_only.append((e["id"], t))
res["committed_triggers_from_alias"] = len(alias_only)
res["committed_triggers_from_alias_not_curated"] = sorted(p for p in alias_only if p not in cur_pairs)
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(Path(__file__).with_suffix(".json"), "w"), ensure_ascii=False, indent=1)
