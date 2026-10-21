"""Scoring, gates and the report of plan A4 (docs/records/2026-10-21_gen_card_integration_plan.md §3.2). CPU only.

Per call: the GEN confirmation set's frozen ``score_g.score_record`` (stage-0's keys_x on the item's arithmetic key),
imported unchanged, with num_ctx = the context_length /api/ps reported; a /query record carries no token counts, so
ON and OFF truncation cannot be seen. Item value per arm = the exact Fraction mean of its reps. A rule abstention (no
card): T-rows-prod rep r is B0-prod's rep r (the same prompt byte for byte, reused) and d is 0 for both Δ (ON is
imputed there, not reused: prod answers those items with its ordinary prompt). Δ over every item in sid order:
``ab_stats.sign_flip_p`` and ``bootstrap_ci`` (10000, seed 20261018) and W:L:T, analyze_g.d_test's conventions.
Means: ON on the fired items only; B0-prod and T-rows-prod strict (score) and lenient (score_any); OFF strict.
Whole-answer lenient score (keys_x.gold_written over every line of the answer, answer_text_x's normalisation): OFF
and B0-prod over every item, ON beside OFF on the abstentions, never ON on a fired item (every card holds the gold).
Retrieval strata: an ON call hits when one of its sources' id, passage_id or split_passage_ids equals the item's
context_from (string equality); an item is "all" (every rep hits), "some" or "none". Gates: wiring (ON card parity on
every item against run/cards.json's ``g`` key, OFF without aux_card on every item), quality (ON mean on the fired
items ≥ 0.80), stop (Δ(ON − B0-prod) CI low ≤ 0). Run-level voids judged here: a direct arm truncated ≥ 2 times
(prereg §4.5), /api/ps readings that differ in model or context_length or carry none. Nothing here reads or writes
a file or prints; the report holds ids, numbers and sha256 only.
"""
from __future__ import annotations

import hashlib
import statistics
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GEN_CONFIRM = REPO / "evaluation/experiments/2026-10-20_gen_confirm"
for _p in (REPO / "evaluation", GEN_CONFIRM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import score_g as SG  # noqa: E402  (frozen: imported, never edited)
from src import ab_stats  # noqa: E402

K, cc, fx = SG.K, SG.cc, SG.fx
ARMS = ("ON", "B0-prod", "T-rows-prod", "OFF")
DIRECT = ("B0-prod", "T-rows-prod")
ROTATED = ("B0-prod", "T-rows-prod", "OFF")        # rotated by item index after ON (arms_c.arm_jobs)
LENIENT = ("B0-prod", "T-rows-prod")
WHOLE = ("OFF", "B0-prod")
SEED, N_BOOT, EPS = 20261018, 10000, 1e-9          # analyze_g's
QUALITY_MIN = Fraction(4, 5)
TRUNC_ARM_MAX = SG.TRUNC_ARM_MAX                   # prereg §4.5
GEN_LAYER_SHA256 = "46d87abb29000d1210d0ee6fd5e045f7bf6ac08a2f1c034374a61c5e9c1aead5"
STRATA = ("all", "some", "none")
# §3.2's A4 sentence, written before the run; only the numbers are filled in
SENTENCE = ("staging（新 build＋r5）prod 檢索下，確認集同一批 58 題（盲寫；題目寫出兩人的層名、只在必要時加一個不在路徑上的"
            "辨識詞、不含數字、點名創世記），gemma4:e4b：ON − B0-prod Δ̄＝{d1}（棄權記 0），95% CI {ci1}；ON − T-rows-prod "
            "Δ̄＝{d2}，95% CI {ci2}；描述性，題目不是新樣本；Δ 固定實驗的 prompt 格式，不等於使用者看到的 ON − OFF 差")
NOTES = ("ON and OFF truncation cannot be observed: /query returns no done_reason or token counts",
         "abstentions: d = 0 for both Δ; T-rows-prod reuses B0-prod (same prompt), ON is imputed (prod's prompt differs)",
         "OFF strict is mostly a format failure (prod's ordinary prompt asks for no answer line); its whole-answer "
         "lenient score is not comparable with H1/H2")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def fired(cards: dict, sid: str) -> bool:
    return cards[sid]["g"] is not None


def content(rec: dict) -> str:
    """The answer a call gave: a direct call's content, a /query call's answer."""
    return (rec.get("content") if "content" in rec else rec.get("answer")) or ""


def scored(item: dict, rec: dict, num_ctx: int | None) -> dict:
    r = {"content": content(rec), "job_id": f"A4|{rec['sid']}|{rec['arm']}|{rec['rep']}",
         **{k: rec.get(k) for k in ("elapsed_s", "done_reason", "prompt_eval_count", "eval_count")}}
    return SG.score_record(item, r, num_ctx)


def whole_answer_text(text: str | None) -> str | None:
    """Every non-empty line of the answer, normalised as keys_x.answer_text_x normalises its lines, joined by ';'."""
    t = K.MD.sub("", unicodedata.normalize("NFKC", text or ""))
    lines = [cc.norm(K.LIST_X.sub("", ln.strip())) for ln in t.splitlines()]
    return ";".join(s for s in lines if s) or None


def whole_answer_score(item: dict, text: str | None) -> int:
    return int(K.gold_written(whole_answer_text(text), K._arith_key(item)))


def hit(rec: dict, context_from: str) -> bool:
    return any(s.get("id") == context_from or s.get("passage_id") == context_from
               or context_from in (s.get("split_passage_ids") or []) for s in rec.get("sources") or [])


def card_ok(aux: dict | None, card: dict) -> bool:
    """ON's aux_card against run/cards.json's ``g`` key: the GEN card byte for byte, or none on an abstention."""
    g = card["g"]
    if g is None:
        return aux is None
    return (isinstance(aux, dict) and aux.get("kind") == "gen" and isinstance(aux.get("text"), str)
            and sha(aux["text"]) == sha(g["g_block"]) and aux.get("layer_sha256") == GEN_LAYER_SHA256)


def mean(xs: list) -> Fraction | None:
    return None if not xs or any(x is None for x in xs) else Fraction(sum(xs), len(xs))


def d_test(d: list[Fraction]) -> dict:
    xs = [float(x) for x in d]
    lo, hi = ab_stats.bootstrap_ci(xs, n_boot=N_BOOT, seed=SEED) if xs else (None, None)
    return {"n": len(xs), "delta": float(sum(d, Fraction(0)) / len(d)) if d else None, "ci95": [lo, hi],
            "p": ab_stats.sign_flip_p(xs, seed=SEED) if xs else None,
            "W": sum(x > EPS for x in xs), "L": sum(x < -EPS for x in xs), "T": sum(abs(x) <= EPS for x in xs)}


# ---------------------------------------------------------------- one item
def item_row(item: dict, card: dict, recs: dict, reps: int, num_ctx: int | None) -> dict:
    """recs: {(arm, rep): final record}; T-rows-prod is absent on an abstention."""
    f, rr = card["g"] is not None, range(1, reps + 1)
    s = {k: scored(item, v, num_ctx) for k, v in recs.items()}
    if not f:
        s |= {("T-rows-prod", r): dict(s["B0-prod", r], substituted_from="B0-prod") for r in rr}
    m = {a: mean([s[a, r]["score"] for r in rr]) for a in ARMS}
    m_any = {a: mean([s[a, r]["score_any"] for r in rr]) for a in LENIENT}
    whole = {a: mean([whole_answer_score(item, content(recs[a, r])) for r in rr])
             for a in WHOLE + (() if f else ("ON",))}
    n_hit = sum(hit(recs["ON", r], item["context_from"]) for r in rr)
    return {"sid": item["sid"], "fired": f, "mean": m, "mean_any": m_any, "whole": whole,
            "d1": m["ON"] - m["B0-prod"] if f else Fraction(0), "d2": m["ON"] - m["T-rows-prod"] if f else Fraction(0),
            "hits": n_hit, "stratum": STRATA[0] if n_hit == reps else STRATA[1] if n_hit else STRATA[2],
            "on_card_ok": all(card_ok(recs["ON", r].get("aux_card"), card) for r in rr),
            "off_no_card": all(recs["OFF", r].get("aux_card") is None for r in rr),
            "truncated": {a: sum(s[a, r]["truncated"] for r in rr if (a, r) in recs) for a in DIRECT},
            "format_fail": {a: sum(s[a, r]["format_fail"] for r in rr if (a, r) in recs) for a in ARMS},
            "elapsed_s": {a: [recs[a, r].get("elapsed_s") for r in rr if (a, r) in recs] for a in ARMS}}


# ---------------------------------------------------------------- the run
def ps_problems(readings: list[dict]) -> list[str]:
    """§3.2: the /api/ps readings agree in model and context_length, and every one has a context_length."""
    out = [] if readings else ["no /api/ps reading"]
    if any(not isinstance(r.get("context_length"), int) or r["context_length"] <= 0 for r in readings):
        out.append("an /api/ps reading without a context_length")
    if len({(r.get("model"), r.get("context_length")) for r in readings}) > 1:
        out.append("/api/ps readings differ in model or context_length")
    return out


def truncation_problems(rows: list[dict]) -> list[str]:
    n = {a: sum(r["truncated"][a] for r in rows) for a in DIRECT}
    return [f"{a} truncated {k} times" for a, k in n.items() if k >= TRUNC_ARM_MAX]


def avg(rows: list[dict], get) -> dict | None:
    vs = [get(r) for r in rows]
    return fx(sum(vs, Fraction(0)) / len(vs)) if vs and None not in vs else None


def timing(rows: list[dict]) -> dict:
    out = {}
    for a in ARMS:
        xs = [x for r in rows for x in r["elapsed_s"][a] if x is not None]
        out[a] = {"n": len(xs), "median": statistics.median(xs) if xs else None, "max": max(xs, default=None),
                  "total": round(sum(xs), 2)}
    return out


def fmt(t: dict) -> tuple[str, str]:
    lo, hi = t["ci95"]
    return f"{t['delta']:+.3f}", f"[{lo:+.3f}, {hi:+.3f}]"


def sentence(t1: dict, t2: dict) -> str:
    (d1, ci1), (d2, ci2) = fmt(t1), fmt(t2)
    return SENTENCE.format(d1=d1, ci1=ci1, d2=d2, ci2=ci2)


def means(rows: list[dict]) -> dict:
    fr, ab = [r for r in rows if r["fired"]], [r for r in rows if not r["fired"]]
    out = {"ON": {"fired": avg(fr, lambda r: r["mean"]["ON"])},
           "OFF": {"all": avg(rows, lambda r: r["mean"]["OFF"])}}
    for a in LENIENT:
        out[a] = {}
        for w, sub in (("fired", fr), ("all", rows)):
            out[a][f"{w}_strict"] = avg(sub, lambda r: r["mean"][a])
            out[a][f"{w}_lenient"] = avg(sub, lambda r: r["mean_any"][a])
    whole = {f"{a}_all": avg(rows, lambda r: r["whole"][a]) for a in WHOLE}
    whole |= {f"{a}_abstained": avg(ab, lambda r: r["whole"][a]) for a in ("ON", "OFF")}
    return {**out, "whole_answer_lenient": whole}


def report(items: list[dict], cards: dict, finals: dict, *, reps: int, num_ctx: int | None, readings: list[dict],
           void: list[str]) -> dict:
    """finals: {(sid, arm, rep): final record} for every planned call; void: the run-level voids found so far."""
    rows = [item_row(it, cards[it["sid"]], {(a, r): v for (s, a, r), v in finals.items() if s == it["sid"]},
                     reps, num_ctx) for it in items]
    void = list(void) + ps_problems(readings) + truncation_problems(rows)
    t1, t2 = d_test([r["d1"] for r in rows]), d_test([r["d2"] for r in rows])
    strata = {k: {"n": len(sub), "d1": d_test([r["d1"] for r in sub]), "d2": d_test([r["d2"] for r in sub])}
              for k in STRATA for sub in [[r for r in rows if r["stratum"] == k]]}
    fr = [r for r in rows if r["fired"]]
    on_fired = sum((r["mean"]["ON"] for r in fr), Fraction(0)) / len(fr) if fr else None
    wiring = {"on_card_parity": sum(r["on_card_ok"] for r in rows), "off_no_card": sum(r["off_no_card"] for r in rows),
              "n": len(rows)}
    wiring["pass"] = wiring["on_card_parity"] == wiring["off_no_card"] == len(rows)
    quality = {"on_mean_fired": fx(on_fired), "min": str(QUALITY_MIN),
               "pass": on_fired is not None and on_fired >= QUALITY_MIN}
    stop = {"ci_low": t1["ci95"][0], "stop": t1["ci95"][0] is None or t1["ci95"][0] <= 0}
    judged = not void
    return {"schema": "gen_card.a4_report.v1", "state": "void" if void else "valid", "void": void, "judged": judged,
            "n_items": len(rows), "n_fired": len(fr), "reps": reps, "num_ctx": num_ctx,
            "context_length_readings": [r.get("context_length") for r in readings],
            "gates": {"wiring": wiring, "quality": quality, "stop": stop,
                      "propose_prod": judged and wiring["pass"] and quality["pass"] and not stop["stop"]},
            "delta": {"ON-B0-prod": t1, "ON-T-rows-prod": t2}, "strata": strata, "means": means(rows),
            "format_fail": {a: sum(r["format_fail"][a] for r in rows) for a in ARMS},
            "truncated": {a: sum(r["truncated"][a] for r in rows) for a in DIRECT}, "timing": timing(rows),
            "sentence": sentence(t1, t2) if judged else None, "notes": list(NOTES),
            "items": [{"sid": r["sid"], "fired": r["fired"], "stratum": r["stratum"], "hits": r["hits"],
                       "mean": {a: fx(v) for a, v in r["mean"].items()},
                       "mean_any": {a: fx(v) for a, v in r["mean_any"].items()},
                       "whole": {a: fx(v) for a, v in r["whole"].items()}, "d1": fx(r["d1"]), "d2": fx(r["d2"]),
                       "on_card_ok": r["on_card_ok"], "off_no_card": r["off_no_card"], "elapsed_s": r["elapsed_s"]}
                      for r in rows]}


def prod_check_report(items: list[dict], cards: dict, finals: dict, void: list[str]) -> dict:
    """The post-switch check: ON × 1 without the flag, card parity on every item (48 GEN cards, 10 none)."""
    ok = {it["sid"]: card_ok(finals[it["sid"], "ON", 1].get("aux_card"), cards[it["sid"]]) for it in items}
    fr = [it for it in items if fired(cards, it["sid"])]
    on = [scored(it, finals[it["sid"], "ON", 1], None)["score"] for it in fr]
    xs = [finals[it["sid"], "ON", 1].get("elapsed_s") for it in items]
    return {"schema": "gen_card.prod_check_report.v1", "state": "void" if void else "valid", "void": list(void),
            "n_items": len(items), "n_fired": len(fr), "card_parity": sum(ok.values()),
            "gen_cards": sum(ok[it["sid"]] for it in fr), "pass": not void and all(ok.values()),
            "on_mean_fired": fx(mean(on)), "failed_sids": sorted(s for s, v in ok.items() if not v),
            "timing": {"median": statistics.median(xs) if xs else None, "max": max(xs, default=None)}}
