"""Dry run of the confirmation set (run_c.py dry-run): no backend, no Ollama, no claude.

A synthetic frozen set (one template-worded §2.8 question per segment candidate, no real question)
and synthetic prod responses (two core blocks, an event_registry block on every third question, all
rendered exactly as prod build_context_blocks) go through collect_ctx.collect (all §4 checks) →
items_c.build_items → seeds_a.seed_jobs and arms_c.build_arms with gold seeds written as stage 1 would.
Checks: the four prompt sha values equal stage-0's (confirm_A.md §0); every seed / arm job is the
stage-0 template filled independently from those templates; B0 has no auxiliary section and the other
arms do; job count = 15N minus abstentions; seed round trip. Writes store A_confirm/dry_run/ (synthetic questions_frozen.json, contexts.json, items.json, jobs,
summary.json).
"""
from __future__ import annotations

import collections
from pathlib import Path

import arms_c
import collect_ctx
import items_c
from arms_a import ARMS, item_arms
from c_common import (KNAME, LAYER_AUTO, LAYER_REF, OUT, PROD_BUILD_ID, PROMPT_SHA, REPS, SEGMENTS, ac, cc, read_json,
                      sha256_text)
from engine import homonym
from items_a import seed_desc
from keys_a import king_lexicon
from regnal import load_auto, load_ref, map_auto_to_ref
from seeds_a import SEED_SYSTEM, SEED_USER, parse_seeds, seed_jobs, simulated_output

D = OUT / "dry_run"
CN = {1: "一", 2: "二", 3: "三", 4: "四"}


def synth_text(VR, c: dict, kn: str) -> str:
    a = c.get("a", c.get("seed"))
    if c["qtype"] == "S1a":
        return f"{seed_desc(VR, a)}之{'後' if c['k'] > 0 else '前'}的第{CN[abs(c['k'])]}位{kn}王是誰？"
    if c["qtype"] == "S1b":
        return f"從{seed_desc(VR, a)}到{seed_desc(VR, c['b'])}，王位一共交接了幾次？"
    if c["qtype"] == "S1c":
        return f"{seed_desc(VR, a)}之後第{CN[c['n']]}個篡位得國的{kn}王是誰？"
    return f"{seed_desc(VR, a)}出生時，在位的{kn}王是誰？"


def synth_questions(segs: list[dict], VR) -> list[dict]:
    """One §2.8 question per segment candidate (template wording; dry run and tests only)."""
    out = []
    for s in segs:
        kn, ch = KNAME[s["kingdom"]], s["kings"]
        for i, c in enumerate(s["candidates"]):
            a, b = (c["a"], c["b"]) if c["qtype"] == "S1b" else (c["seed"], c["answer"])
            ia, ib = ch.index(a), ch.index(b)
            path = ch[ia:ib + 1] if ia <= ib else ch[ib:ia + 1][::-1]
            fa = lambda x: VR.nodes[x]["father"] if homonym(VR, x) else None  # noqa: E731
            ans = ({"kind": "count", "text": f"{c['value']}次", "accept": [], "value": c["value"], "unit": "次"}
                   if c["qtype"] == "S1b" else {"kind": "name", "text": VR.nodes[b]["name"], "accept": []})
            out.append({"id": f"Z_{s['id']}_{i:02d}", "segment": s["id"], "qtype": c["qtype"], "kingdom": kn,
                        "question": synth_text(VR, c, kn), "pilot": i == 0, "k": c.get("k"), "n": c.get("n"),
                        "seeds": [{"name": VR.nodes[x]["name"], "father": fa(x)}
                                  for x in ([a, b] if c["qtype"] == "S1b" else [a])],
                        "answer": ans,
                        "chain": [{"king": VR.nodes[x]["name"], "father": fa(x),
                                   "role": "seed" if j == 0 else ("answer" if j == len(path) - 1 else "step"),
                                   "fact": "", "basis": [VR.nodes[x]["prov"].get("pred") or ""]}
                                  for j, x in enumerate(path)]})
    return out


def synth_source(pos: int, qid: str, strategy: str) -> dict:
    src = {"id": f"ps:synth.{qid}.{pos}", "book": "列王紀上", "chapter": pos, "title": f"合成段落{pos}",
           "verse_range": "1-2", "strategy": strategy, "build_id": PROD_BUILD_ID}
    block = cc.context_block(pos, {"book_name": src["book"], "chapter_num": pos, "title": src["title"],
                                   "verse_range": "1-2", "content": f"合成內容 {qid} 第{pos}段"})
    return {**src, "context": block}


def synth_response(i: int, qid: str) -> dict:
    strategies = ["hybrid_hybrid", "hybrid_hybrid"] + (["event_registry"] if i % 3 == 0 else [])
    return {"answer": "", "sources": [synth_source(p, qid, s) for p, s in enumerate(strategies, 1)],
            "intent": {"type": "synthetic", "entities": [], "verse_refs": []},
            "retrieval_stats": {"route_used": "synthetic", "strategies_used": ["hybrid_hybrid"], "strategy_errors": {},
                                "event_registry_events": []}}


def fake_post(questions: list[dict]):
    by_q = {q["question"]: synth_response(i, q["id"]) for i, q in enumerate(questions)}
    if len(by_q) != len(questions):
        raise SystemExit("synthetic question texts are not unique")
    return lambda _url, body, _timeout: by_q[body["question"]]


def expected_user(ctx: str, question: str, block: str | None, template: str = cc.USER_TEMPLATE) -> str:
    """The stage-0 user template filled directly (independent of cards_common.build_user)."""
    aux, ref = (f"\n{cc.AUX_LABEL}\n{block}\n", "與輔助資料") if block else ("", "")
    return template.format(context=ctx, aux=aux, aux_ref=ref, instruction=cc.ANSWER_INSTRUCTION, question=question)


def job_problems(its: list[dict], sj: list[dict], jobs: list[dict], built: dict) -> list[str]:
    by_id = {it["id"]: it for it in its}
    bad = [f"{j['job_id']}: seed prompt" for j, it in zip(sj, its)
           if j["system"] != SEED_SYSTEM or j["user"] != SEED_USER.format(
               context=cc.build_context(it["sources"]), question=it["question"])]
    for j in jobs:
        it, block = by_id[j["item"]], built[j["item"]]["blocks"][j["arm"]]
        if j["system"] != cc.SYSTEM_PROMPT or j["user"] != expected_user(cc.build_context(it["sources"]),
                                                                           it["question"], block or None):
            bad.append(f"{j['job_id']}: arm prompt")
        if (cc.AUX_LABEL in j["user"]) != (j["arm"] != "B0"):
            bad.append(f"{j['job_id']}: auxiliary section")
    if len({j["job_id"] for j in jobs}) != len(jobs):
        bad.append("duplicate arm job ids")
    return bad


def dry_run(out_dir: Path = D, segs: list[dict] | None = None) -> dict:
    out_dir = Path(out_dir)
    VR, VA = load_ref(LAYER_REF), load_auto(LAYER_AUTO)
    segs = segs or read_json(SEGMENTS)["segments"]
    qs = synth_questions(segs, VR)
    for name in ("contexts.json", "collect_failed.json"):
        (out_dir / name).unlink(missing_ok=True)
    ctx_doc = collect_ctx.collect(qs, "synthetic", out=out_dir / "contexts.json", failed=out_dir / "collect_failed.json",
                                  post=fake_post(qs), ps=lambda: {"synthetic": True}, log=lambda *_: None,
                                  sleep=lambda _s: None)
    cc.write_json(out_dir / "questions_frozen.json", {"questions": qs})
    items_doc = items_c.build_items(qs, items_c.contexts_of(ctx_doc), segs, VR)
    items_doc["inputs_sha256"] = {n: ac.sha256_file(out_dir / n) for n in ("questions_frozen.json", "contexts.json")}
    its = items_doc["items"]
    seed_text = {it["id"]: simulated_output(VR, it) for it in its}
    sj = seed_jobs(its)
    jobs, meta = arms_c.build_arms(its, seed_text, VA, VR)
    base, a2r = king_lexicon(VR), map_auto_to_ref(VA, VR)
    built = {it["id"]: item_arms(it, seed_text[it["id"]], VA, VR, base, a2r) for it in its}
    sha = {"system_prompt": sha256_text(cc.SYSTEM_PROMPT), "user_template": sha256_text(cc.USER_TEMPLATE),
           "seed_system": sha256_text(SEED_SYSTEM), "seed_user_template": sha256_text(SEED_USER)}
    roundtrip = [it["id"] for it in its if [(VR.nodes[x]["kingdom"], VR.nodes[x]["name"]) for x in it["seeds"]]
                 != parse_seeds(seed_text[it["id"]]) or meta[it["id"]]["ref_ids"] != it["seeds"]]
    problems = job_problems(its, sj, jobs, built)
    summary = {"label": "dry run: synthetic frozen set and contexts, gold seeds (no backend, no Ollama)",
               "n_items": len(its), "n_units": len({it["unit"] for it in its}), "n_seed_jobs": len(sj),
               "n_arm_jobs": len(jobs), "expected_arm_jobs": arms_c.expected_jobs(meta), "reps": REPS,
               "arm_jobs_by_arm": dict(collections.Counter(j["arm"] for j in jobs)),
               "prompt_sha256": sha, "prompt_sha_ok": sha == PROMPT_SHA, "job_problems": problems,
               "seed_roundtrip_mismatch": roundtrip, "context_n_aux": sum(r["n_aux"] for r in ctx_doc["items"].values()),
               "g_auto_abstain": [i for i, m in meta.items() if not m["g_auto_fired"]],
               "g_ref_abstain": [i for i, m in meta.items() if not m["g_ref_fired"]],
               "a_hit_gold_seeds": sum(m["a_hit"] for m in meta.values()),
               "user_chars_max": max(len(j["user"]) for j in sj + jobs),
               "seed_prompts_sha256": ac.prompts_sha256(sj), "arm_prompts_sha256": ac.prompts_sha256(jobs)}
    summary["ok"] = (summary["prompt_sha_ok"] and not problems and not roundtrip
                     and summary["n_arm_jobs"] == summary["expected_arm_jobs"]
                     and set(summary["arm_jobs_by_arm"]) == set(ARMS))
    for name, obj in (("items.json", items_doc),
                      ("seed_jobs.json", sj), ("arms_jobs.json", jobs), ("arms_meta.json", meta),
                      ("summary.json", summary)):
        cc.write_json(out_dir / name, obj)
    print({k: summary[k] for k in ("ok", "n_items", "n_seed_jobs", "n_arm_jobs", "expected_arm_jobs", "prompt_sha_ok")})
    return summary
