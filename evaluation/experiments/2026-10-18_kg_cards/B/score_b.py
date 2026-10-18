"""Score experiment B answers (prereg §1 計分前處理, §3 指標).

answer line = cards_common.answer_line on the content with Markdown symbols removed first (prereg §1;
otherwise "**答案**：" is not found); no answer line, or a truncated call (done_reason=length,
or prompt_eval_count+eval_count >= context_length), = format failure, 0. A stage-2 answer whose
stage-1 call was truncated is a format failure too. LIN: a gold surface and no trap name; pair: an
accepted term and no trap term (b_terms.judge, substring-safe). context_length comes from --ctx-len
or the smoke's /api/ps record (B/smoke/ps.json); without either, scoring refuses.
Descriptive only: b_terms.judge_variants, and the stage-1 slot statistics of the two-stage arms.
"""
from __future__ import annotations

import collections

import b_card as Cd
import b_lib as L
import b_terms as Tm
from b_lib import cc

PS = L.OUT / "smoke/ps.json"


def ctx_from_ps(path=PS) -> int | None:
    """context_length of the generation model in a saved /api/ps response."""
    if not path.exists():
        return None
    for m in L.load_json(path)["ps"].get("models", []):
        if cc.MODEL in (m.get("name"), m.get("model")) and m.get("context_length"):
            return int(m["context_length"])
    return None


def resolve_ctx(ctx_len: int | None) -> int:
    ctx = ctx_len or ctx_from_ps()
    if not ctx:
        raise SystemExit("no context_length: pass --ctx-len N or run `arms --smoke 3` / `ps` (B/smoke/ps.json)")
    return ctx


def truncated(rec: dict, ctx_len: int | None) -> bool:
    if rec.get("done_reason") == "length":
        return True
    pe, ec = rec.get("prompt_eval_count"), rec.get("eval_count")
    return bool(ctx_len and pe is not None and ec is not None and pe + ec >= ctx_len)


def answer_line(content: str | None) -> str | None:
    """Markdown removed before the 「答案：」 search: gemma often writes 「**答案**：」."""
    return cc.answer_line(cc._MD.sub("", content or ""))


def score_job(rec: dict | None, s1: dict | None, key: dict, ctx_len: int) -> dict:
    if rec is None:
        return dict(ok=0, why="missing", missing=True)
    trunc = truncated(rec, ctx_len) or (s1 is not None and truncated(s1, ctx_len))
    line = answer_line(rec["content"])
    out = dict(ok=0, why="truncated") if trunc else Tm.judge(line, key)
    var = dict(ok_first_clause=0, accept_only_in_parens=False) if trunc else Tm.judge_variants(line, key)
    return dict(out, **var, line=line, truncated=trunc, user_chars=rec.get("user_chars"),
                prompt_eval_count=rec.get("prompt_eval_count"), eval_count=rec.get("eval_count"),
                done_reason=rec.get("done_reason"), missing=False)


def slot_stats(s1: dict, cap: int) -> dict:
    """Stage-1 output vs the slot: raw non-empty lines and chars, and what fill_slot cut."""
    lines = [ln.strip() for ln in (s1.get("content") or "").strip().splitlines() if ln.strip()]
    kept = "\n".join(lines[:Cd.CARD_MAX_LINES])
    return dict(n_lines=len(lines), chars=len("\n".join(lines)), cut_lines=len(lines) > Cd.CARD_MAX_LINES,
                cut_chars=len(kept) > cap)


def score(items: list[dict], jobs: list[dict], answers: dict, cards: dict, ctx_len: int) -> tuple[dict, list]:
    by_item = {it["id"]: it for it in items}
    per = collections.defaultdict(lambda: collections.defaultdict(dict))
    slots = []
    for j in jobs:
        if j["kind"] != "gen":
            continue
        src = j.get("slot_from")
        s1 = answers.get(src) if src else None
        if src and s1 is None:
            per[j["item"]][j["arm"]][str(j["rep"])] = dict(ok=0, why="missing", missing=True)
            continue
        if s1 is not None:
            slots.append(dict(arm=j["arm"], item=j["item"], rep=j["rep"], **slot_stats(s1, j["slot_cap_chars"])))
        per[j["item"]][j["arm"]][str(j["rep"])] = score_job(answers.get(j["job_id"]), s1, by_item[j["item"]]["key"], ctx_len)
    out = {}
    for it in items:
        g, go = cards[it["id"]]["G"], cards[it["id"]]["GO"]
        out[it["id"]] = dict(
            stratum=it["stratum"], type=it["type"], pericope=it["pericope"], layout=it["layout"]["cls"],
            dispersed=it["layout"]["dispersed"], chain=list(it["ids"]), fired=g["status"] == "fire",
            card_reason=g["reason"], card_ok=int(g["status"] == "fire" and g["card_judge"]["ok"] == 1),
            card_hops=g.get("n_hops"), lookup_layer=g.get("n_hops") == 1,
            oracle_fired=go["status"] == "fire",
            oracle_ok=int(go["status"] == "fire" and go["card_judge"]["ok"] == 1),
            arms={a: dict(reps) for a, reps in per[it["id"]].items()})
    return out, slots


def run(ctx_len: int | None) -> dict:
    ctx = resolve_ctx(ctx_len)
    items = L.load_json(L.OUT / "items.json")["items"]
    jobs = L.load_json(L.OUT / "arm_jobs.json")["jobs"]
    cards = L.load_json(L.OUT / "cards.json")["cards"]
    answers = cc.done_jobs(L.OUT / "arms.jsonl")
    scores, slots = score(items, jobs, answers, cards, ctx)
    n_missing = sum(r.get("missing", False) for s in scores.values() for a in s["arms"].values()
                    for r in a.values())
    out = dict(ctx_len=ctx, ctx_source="--ctx-len" if ctx_len else "smoke/ps.json", n_items=len(items),
               n_gen_jobs=sum(j["kind"] == "gen" for j in jobs), n_missing=n_missing, items=scores, slots=slots)
    cc.write_json(L.OUT / "scores.json", out)
    return out


def smoke_report(ctx_len: int | None) -> dict:
    """Truncation count of the smoke calls (seeds and arms) under the saved context_length."""
    ctx = ctx_len or ctx_from_ps()
    out = dict(ctx_len=ctx)
    for name in ("seeds", "arms"):
        recs = list(cc.done_jobs(L.OUT / f"smoke/{name}.jsonl").values())
        out[name] = dict(n=len(recs), truncated=sum(truncated(r, ctx) for r in recs),
                         done_reason_length=sum(r.get("done_reason") == "length" for r in recs),
                         max_tokens=max(((r.get("prompt_eval_count") or 0) + (r.get("eval_count") or 0) for r in recs), default=0))
    cc.write_json(L.OUT / "smoke/truncation.json", out)
    return out
