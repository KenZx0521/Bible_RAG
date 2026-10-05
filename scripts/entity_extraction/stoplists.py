"""Shared stoplists for entity names (single source).

GENERIC_EVENT_STOPLIST is what Step 10.2 (cleanup_noise_entities --actions
generic-events) deletes, and what the offline Step 6.05 treats as already
gone. Batch 1D-C1 will add PLACE_FORMULA and JUNK_TITLE_ALLOW here and point
pericope_miner's GENERIC_TITLE_STOPLIST (the same 24 words, a second copy) at
this list.

Standard library only: 6.05 reads JSONL and connects to no database.
"""

# Generic-noun Event nodes: pericope-title artifacts, not biblical events.
# Kept: 饑荒/瘟疫/洪水/地震/節期/洗禮/登基... (real event semantics).
GENERIC_EVENT_STOPLIST = [
    "日子", "長子", "結局", "問候", "吩咐", "工程", "大會", "建築",
    "大事", "醜事", "使用", "艱難", "爭論", "坐席", "生日", "探子",
    "兒子", "時候", "事情", "話", "早晨", "晚上", "夜間", "明天",
]
