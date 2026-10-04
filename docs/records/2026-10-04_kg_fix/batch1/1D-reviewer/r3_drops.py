"""R3 (reviewer, independent): C6/C7 drop rules against staging Neo4j (READ only).

Own implementation of the plan text (not the planner's code):
  normalize: NFC + remove all whitespace/zero-width
  junk: len<2 | starts （ ( ＊ * | contains [0-9０-９] | ends 。，！？；」：   ('這是基督嗎？' and '(無標題)' allowed)
  stop: GENERIC_EVENT_STOPLIST (from cleanup_noise_entities) + 瑪拉 瑪撒 米利巴 耶和華曉諭 曉諭摩西 (Event only)
  dictname: normalized E/O/T name in PERSON/PLACE/GROUP dict keys or aliases
  order: twin merge first (survivor = clean twin) -> drops apply to remaining nodes
  protected: registry events+dropped, ALIAS_INJECTIONS, NEW_EVENTS, manual patch ids, place:dan, group:yehehua
Reports: drops by type/rule, Event MENTIONS removed (H10 delta), and which surviving
E/O/T names would still match R8's _is_junk_name or a digit rule (rule mismatch check).
"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(BIBLE_RAG_ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
from kg_validate.checks_r import _is_junk_name
from neo4j import GraphDatabase, READ_ACCESS

WS = re.compile(r"[\s　​‌‍﻿]")
norm = lambda s: WS.sub("", unicodedata.normalize("NFC", s or ""))
env = dotenv_values(ROOT / ".env")
drv = GraphDatabase.driver("bolt://localhost:7688", auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]),
                           notifications_min_severity="OFF")
with drv.session(default_access_mode=READ_ACCESS) as s:
    rows = s.execute_read(lambda tx: [r.data() for r in tx.run(
        "MATCH (e:Entity) OPTIONAL MATCH (src)-[m:MENTIONS]->(e) "
        "RETURN e.entity_id AS id, [l IN labels(e) WHERE l<>'Entity'][0] AS t, e.canonical_name AS n, count(m) AS men")])
drv.close()
E = {r["id"]: r for r in rows}

reg = json.load(open(ROOT / "backend/data/event_registry.json"))
prot = {e["id"] for e in reg["events"]} | {d["id"] for d in reg["dropped"]} | set(ALIAS_INJECTIONS) \
    | {e["entity_id"] for e in NEW_EVENTS} | {"place:dan", "group:yehehua"}
for line in (ROOT / "config/curated/manual_graph_patches.jsonl").read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    if r.get("entity_id"):
        prot.add(r["entity_id"])

dictnames = set()
for d in (PERSON_DICT, PLACE_DICT, GROUP_DICT):
    for k, v in d.items():
        dictnames |= {k, *v}

# twin merge (losers removed before drop rules)
WSid = re.compile(r"\s")
key = defaultdict(list)
for e, r in E.items():
    key[(r["t"], norm(r["n"]))].append(e)
losers = set()
for (t, n), ids in key.items():
    clean = [i for i in ids if not WSid.search(i) and E[i]["n"] == norm(E[i]["n"])]
    if len(ids) > 1 and len(clean) == 1:
        losers |= set(ids) - set(clean)

STOP = set(GENERIC_EVENT_STOPLIST)
EV09 = {"瑪拉", "瑪撒", "米利巴", "耶和華曉諭", "曉諭摩西"}


def rule(r):
    n = norm(r["n"])
    if n in {"這是基督嗎？", "(無標題)"}:
        return None
    if len(n) < 2: return "junk:short"
    if re.match(r"^[（(＊*]", n): return "junk:xref"
    if re.search(r"[0-9０-９]", n): return "junk:digit"
    if re.search(r"[。，！？；」：]$", n): return "junk:frag"
    if r["t"] == "Event" and n in STOP: return "stop:generic"
    if r["t"] == "Event" and n in EV09: return "stop:ev09"
    if n in dictnames: return "dictname"
    return None


drops, prot_hit = {}, []
for e, r in E.items():
    if e in losers or r["t"] not in ("Event", "Object", "Theme"):
        continue
    k = rule(r)
    if k and e in prot:
        prot_hit.append((e, r["n"], k)); continue
    if k:
        drops[e] = k
res = {
    "twin_losers": len(losers),
    "drops_by_type_rule": dict(Counter(f"{E[e]['t']}|{k}" for e, k in drops.items())),
    "drops_by_type": dict(Counter(E[e]["t"] for e in drops)),
    "protected_that_match_a_rule": prot_hit,
    "event_mentions_staging": sum(r["men"] for r in E.values() if r["t"] == "Event"),
    "event_mentions_removed": sum(E[e]["men"] for e in drops if E[e]["t"] == "Event"),
    "events_dropped": sum(1 for e in drops if E[e]["t"] == "Event"),
}
# survivors still junk by R8 (validator) or by a digit anywhere
surv = [e for e in E if e not in drops and e not in losers and E[e]["t"] in ("Event", "Object", "Theme")]
res["survivors_R8_junk_after_normalize"] = [E[e]["n"] for e in surv if _is_junk_name(norm(E[e]["n"]))][:20]
res["dash_led_events_kept"] = sum(1 for e in surv if E[e]["t"] == "Event" and norm(E[e]["n"]).startswith(("－", "-", "—")))
res["dropped_names_sample"] = {k: sorted(E[e]["n"] for e, kk in drops.items() if kk == k)[:12] for k in set(drops.values())}
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(Path(__file__).with_suffix(".json"), "w"), ensure_ascii=False, indent=1)
