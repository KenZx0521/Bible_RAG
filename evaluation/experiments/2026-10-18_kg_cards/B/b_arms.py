"""Seed (anchor) jobs and parser, cards, and the arm jobs of experiment B (prereg §3).

Arms: G (edge table + program card), T1C (T-1hop+CoT: edge table + gemma's own chain, two
stages), TLLM (gemma's own chain, no edges, two stages), B0 (no auxiliary block), GO (G-oracle:
the TIPNR (fixed gold) surface-triple table + its card under the same rules; 理想上限 only). Run order: rep -> item -> arm, the
arm order rotated by the item's index; each stage-1 job sits right before its stage-2 job.
"""
from __future__ import annotations

import re
import unicodedata

import b_card as Cd
import b_gold as Gd
import b_lib as L
import b_terms as Tm
from b_lib import cc

SEED_SYSTEM = "你是一個資訊抽取工具，只輸出要求的內容。"
SEED_USER = ("請找出下面問題中的人名，最多 2 個。每行輸出一個人名，照問題中的原字，"
             "不要加編號、標點或其他文字。\n\n問題：{question}")
CHAIN_INSTRUCTION = ("這一步先不要作答：只寫出與問題相關的世代鏈，最多 6 行，每行一跳，"
                     "格式如「甲的父親是乙（書卷 章:節）」。第一行就寫第一跳，不要前言、不要編號。")
TABLE_HEAD = "〔經文親屬關係〕"
SLOT_HEAD = "〔關係推算〕"
SLOT = "{slot}"
ARMS_REP = {1: ("G", "T1C", "TLLM", "B0", "GO"), 2: ("G", "T1C")}
_BULLET = re.compile(r"^\s*(?:[-*•·]+|\d+\s*[.、)）:：]|[（(]\d+[)）])\s*")
_SPLIT = re.compile(r"[、，,；;/／\s]+")
_STRIP = "「」『』\"'“”‘’。．.：:！!？?（）()"


# ---------------------------------------------------------------- seeds
def seed_job(item: dict) -> dict:
    return {"job_id": f"B:{item['id']}:seed", "exp": "B", "item": item["id"], "arm": "seed", "rep": 1,
            "kind": "seed", "system": SEED_SYSTEM, "user": SEED_USER.format(question=item["question"])}


def simulated_seed(item: dict) -> str:
    """dry-run: the gold surfaces in question order (b before a in a pair question)."""
    s = item["surfaces"]
    return s[0] if item["type"] in Tm.LIN_WORDS else f"{s[-1]}\n{s[0]}"


def seed_names(content: str, question: str) -> list[str]:
    """Tokens of the seed output in order; tokens found in the question first; at most 2."""
    out = []
    for line in unicodedata.normalize("NFKC", content or "").splitlines():
        for tok in _SPLIT.split(_BULLET.sub("", line)):
            tok = tok.strip(_STRIP)
            if tok and tok not in out:
                out.append(tok)
    q = Tm.nrm(question)
    return ([t for t in out if Tm.nrm(t) in q] + [t for t in out if Tm.nrm(t) not in q])[:2]


def map_name(raw: str, nodes) -> str:
    """Exact node name first; else the unique node equal up to name dots; else the unique node
    containing / contained in raw (dots ignored); else raw (the card then abstains)."""
    if raw in nodes:
        return raw
    key = Tm.nrm(raw)
    for test in (lambda n: n == key, lambda n: n in key or key in n):
        hits = [n for n in sorted(nodes) if test(Tm.nrm(n))]
        if len(hits) == 1:
            return hits[0]
        if hits:
            break
    return raw


def anchors(content: str, question: str, nodes) -> dict:
    """Pair questions read 「{b}是{a}的什麼人」: the name earlier in the question is b."""
    raws = seed_names(content, question)
    mapped = [map_name(r, nodes) for r in raws]
    q = Tm.parse_question(question)
    if q["mode"] == "lin":
        return dict(mode="lin", k=q["k"], a=mapped[0] if mapped else None, b=None, raw=raws)
    if len(set(mapped)) < 2:
        return dict(mode="pair", k=None, a=None, b=None, raw=raws)

    def pos(i):
        p = Tm.nrm(question).find(Tm.nrm(raws[i]))
        p = Tm.nrm(question).find(Tm.nrm(mapped[i])) if p < 0 else p
        return (p if p >= 0 else len(question) + i, i)
    first, second = sorted(range(2), key=pos)
    return dict(mode="pair", k=None, a=mapped[second], b=mapped[first], raw=raws)


# ---------------------------------------------------------------- cards
def run_card(G: dict, anc: dict) -> dict:
    if anc["a"] is None:
        return dict(status="abstain", reason="seed_incomplete")
    if anc["mode"] == "lin":
        return Cd.ancestor_card(G, anc["a"], anc["k"])
    return Cd.pair_card(G, anc["a"], anc["b"])


def card_for(item: dict, seed_content: str, by_unit: dict) -> dict:
    G = Cd.subgraph(item["verses"], by_unit)
    anc = anchors(seed_content, item["question"], set(G["adj"]))
    res = run_card(G, anc)
    out = dict(anchors=anc, status=res["status"], reason=res.get("reason", ""), res=res)
    if res["status"] == "fire":
        lines = Cd.card_lines(res, anc["a"], anc["b"], anc["k"])
        out.update(text="\n".join(lines), n_hops=len(res["path"]),
                   card_judge=Tm.judge(cc.norm(lines[-1].split("：", 1)[1]), item["key"]))
    return out


def cards(item: dict, seed_content: str) -> dict:
    return dict(G=card_for(item, seed_content, L.triples_by_unit()),
                GO=card_for(item, seed_content, Gd.oracle_triples()))


# ---------------------------------------------------------------- arm prompts
def aux_blocks(item: dict) -> dict:
    table = Cd.edge_table(item["verses"], L.triples_by_unit())
    otable = Cd.edge_table(item["verses"], Gd.oracle_triples())
    return dict(table=f"{TABLE_HEAD}\n{table}", otable=f"{TABLE_HEAD}\n{otable}",
                table_chars=len(table), otable_chars=len(otable),
                n_edges=table.count("\n") + 1 if table != "（無）" else 0)


def _job(item, arm, rep, kind, **kw) -> dict:
    suffix = ":s1" if kind == "stage1" else ""
    return {"job_id": f"B:{item['id']}:{arm}:r{rep}{suffix}", "exp": "B", "item": item["id"],
            "arm": arm, "rep": rep, "kind": kind, "system": cc.SYSTEM_PROMPT, **kw}


def arm_jobs_for(item: dict, arm: str, rep: int, cd: dict, aux: dict, cap: int) -> list[dict]:
    ctx, q = item["context"], item["question"]
    if arm == "B0":
        return [_job(item, arm, rep, "gen", user=cc.build_user(ctx, q, None))]
    if arm in ("G", "GO"):
        c = cd[arm]
        if c["status"] != "fire":
            return []
        slot = cc.fill_slot(c["text"], Cd.CARD_MAX_LINES, cap) if arm == "G" else c["text"]
        table = aux["table"] if arm == "G" else aux["otable"]
        return [_job(item, arm, rep, "gen", user=cc.build_user(ctx, q, f"{table}\n\n{SLOT_HEAD}\n{slot}"))]
    s1_aux = aux["table"] if arm == "T1C" else None
    s2_aux = f"{aux['table']}\n\n{SLOT_HEAD}\n{SLOT}" if arm == "T1C" else f"{SLOT_HEAD}\n{SLOT}"
    s1 = _job(item, arm, rep, "stage1", user=cc.build_user(ctx, q, s1_aux, instruction=CHAIN_INSTRUCTION))
    s2 = _job(item, arm, rep, "gen", user_template=cc.build_user(ctx, q, s2_aux), slot_from=s1["job_id"],
              slot_max_lines=Cd.CARD_MAX_LINES, slot_cap_chars=cap)
    return [s1, s2]


def longest_card(card_by_item: dict) -> int:
    """Longest fired G card of the dev items (0 if none fires)."""
    return max((len(c["G"]["text"]) for c in card_by_item.values() if c["G"]["status"] == "fire"), default=0)


def slot_cap(card_by_item: dict, k0_cap: int) -> int:
    """Slot char cap of all three arms = max(K0 dry-run value, longest G card under the seeds in use):
    never below K0, and no G card is ever cut."""
    return max(k0_cap, longest_card(card_by_item))


def arm_jobs(items: list[dict], card_by_item: dict, cap: int) -> list[dict]:
    aux = {it["id"]: aux_blocks(it) for it in items}
    jobs = []
    for rep, arms in ARMS_REP.items():
        for i, it in enumerate(items):
            order = arms[i % len(arms):] + arms[:i % len(arms)]
            for arm in order:
                jobs += arm_jobs_for(it, arm, rep, card_by_item[it["id"]], aux[it["id"]], cap)
    return jobs
