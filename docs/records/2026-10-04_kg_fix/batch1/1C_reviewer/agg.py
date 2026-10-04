import json, collections
from edges import *
F, Frows = edges_of("rrows_final.jsonl")
title_only = sum(1 for k, rs in Frows.items() if all(r["region"] == "title" for r in rs))
first_title_but_body = sum(1 for k, rs in Frows.items() if rs[0]["region"] == "title" and any(r["region"] == "body" for r in rs))
# sorted by start_pos then first (master plan's "sort by start_pos")
sort_first_title = 0
for k, rs in Frows.items():
    r0 = min(rs, key=lambda r: r["start_pos"])
    if r0["region"] == "title" and any(r["region"] == "body" for r in rs): sort_first_title += 1
both = sum(1 for k, rs in Frows.items() if k[0] == "Pericope" and {r["source_type"] for r in rs} >= {"pericope", "verse"})
verse_only = sum(1 for k, rs in Frows.items() if k[0] == "Pericope" and {r["source_type"] for r in rs} == {"verse"})
print("edges", len(F), "title_only", title_only, "first-row title though body exists", first_title_but_body,
      "min-start title though body", sort_first_title, "pericope+verse", both, "verse-only", verse_only)
# E/O/T: does the import aggregate touch E/O/T? count Event edges in merged entity_mentions
