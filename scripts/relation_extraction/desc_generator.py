"""P2-A — Generate grounded descriptions for entities lacking one.

Targets Person/Place/Group entities (4,223 records) whose `description` field
is empty in Neo4j. For each, fetches the canonical_name + a sample of
mentioning pericope titles and prompts a smaller LLM (default
gemma4:e4b-it-q8_0) for a <=80-character description constrained to the
provided context.

Usage:
    python -m scripts.relation_extraction.desc_generator \\
        [--target-types Person,Place,Group] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Optional

import httpx
from dotenv import load_dotenv
from neo4j import GraphDatabase

from .config import Neo4jConfig

load_dotenv()
logger = logging.getLogger("desc_generator")


SYSTEM_PROMPT = """你是聖經實體百科編輯。給定一個實體 (人/地/群體) 與該實體相關的若干段聖經敘事,
請用繁體中文寫一句 60 字以內的客觀描述。

嚴格規則:
1. 描述必須完全基於提供的上下文,**不可加入未提及的事實**。
2. 不可使用「可能」「或許」「相傳」等不確定字眼。
3. 不可重述實體名稱本身;直接寫角色或屬性。
4. 一句話即可,不需多句。

回應格式 (JSON):
{"description": "..."}"""


_FETCH_NEED_DESC_CYPHER = """
MATCH (e:Entity)
WHERE coalesce(e.description, '') = ''
  AND any(label IN labels(e) WHERE label IN $target_types)
OPTIONAL MATCH (e)<-[:MENTIONS]-(src)
WHERE src:Pericope OR src:Chunk
WITH e, src,
     CASE
       WHEN src:Pericope THEN src.title
       WHEN src:Chunk    THEN src.pericope_title
       ELSE NULL
     END AS title
WITH e, [t IN collect(DISTINCT title) WHERE t IS NOT NULL AND t <> ''][0..6] AS titles
RETURN e.entity_id AS entity_id,
       e.canonical_name AS canonical_name,
       e.aliases AS aliases,
       [l IN labels(e) WHERE l <> 'Entity'][0] AS type,
       titles
ORDER BY e.entity_id
"""

# Phrases that signal the LLM refused for lack of context. Saving any of these
# as a description would pollute the graph; we treat them as failures and skip.
_REFUSAL_MARKERS = ("我無法", "請提供", "JSON 回應", "JSON回應", "未提供")


_UPDATE_DESC_CYPHER = """
UNWIND $rows AS row
MATCH (e:Entity {entity_id: row.entity_id})
SET e.description = row.description
"""


def _fetch_targets(driver, target_types: list[str], limit: Optional[int]) -> list[dict]:
    with driver.session() as session:
        result = session.run(_FETCH_NEED_DESC_CYPHER, target_types=target_types)
        rows = [dict(r) for r in result]
    if limit:
        rows = rows[:limit]
    return rows


def _generate_description(
    client: httpx.Client,
    model: str,
    target: dict,
    num_ctx: int,
    num_predict: int,
) -> str:
    canonical = target["canonical_name"] or ""
    type_zh = target.get("type", "Entity")
    titles = target.get("titles") or []

    user_prompt = (
        f"實體名稱: {canonical}\n"
        f"類型: {type_zh}\n"
        f"出現於以下聖經段落:\n"
        + "\n".join(f"- {t}" for t in titles if t)
        + "\n\n請用 60 字以內、純客觀的描述總結這個實體在聖經中的角色或位置。"
    )

    response = client.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # Disable hidden reasoning — gemma4 *-it loops in thinking for some
            # entities (e.g. 艾城人 burnt 8192 tokens without producing JSON).
            # Same case finishes in ~55 tokens with think=false.
            "think": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        },
    )
    response.raise_for_status()
    payload = response.json()
    content = (payload.get("message") or {}).get("content", "")
    if not content:
        done_reason = payload.get("done_reason")
        eval_count = payload.get("eval_count")
        if done_reason == "length":
            raise RuntimeError(
                f"LLM truncated by num_predict={num_predict} (eval_count={eval_count}); "
                "raise DESC_NUM_PREDICT — reasoning models can emit hundreds of "
                "hidden thinking tokens before producing JSON."
            )
        raise RuntimeError(f"LLM returned empty content (done_reason={done_reason})")

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return str(data.get("description") or "").strip()
        except json.JSONDecodeError:
            pass

    return text[:80].replace("\n", " ").strip()


def _write_back(driver, rows: list[dict]) -> None:
    if not rows:
        return
    with driver.session() as session:
        session.run(_UPDATE_DESC_CYPHER, rows=rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-types", default="Person,Place,Group",
                        help="Comma-separated entity labels to target")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap entities processed (debug/dry runs)")
    parser.add_argument("--model", default=os.getenv("DESC_OLLAMA_MODEL", "gemma4:e4b-it-q8_0"))
    parser.add_argument("--base-url", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--num-ctx", type=int, default=int(os.getenv("DESC_NUM_CTX", "8192")))
    parser.add_argument("--num-predict", type=int, default=int(os.getenv("DESC_NUM_PREDICT", "2048")),
                        help="num_predict cap for the LLM. Reasoning models need "
                             ">=2048 to clear hidden thinking tokens before JSON.")
    parser.add_argument("--write-batch", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate but don't write to Neo4j")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    target_types = [t.strip() for t in args.target_types.split(",") if t.strip()]
    neo4j_cfg = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(neo4j_cfg.uri, auth=(neo4j_cfg.user, neo4j_cfg.password))

    targets = _fetch_targets(driver, target_types, args.limit)
    logger.info("Found %d entities lacking description (types=%s)", len(targets), target_types)
    if not targets:
        driver.close()
        return 0

    http = httpx.Client(
        base_url=args.base_url,
        timeout=httpx.Timeout(120.0, connect=15.0, read=120.0, write=15.0),
    )
    pending: list[dict] = []
    total_done = 0
    failed = 0

    skipped_no_context = 0
    skipped_refusal = 0
    try:
        for target in targets:
            if not (target.get("titles") or []):
                logger.warning("Skip %s (%s): no Pericope/Chunk context — "
                               "entity has no MENTIONS source",
                               target.get("entity_id"), target.get("canonical_name"))
                skipped_no_context += 1
                continue

            try:
                desc = _generate_description(
                    http, args.model, target, args.num_ctx, args.num_predict,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM failed for %s (%s): %s",
                               target.get("entity_id"), target.get("canonical_name"), e)
                failed += 1
                desc = ""
                time.sleep(2)

            if not desc:
                continue
            if any(marker in desc for marker in _REFUSAL_MARKERS):
                logger.warning("Skip %s (%s): LLM refused — context insufficient. "
                               "Reply preview: %s",
                               target.get("entity_id"),
                               target.get("canonical_name"),
                               desc[:60])
                skipped_refusal += 1
                continue

            pending.append({"entity_id": target["entity_id"], "description": desc})
            total_done += 1

            if not args.dry_run and len(pending) >= args.write_batch:
                _write_back(driver, pending)
                pending = []
                logger.info("Updated %d/%d (failed=%d)", total_done, len(targets), failed)

        if pending and not args.dry_run:
            _write_back(driver, pending)

    finally:
        http.close()
        driver.close()

    logger.info(
        "Done. generated=%d failed=%d skipped_no_context=%d skipped_refusal=%d "
        "(dry_run=%s)",
        total_done, failed, skipped_no_context, skipped_refusal, args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
