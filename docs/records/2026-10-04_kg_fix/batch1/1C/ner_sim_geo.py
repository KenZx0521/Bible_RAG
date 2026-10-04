# --- copy of cleanup_noise_entities.py:66-70, 167-183 (no import: module loads .env/neo4j)
PUNCT = set("，。；：、「」？！ \n\t^$（）－")
GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}
LIST_OK_PREV = {"和", "與", "同"} | PUNCT
def _geo_at(ctx, i):
    p = ctx[i - 1] if i > 0 else "^"
    n = ctx[i + 1] if i + 1 < len(ctx) else "$"
    if p in GEO_PREV and n != "以": return True
    if p in NAMING_PREV and (n in PUNCT or n == "$"): return True
    if p in LIST_OK_PREV and n == "、": return True
    if p == "、" and (n in PUNCT or n == "$"): return True
    return False
def is_geo_context(ctx):
    if "別是巴" in ctx: return True
    i = ctx.find("但")
    while i >= 0:
        if _geo_at(ctx, i): return True
        i = ctx.find("但", i + 1)
    return False
def is_geo_at(text, start):
    # position-specific variant: 別是巴 within ±30 or the rule at this 但
    lo, hi = max(0, start - 30), min(len(text), start + 31)
    return "別是巴" in text[lo:hi] or _geo_at(text, start)

