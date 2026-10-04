"""R4 (reviewer): follow-up checks, no DB access.

  a) find_entity_by_name('利未') ranking after 1C (1C planner's FINAL NER sim ents) + 1D alias removal
  b) person:yeteluo rows after the 1C NER re-run (1C planner's rows_1c_pos_cfull.jsonl)
  c) PG entity_mentions projection (rows after 1D drops + dan edge-level keep)
  d) homophone collisions if whitespace ids were re-minted from clean names
  e) known-bad descriptions: in cache, not stale after 1C (1C expected_stale_FINAL.json)
"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re, sys
from collections import Counter
from pathlib import Path
from pypinyin import lazy_pinyin

ROOT = Path(BIBLE_RAG_ROOT); OUT = ROOT / "output"
SP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cleanup_noise_entities import compute_dan_keep_sources

jl = lambda p: (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())
res = {}

# a)
new = {r["entity_id"]: r for r in jl(SP / "1C/ents_1c_pos_cfull.jsonl")}
for r in jl(OUT / "frozen/grounded_entities.jsonl"):
    new.setdefault(r["entity_id"], r)
hits = sorted(((r.get("mention_count") or 0), e) for e, r in new.items()
              if "利未" in r["canonical_name"] or any("利未" in a for a in (r.get("aliases") or [])
                                                     if (e, a) != ("person:matai", "利未")))
res["a_liwei_rank_after_1C_1D"] = hits[::-1][:4]

# b)
c = Counter()
for r in jl(SP / "1C/rows_1c_pos_cfull.jsonl"):
    if r["entity_id"] == "person:yeteluo":
        c[f"{':'.join(r['source_id'].split(':v:')[0].split(':')[:3])}|{r['text_span']}"] += 1
res["b_yeteluo_rows_after_1C"] = dict(sorted(c.items()))

# c)
s4 = json.load(open(SP / "1D/s4_compile_1d.json"))["keep|Event+Object+Theme"]
drop = {m["old_id"] for m in s4["migration_rows"] if m["op"] == "drop"}
keep = compute_dan_keep_sources(OUT / "entity_mentions.jsonl")
tot = nd = ndan = dk = 0
for m in jl(OUT / "entity_mentions.jsonl"):
    tot += 1
    if m["entity_id"] in drop: nd += 1; continue
    if m["entity_id"] == "place:dan":
        if m["source_id"].split(":v:")[0] in keep: dk += 1
        else: ndan += 1
res["c_pg_rows"] = {"jsonl_rows": tot, "drop_rows": nd, "dan_removed": ndan, "dan_kept_rows": dk, "after": tot - nd - ndan}

# d)
WS = re.compile(r"[\s　]")
L = {}
for r in jl(OUT / "frozen/live_state/20261004/entities.jsonl"):
    L[r["entity_id"]] = ([x for x in r["labels"] if x != "Entity"][0], r["canonical_name"])
kept = json.load(open(Path(__file__).with_name("r1_twins.json")))["keep_ws"]
coll = []
for e in kept:
    t, n = L[e]; cn = WS.sub("", n)
    mint = f"{t.lower()}:{''.join(lazy_pinyin(cn))}"
    if mint in L and WS.sub("", L[mint][1]) != cn:
        coll.append(f"{e}({n.strip()}) -> {mint}({L[mint][1]})")
res["d_remint_homophone_collisions"] = coll

# e)
st = json.load(open(SP / "1C/expected_stale_FINAL.json"))
gone = {x["entity_id"] for x in st["stale"]} | {x["entity_id"] for x in st["missing"]}
cache = {}
for r in jl(OUT / "frozen/descriptions.jsonl"):
    cache.setdefault(r["entity_id"], []).append(r)
res["e_known_bad_exposed"] = {e: {"stale_after_1C": e in gone,
                                  "desc": [x["description"][:60] for x in cache.get(e, [])],
                                  "quality_flag": [x.get("quality_flag") for x in cache.get(e, [])]}
                              for e in ("person:maliya", "person:lajie")}
print(json.dumps(res, ensure_ascii=False, indent=1))
json.dump(res, open(Path(__file__).with_suffix(".json"), "w"), ensure_ascii=False, indent=1)
