"""When a 「但」 mention of place:dan is the place name (shared rule).

「但」 is mostly a conjunction (但我/但你...) or part of another name (撒但/拿但業/
底但/亞比但/米但); only a few sources use it for the place (從但到別是巴,
金牛犢安在但, 支派地業列表...). Step 10.2 (cleanup_noise_entities --actions dan)
deletes every place:dan MENTIONS edge outside those sources, and the offline
Step 6.05 treats the same edges as absent, so both import this one module.

Standard library only: 6.05 reads JSONL and connects to no database.
"""

from __future__ import annotations

import json
from collections.abc import Container
from pathlib import Path

DAN_ID = "place:dan"

# --- place:dan geo classification (same rules validated on live data) ---
PUNCT = set("，。；：、「」？！ \n\t^$（）－")
GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}
LIST_OK_PREV = {"和", "與", "同"} | PUNCT


def is_geo_context(ctx: str) -> bool:
    if "別是巴" in ctx:
        return True
    i = ctx.find("但")
    while i >= 0:
        p = ctx[i - 1] if i > 0 else "^"
        n = ctx[i + 1] if i + 1 < len(ctx) else "$"
        if p in GEO_PREV and n != "以":
            return True
        if p in NAMING_PREV and (n in PUNCT or n == "$"):
            return True
        if p in LIST_OK_PREV and n == "、":
            return True
        if p == "、" and (n in PUNCT or n == "$"):
            return True
        i = ctx.find("但", i + 1)
    return False


def compute_dan_keep_sources(mentions_path: Path) -> set[str]:
    keep: set[str] = set()
    with mentions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if '"place:dan"' not in line:
                continue
            rec = json.loads(line)
            if rec.get("entity_id") != "place:dan":
                continue
            if is_geo_context(rec.get("context", "")):
                keep.add(rec["source_id"].split(":v:")[0])
    return keep


def keeps_dan_mention(entity_id: str, source_key: str, keep: Container[str]) -> bool:
    """Whether a mention survives the 10.2 「但」 filter.

    source_key is what action_dan compares against s.id: the pericope id for a
    verse row (source_id split at ':v:'), the source_id itself for a chunk or
    pericope row. keep is compute_dan_keep_sources(...). Mentions of any other
    entity always survive.
    """
    return entity_id != DAN_ID or source_key in keep
