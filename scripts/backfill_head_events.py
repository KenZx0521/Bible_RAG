#!/usr/bin/env python3
"""Backfill head-event aliases and curated Event nodes (P0-eval fix #2).

Context (docs/kg_p0_eval_p1_decision_2026-07-06.md §4.2#2): 31/54 backend
EVENT_KEYWORDS resolve to zero Event entities, so R4 graph_event comes back
empty for head questions like 最後的晚餐 / 王國分裂, and the entity_query
vector match cannot bridge modern phrasings either. Two repair modes, both
data-only (no re-extraction):

1. ALIAS_INJECTIONS — the event exists under a different canonical name
   (e.g. 王國分裂 → 北方的支派反叛). Merge the question-phrasing aliases into
   the existing node (native LIST, never json.dumps).
2. NEW_EVENTS — the extraction pipeline never produced the event (pericope
   captions were mangled synoptic references like 「(太26'26-30;可14'22-26」).
   Create a curated :Event:Entity node with verified Pericope MENTIONS
   anchors, marked ``source='head_event_backfill'`` for audit/rollback.

All anchor pericope ids in NEW_EVENTS were verified against live Neo4j
titles on 2026-07-06. Three stores stay in sync: Neo4j (retrieval truth),
PostgreSQL entities (bookkeeping), Qdrant bible_entities (re-embedded with
alias-enriched text so entity_query sees the new phrasings).

Rollback:
  * new nodes:  MATCH (e:Event {source:'head_event_backfill'}) DETACH DELETE e
                (plus PG DELETE and Qdrant delete by entity_id payload)
  * aliases:    restore from output/backups/head_events_<ts>.json

Usage:
    cd scripts && uv run python backfill_head_events.py [--dry-run] [--skip-qdrant]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from pypinyin import lazy_pinyin

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))

load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Curated mapping (anchors verified against live Neo4j pericope titles)
# ---------------------------------------------------------------------------

# Existing entity_id → question-phrasing aliases to merge in.
ALIAS_INJECTIONS: dict[str, list[str]] = {
    # 1ki:12:0 北方的支派反叛 — EVENT_008 王國分裂
    "event:beifangdezhipaifanpan": ["王國分裂", "南北國分裂", "以色列王國分裂", "羅波安王國分裂"],
    # act:9:0 掃羅的轉變 — EVENT_019 保羅歸主
    "event:saoluodezhuanbian": ["保羅歸主", "掃羅歸主", "保羅信主", "大馬士革路上遇見主"],
    # mat:14:1 / mrk:6:3 / luk:9:2 / jhn:6:0 — EVENT_012 五餅二魚
    "event:yesugeiwuqianrenchibao": ["五餅二魚", "給五千人吃飽", "五餅二魚神蹟"],
    # mat:17:0 / mrk:9:1 / luk:9:5
    "event:yesugaibianxingxiang": ["登山變像", "變像", "改變形像"],
    # 1sa:17:2
    "event:daweijishageliya": ["大衛與歌利亞", "大衛戰勝歌利亞", "大衛打敗歌利亞"],
    # act:7:1
    "event:zhongrenyongshitoudasisitifan": ["司提反殉道", "司提反被石頭打死"],
    # neh:3:0
    "event:chongjianyelusalengchengqiang": ["重建城牆", "尼希米重建城牆"],
    # gen:3:2
    "event:yadanghexiawabeiganchuyidianyuan": ["墮落", "人類的墮落", "始祖犯罪"],
    # exo:20:0 / deu:5:0 十誡
    "event:shijie": ["頒布律法", "西奈山頒布律法", "摩西領受律法"],
    # 2ki:25:2 猶大人被擄
    "event:youdarenbeilu": ["巴比倫之囚", "被擄巴比倫", "猶大被擄"],
    # num:13:0 十二個探子
    "event:shiergetanzi": ["探子窺地", "窺探迦南", "十二探子"],
}

# Curated new events. anchors = verified Pericope ids.
NEW_EVENTS: list[dict] = [
    {
        "canonical_name": "最後的晚餐",
        "aliases": ["主的晚餐", "設立聖餐", "逾越節晚餐"],
        "description": "耶穌受難前夕與十二門徒同守逾越節的筵席:設立聖餐(擘餅與杯)、為門徒洗腳、預言猶大出賣與彼得三次不認主。",
        "anchors": ["luk:22:1", "luk:22:2", "jhn:13:0", "jhn:13:1",
                    "mat:26:3", "mat:26:4", "mrk:14:3", "mrk:14:4"],
    },
    {
        "canonical_name": "客西馬尼禱告",
        "aliases": ["客西馬尼園禱告", "在客西馬尼禱告", "客西馬尼園的禱告", "橄欖山禱告"],
        "description": "最後晚餐後耶穌在客西馬尼園(橄欖山)極其傷痛地三次禱告「不要照我的意思,只要照你的意思」,門徒睡著,隨後猶大帶人捉拿耶穌。",
        "anchors": ["mat:26:6", "mrk:14:6", "luk:22:6"],
    },
    {
        "canonical_name": "五旬節聖靈降臨",
        "aliases": ["五旬節", "聖靈降臨", "聖靈澆灌"],
        "description": "五旬節門徒聚集,聖靈如大風與火舌降臨,眾人被聖靈充滿說起別國的話,彼得講道後三千人受洗,教會誕生。",
        "anchors": ["act:2:0", "act:2:1"],
    },
    {
        "canonical_name": "巴別塔",
        "aliases": ["巴別塔事件", "變亂口音"],
        "description": "洪水後人類在示拿地要建造塔頂通天的城和塔傳揚己名,耶和華變亂他們的口音,使他們分散在全地。",
        "anchors": ["gen:11:0"],
    },
    {
        "canonical_name": "十災",
        "aliases": ["埃及十災", "十個災殃", "降災給埃及"],
        "description": "耶和華藉摩西向法老降下十樣災殃:血、蛙、虱、蠅、畜疫、瘡、雹、蝗、黑暗、擊殺長子,迫使法老容以色列人離開埃及。",
        "anchors": ["exo:7:2", "exo:8:0", "exo:8:2", "exo:9:2",
                    "exo:10:0", "exo:10:1", "exo:11:0", "exo:12:3"],
    },
    {
        "canonical_name": "逾越節的設立",
        "aliases": ["逾越節", "第一個逾越節", "守逾越節"],
        "description": "出埃及前夕耶和華吩咐以色列人宰羔羊、把血塗在門框上,滅命的越過有血記號的家,擊殺埃及一切頭生的;此夜設立逾越節為永遠的定例。",
        "anchors": ["exo:12:0", "exo:12:2", "exo:12:5"],
    },
    {
        "canonical_name": "亞伯拉罕之約",
        "aliases": ["上帝與亞伯蘭立約", "割禮之約", "與亞伯拉罕立約"],
        "description": "上帝與亞伯蘭立約應許後裔如天上繁星、賜迦南地為業,並以割禮為立約的記號,改名亞伯拉罕作多國之父。",
        "anchors": ["gen:15:0", "gen:17:0"],
    },
    {
        "canonical_name": "金牛犢事件",
        "aliases": ["金牛犢", "鑄造金牛犢", "拜金牛犢"],
        "description": "摩西在西奈山上遲延未下,亞倫用金環鑄了牛犢,百姓獻祭跪拜;摩西下山怒摔法版,擊碎牛犢,利未人殺了三千人。",
        "anchors": ["exo:32:0"],
    },
    {
        "canonical_name": "曠野漂流",
        "aliases": ["曠野漂流四十年", "曠野四十年", "在曠野漂流"],
        "description": "十二探子報惡信後百姓埋怨不肯進迦南,耶和華懲罰那世代在曠野漂流四十年,倒斃曠野,唯迦勒與約書亞得進應許之地。",
        "anchors": ["num:14:0", "num:14:2", "num:14:3"],
    },
    {
        "canonical_name": "道成肉身",
        "aliases": ["太初有道", "道成了肉身"],
        "description": "太初與上帝同在的道成了肉身,住在我們中間,充充滿滿地有恩典有真理,將父上帝表明出來。",
        "anchors": ["jhn:1:0"],
    },
    {
        "canonical_name": "耶路撒冷大會",
        "aliases": ["耶路撒冷會議", "使徒會議"],
        "description": "使徒和長老在耶路撒冷聚會,議定外邦信徒不必受割禮守摩西律法,只要禁戒祭偶像之物、血、勒死的牲畜和姦淫,並發覆函通知眾教會。",
        "anchors": ["act:15:0", "act:15:1"],
    },
    {
        "canonical_name": "末日的審判",
        "aliases": ["末日審判", "最後審判", "白色大寶座審判"],
        "description": "末日死了的人都站在白色大寶座前,案卷展開,照各人所行的受審判;名字沒有記在生命冊上的被扔進火湖。",
        "anchors": ["rev:20:2"],
    },
    {
        "canonical_name": "新天新地",
        "aliases": ["新耶路撒冷", "聖城新耶路撒冷"],
        "description": "先前的天地過去,聖城新耶路撒冷由上帝那裡從天而降;上帝要親自與人同住,擦去一切眼淚,不再有死亡、悲哀、哭號、疼痛。",
        "anchors": ["rev:21:0", "rev:21:1"],
    },
    {
        "canonical_name": "耶穌被釘十字架",
        "aliases": ["釘十字架", "耶穌受難", "十字架受死", "各各他"],
        "description": "耶穌被兵丁戲弄後帶到各各他釘十字架,與兩個強盜同釘;遍地黑暗,耶穌大聲喊叫斷氣,殿裡的幔子從上到下裂為兩半。",
        "anchors": ["mat:27:5", "mat:27:6", "mrk:15:3", "luk:23:3", "jhn:19:1"],
    },
    {
        "canonical_name": "耶穌受洗",
        "aliases": ["耶穌接受約翰的洗", "在約旦河受洗"],
        "description": "耶穌從加利利來到約旦河受施洗約翰的洗,天忽然開了,聖靈彷彿鴿子降在他身上,天上有聲音說「這是我的愛子,我所喜悅的」。",
        "anchors": ["mat:3:1", "mrk:1:1", "luk:3:1"],
    },
    {
        "canonical_name": "掃羅受膏作王",
        "aliases": ["掃羅受膏", "掃羅作王", "撒母耳膏掃羅"],
        "description": "撒母耳私下用膏油膏掃羅作以色列的君王,後在米斯巴掣籤公開立掃羅,眾民呼喊「願王萬歲」,以色列從此進入王國時期。",
        "anchors": ["1sa:9:1", "1sa:10:1"],
    },
    {
        "canonical_name": "所羅門建造聖殿",
        "aliases": ["建造聖殿", "所羅門獻殿", "奉獻聖殿", "獻殿禮"],
        "description": "所羅門用七年建造耶路撒冷聖殿,將約櫃運入至聖所,雲充滿殿宇;所羅門獻上獻殿禱告與祭物,將殿分別為聖歸給耶和華。",
        "anchors": ["1ki:6:0", "1ki:8:0", "1ki:8:2", "1ki:8:4"],
    },
    {
        "canonical_name": "第一次宣教旅程",
        "aliases": ["保羅第一次宣教旅程", "第一次佈道旅程"],
        "description": "聖靈差遣巴拿巴和掃羅從安提阿出發,經塞浦路斯、彼西底的安提阿、以哥念、路司得傳道,建立外邦教會後回到安提阿。",
        "anchors": ["act:13:0", "act:13:1", "act:13:2", "act:14:0", "act:14:2"],
    },
]


def _pinyin_id(name: str) -> str:
    return "event:" + "".join(lazy_pinyin(name))


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

def get_neo4j():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def get_pg():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "bible_rag"),
        user=os.getenv("POSTGRES_USER", "bible"),
        password=os.getenv("POSTGRES_PASSWORD", "bible_password"),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(session) -> list[dict]:
    """Check alias targets exist, anchors exist, and new ids don't collide.

    Returns the NEW_EVENTS list enriched with entity_id, or raises.
    """
    problems: list[str] = []

    rows = session.run(
        "UNWIND $ids AS eid OPTIONAL MATCH (e:Event {entity_id: eid}) "
        "RETURN eid, e.canonical_name AS name",
        ids=list(ALIAS_INJECTIONS.keys()),
    )
    for r in rows:
        if r["name"] is None:
            problems.append(f"alias target missing in graph: {r['eid']}")

    all_anchors = sorted({a for ev in NEW_EVENTS for a in ev["anchors"]})
    rows = session.run(
        "UNWIND $ids AS pid OPTIONAL MATCH (p:Pericope {id: pid}) "
        "RETURN pid, p.id AS found",
        ids=all_anchors,
    )
    for r in rows:
        if r["found"] is None:
            problems.append(f"anchor pericope missing: {r['pid']}")

    enriched: list[dict] = []
    for ev in NEW_EVENTS:
        eid = _pinyin_id(ev["canonical_name"])
        rec = session.run(
            "OPTIONAL MATCH (e {entity_id: $eid}) RETURN e.canonical_name AS name",
            eid=eid,
        ).single()
        existing = rec["name"] if rec else None
        if existing is not None and existing != ev["canonical_name"]:
            problems.append(
                f"pinyin id collision: {eid} already used by {existing!r} "
                f"(wanted {ev['canonical_name']!r})"
            )
        enriched.append({**ev, "entity_id": eid})

    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        raise SystemExit("validation failed — nothing written")
    return enriched


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

_MERGE_ALIAS_CYPHER = """
UNWIND $rows AS row
MATCH (e:Event {entity_id: row.eid})
WITH e, coalesce(e.aliases, []) + row.aliases AS combined
SET e.aliases = apoc.coll.toSet([x IN combined WHERE x <> e.canonical_name])
RETURN count(e) AS updated
"""

_CREATE_EVENT_CYPHER = """
UNWIND $rows AS row
MERGE (e:Event:Entity {entity_id: row.entity_id})
ON CREATE SET e.created_from = 'head_event_backfill'
SET e.canonical_name = row.canonical_name,
    e.aliases = row.aliases,
    e.description = row.description,
    e.mention_count = size(row.anchors),
    e.extraction_method = 'curated',
    e.source = 'head_event_backfill'
WITH e, row
UNWIND row.anchors AS pid
MATCH (p:Pericope {id: pid})
MERGE (p)-[m:MENTIONS]->(e)
ON CREATE SET m.curated = true, m.source = 'head_event_backfill'
RETURN count(DISTINCT e) AS events, count(*) AS edges
"""


def backup_state(session, new_events: list[dict]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _PROJECT_ROOT / "output" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"head_events_{ts}.json"

    rows = session.run(
        "UNWIND $ids AS eid MATCH (e:Event {entity_id: eid}) "
        "RETURN eid, e.canonical_name AS name, e.aliases AS aliases",
        ids=list(ALIAS_INJECTIONS.keys()),
    )
    snapshot = {
        "alias_targets_before": [dict(r) for r in rows],
        "new_event_ids": [ev["entity_id"] for ev in new_events],
        "rollback": {
            "new_nodes": "MATCH (e:Event {source:'head_event_backfill'}) DETACH DELETE e",
            "aliases": "restore alias_targets_before via SET e.aliases",
        },
    }
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return path


def write_neo4j(session, new_events: list[dict]) -> None:
    alias_rows = [{"eid": eid, "aliases": aliases} for eid, aliases in ALIAS_INJECTIONS.items()]
    rec = session.run(_MERGE_ALIAS_CYPHER, rows=alias_rows).single()
    print(f"  Neo4j aliases merged into {rec['updated']} existing events")

    rec = session.run(_CREATE_EVENT_CYPHER, rows=new_events).single()
    print(f"  Neo4j curated events: {rec['events']} nodes / {rec['edges']} MENTIONS edges")


def write_pg(conn, new_events: list[dict]) -> None:
    with conn.cursor() as cur:
        for eid, aliases in ALIAS_INJECTIONS.items():
            cur.execute(
                """
                UPDATE entities
                SET aliases = (
                    SELECT jsonb_agg(DISTINCT x) FROM (
                        SELECT jsonb_array_elements_text(coalesce(aliases, '[]'::jsonb)) AS x
                        UNION
                        SELECT unnest(%s::text[])
                    ) t WHERE x <> canonical_name
                )
                WHERE entity_id = %s
                """,
                (aliases, eid),
            )
        for ev in new_events:
            cur.execute(
                """
                INSERT INTO entities (entity_id, type, canonical_name, aliases,
                                      description, extraction_method, mention_count)
                VALUES (%s, 'Event', %s, %s::jsonb, %s, 'curated', %s)
                ON CONFLICT (entity_id) DO UPDATE
                    SET canonical_name = EXCLUDED.canonical_name,
                        aliases = EXCLUDED.aliases,
                        description = EXCLUDED.description,
                        mention_count = EXCLUDED.mention_count
                """,
                (ev["entity_id"], ev["canonical_name"],
                 json.dumps(ev["aliases"], ensure_ascii=False),
                 ev["description"], len(ev["anchors"])),
            )
    conn.commit()
    print(f"  PG: {len(ALIAS_INJECTIONS)} alias updates + {len(NEW_EVENTS)} curated rows upserted")


def reembed_qdrant(touched_ids: list[str]) -> None:
    """Re-embed touched entities into bible_entities with alias-enriched text."""
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels
    from embeddings.embedder import BGEEmbedder
    from embed_entities import _build_text, _entity_uuid, COLLECTION_NAME

    fetch_cypher = """
    MATCH (e:Entity) WHERE e.entity_id IN $ids
    OPTIONAL MATCH (e)<-[:MENTIONS]-(src)
    WHERE src:Pericope OR src:Chunk
    OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(src)
    WITH e, src, parent,
         CASE WHEN src:Pericope THEN src.title
              WHEN src:Chunk    THEN src.pericope_title ELSE NULL END AS title,
         CASE WHEN src:Pericope THEN src.id
              WHEN src:Chunk    THEN coalesce(parent.id, src.pericope_id) ELSE NULL END AS pid
    WITH e,
         [t IN collect(DISTINCT title) WHERE t IS NOT NULL AND t <> ''][0..5] AS pericope_titles,
         [i IN collect(DISTINCT pid)   WHERE i IS NOT NULL AND i <> ''][0..5] AS pericope_ids
    RETURN e.entity_id AS entity_id,
           e.canonical_name AS canonical_name,
           e.aliases AS aliases,
           coalesce(e.description, '') AS description,
           [l IN labels(e) WHERE l <> 'Entity'][0] AS type,
           pericope_titles, pericope_ids
    """
    driver = get_neo4j()
    try:
        with driver.session() as session:
            entities = [dict(r) for r in session.run(fetch_cypher, ids=touched_ids)]
    finally:
        driver.close()

    if len(entities) != len(touched_ids):
        missing = set(touched_ids) - {e["entity_id"] for e in entities}
        raise SystemExit(f"qdrant re-embed: entities missing from graph: {missing}")

    embedder = BGEEmbedder(device=None, normalize=True)
    if hasattr(embedder, "load_model"):
        embedder.load_model()
    texts = [_build_text(e) for e in entities]
    vectors = embedder.encode_batch(texts, batch_size=16, show_progress=False)

    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_HTTP_PORT", "6333")),
    )
    try:
        points = []
        for entity, vector in zip(entities, vectors):
            points.append(qmodels.PointStruct(
                id=_entity_uuid(entity["entity_id"]),
                vector=vector,
                payload={
                    "entity_id": entity["entity_id"],
                    "type": entity.get("type") or "",
                    "canonical_name": entity.get("canonical_name") or "",
                    "aliases": entity.get("aliases") or [],
                    "description": entity.get("description") or "",
                    "pericope_titles": entity.get("pericope_titles") or [],
                    "pericope_ids": entity.get("pericope_ids") or [],
                },
            ))
        client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    finally:
        client.close()
    print(f"  Qdrant: re-embedded {len(points)} entities into {COLLECTION_NAME}")


def smoke_test(session) -> None:
    """Simulate backend find_events_by_keyword for the benchmark phrasings."""
    print("\nSmoke test (find_events_by_keyword simulation):")
    for kw in ["最後的晚餐", "王國分裂", "客西馬尼禱告", "保羅歸主", "五旬節", "十災", "五餅二魚"]:
        rows = session.run(
            "MATCH (e:Event) WHERE e.canonical_name CONTAINS $kw "
            "   OR any(a IN e.aliases WHERE a CONTAINS $kw) "
            "OPTIONAL MATCH (p:Pericope)-[:MENTIONS]->(e) "
            "WITH e, collect(p.id)[0..4] AS anchors "
            "RETURN e.canonical_name AS name, anchors "
            "ORDER BY e.mention_count DESC LIMIT 3",
            kw=kw,
        ).data()
        hits = "; ".join(f"{r['name']}→{r['anchors']}" for r in rows) or "∅ MISS"
        print(f"  {kw}: {hits}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-qdrant", action="store_true",
                        help="skip the BGE re-embed step (Neo4j/PG only)")
    args = parser.parse_args()

    driver = get_neo4j()
    try:
        with driver.session() as session:
            print("Validating curated mapping against live graph...")
            new_events = validate(session)
            print(f"  ✓ {len(ALIAS_INJECTIONS)} alias targets, "
                  f"{len(new_events)} new events, all anchors resolved")

            if args.dry_run:
                for ev in new_events:
                    print(f"  [new] {ev['entity_id']}  {ev['canonical_name']}  "
                          f"anchors={ev['anchors']}")
                print("Dry run — nothing written.")
                return 0

            backup = backup_state(session, new_events)
            print(f"  Backup written: {backup}")

            write_neo4j(session, new_events)

        conn = get_pg()
        try:
            write_pg(conn, new_events)
        finally:
            conn.close()

        touched = list(ALIAS_INJECTIONS.keys()) + [ev["entity_id"] for ev in new_events]
        if args.skip_qdrant:
            print("  Qdrant re-embed skipped (--skip-qdrant)")
        else:
            reembed_qdrant(touched)

        with driver.session() as session:
            smoke_test(session)
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
