"""Scores and verdict of the rule-seed regression (prereg.md §5–§7). CPU only.

Confirmation set: experiment A confirm's ``score_c.score_items`` (trap rule "chain", unchanged), the rule
arm fed in as its G-auto and the gemma arm as its G-ref (3 reps each; rep r of the gemma arm is seed set
r), no substitution (every slot has a job). Unit value = analyze_c.unit_values (unweighted mean of the
unit's item differences, item value = mean of the arm's 3 calls); Δ̄ = mean over the 14 units.
Development set: ``keys_a.item_ctx`` + ``score_a.score_record`` (stage-0 rule); Δ̄ = mean over the taken
questions of the item differences. Before trusting either, ``reproduce`` rescores the store's G-auto
records and must give scores.json's values exactly.

Verdict (point estimates, fixed in prereg): R1 confirm Δ̄ ≥ −0.05, R2 dev Δ̄ ≥ −0.05 (the boundary
passes), R3 0 truncated and 0 error calls. Everything else is description. Every result is in-sample.
A dry run's verdict is "dry_run", never a pass. ``score_run`` first checks that the cards and jobs it is
given are the run's (jobs_sha256, each job's card, the pins), then that the scorers reproduce.
"""
from __future__ import annotations

import json
from pathlib import Path

import rs_common as C
from rs_cards import slot_map
from rs_common import ARMS, EPS, REPS, THRESHOLD
from rs_jobs import job_id, jobs_sha256
from rs_run import GEN, RUN_META, answers, digest_state, error_lines

A_ARM = {"rule": "G-auto", "gemma": "G-ref"}
SC_REPS = {"G-auto": REPS, "G-ref": REPS, "T-canon": 0, "T-rows": 0, "B0": 0}
NOTES = ("結果是樣本內：規則是讀過實驗 A 的 62 題之後寫的，確認集與 dev 都不是盲集",
         "點估計門檻 −0.05 在這個題數下只抓得到約 ≥0.10–0.15 的破壞，不能宣稱非劣性",
         "H1／H2 的措辭只屬於舊版本（層 932d2242＋gemma 種子＋無 S4 守門），不延伸到規則種子版本")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- per-call checks
def truncated(rec: dict, opts: dict) -> bool:
    """done_reason length, or the output reached num_predict, or prompt + output reached num_ctx."""
    from score_a import truncated as ctx_truncated
    return rec.get("done_reason") == "length" or (rec.get("eval_count") or 0) >= opts["num_predict"] or \
        ctx_truncated(rec, opts.get("num_ctx"))


def r3(recs: list[dict], errors: list[dict], opts: dict) -> dict:
    t = sorted(r["job_id"] for r in recs if truncated(r, opts))
    e = sorted({r["job_id"] for r in errors})
    return {"truncated": len(t), "errors": len(errors), "truncated_ids": t, "error_ids": e,
            "pass": not t and not errors}


# ---------------------------------------------------------------- scoring
def score_confirm(items: list[dict], by_job: dict, VR, num_ctx: int) -> tuple[dict, list[str]]:
    """{item: {"unit", "reps": {"arm|r": record}, "mean": {arm: value}}}, job ids without a record."""
    import score_c
    meta = {it["id"]: {"g_auto_fired": True, "g_ref_fired": True} for it in items}
    mapped = {score_c.job_id(it["id"], a, r): by_job[job_id("confirm", it["id"], arm, r)]
              for it in items for arm, a in A_ARM.items() for r in range(1, REPS + 1)
              if job_id("confirm", it["id"], arm, r) in by_job}
    per, _ = score_c.score_items(items, meta, mapped, VR, num_ctx, SC_REPS, "chain")
    out, missing = {}, []
    for it in items:
        p = per[it["id"]]
        reps = {f"{arm}|{r}": p["reps"][f"{a}|{r}"] for arm, a in A_ARM.items() for r in range(1, REPS + 1)}
        missing += [job_id("confirm", it["id"], arm, r) for arm in A_ARM for r in range(1, REPS + 1)
                    if reps[f"{arm}|{r}"] is None]
        out[it["id"]] = {"unit": it["unit"], "reps": reps, "mean": {arm: p["mean"][a] for arm, a in A_ARM.items()}}
    return out, missing


def score_dev(items: list[dict], by_job: dict, VR, num_ctx: int) -> tuple[dict, list[str]]:
    from keys_a import item_ctx, king_lexicon
    from score_a import score_record
    base = king_lexicon(VR)
    out, missing = {}, []
    for it in items:
        ctx = item_ctx(it, VR, base)
        reps = {}
        for arm in ARMS:
            for r in range(1, REPS + 1):
                rec = by_job.get(job_id("dev", it["id"], arm, r))
                reps[f"{arm}|{r}"] = score_record(ctx, rec, num_ctx) if rec else None
                if rec is None:
                    missing.append(job_id("dev", it["id"], arm, r))
        out[it["id"]] = {"reps": reps, "mean": {arm: mean([reps[f"{arm}|{r}"]["score"] for r in range(1, REPS + 1)
                                                         if reps[f"{arm}|{r}"]]) for arm in ARMS}}
    return out, missing


def unit_delta(rows: dict) -> tuple[dict, float | None]:
    from analyze_c import unit_values
    units = unit_values(rows, "rule", "gemma")
    return units, mean(list(units.values()))


def item_delta(rows: dict) -> float | None:
    return mean([r["mean"]["rule"] - r["mean"]["gemma"] for r in rows.values()
                 if r["mean"]["rule"] is not None and r["mean"]["gemma"] is not None])


def threshold_pass(delta: float | None) -> bool:
    return delta is not None and delta >= THRESHOLD - EPS


# ---------------------------------------------------------------- verdict
def _judge(R1: dict, R2: dict, r3_: dict, missing: list[str], digest: str, nums: str) -> tuple[str, str]:
    """(result, wording). Precedence: a digest mismatch voids the run; a digest Ollama did not answer
    is checked again by resuming; an error or a truncation fails R3 for good (errors are final); a job
    not run, or no after-check yet, is incomplete; else R1, R2 and R3 decide."""
    incomplete = bool(missing) or digest == "unfinished"
    if digest == "mismatch":
        return "void_digest", (f"作廢（樣本內）：跑後模型 digest 與預期不符，可在新目錄用 --rerun-of 重跑 1 次；{nums}")
    if digest == "unknown":
        return "digest_unknown", (f"未判（樣本內）：跑後查不到模型 digest，在同一目錄續跑補查（不開重跑）；{nums}")
    if incomplete and not r3_["pass"]:
        left = f"另有 {len(missing)} 個 job 沒跑，" if missing else ""
        return "fail", (f"樣本內回歸未過（R3 已確定不過；{left}R1／R2 未判；{nums}）：停，逐題看，不改門檻")
    if incomplete:
        what = f"{len(missing)} 個 job 沒跑" if missing else "跑後的 digest 還沒查"
        return "incomplete", f"未完成（樣本內）：{what}，在同一目錄續跑後再判；{nums}"
    if R1["pass"] and R2["pass"] and r3_["pass"]:
        return "pass", (f"樣本內回歸通過（{nums}）：規則種子在確認集與 dev 觸發題上沒有測到超過 0.05 的退步；"
                        "此門檻只抓得到約 ≥0.10–0.15 的破壞，不能宣稱非劣性")
    failed = "、".join(k for k, v in (("R1", R1), ("R2", R2), ("R3", r3_)) if not v["pass"])
    return "fail", f"樣本內回歸未過（{failed}；{nums}）：停，逐題看，不改門檻"


def verdict(r1_delta, r2_delta, r3_: dict, missing: list[str], digest: str, dry_run: bool = False) -> dict:
    """digest: rs_run.digest_state of the run ("ok", "mismatch", "unknown", "unfinished")."""
    R1 = {"delta": r1_delta, "threshold": THRESHOLD, "pass": threshold_pass(r1_delta), "level": "確認集單位層"}
    R2 = {"delta": r2_delta, "threshold": THRESHOLD, "pass": threshold_pass(r2_delta), "level": "dev 觸發題題層"}
    out = {"R1": R1, "R2": R2, "R3": r3_, "missing": missing, "digest_state": digest, "digest_ok": digest == "ok",
           "notes": list(NOTES)}
    d = lambda x: "—" if x is None else f"{x:+.3f}"  # noqa: E731
    nums = f"R1 Δ̄＝{d(r1_delta)}、R2 Δ̄＝{d(r2_delta)}、截斷 {r3_['truncated']}、錯誤 {r3_['errors']}"
    result, wording = _judge(R1, R2, r3_, missing, digest, nums)
    if dry_run:
        return {**out, "result": "dry_run", "pass": False, "dry_judgment": result,
                "wording": f"（假 chat，分數無意義）dry run，不是判定；流程上會判 {result}：{wording}"}
    return {**out, "result": result, "pass": result == "pass", "dry_judgment": None, "wording": wording}


# ---------------------------------------------------------------- description (not judged)
def _unique_cards(doc: dict, arm: str) -> list[dict]:
    seen, out = set(), []
    for s in doc["slots"]:
        key = (s["set"], s["item"], s["seed_source"])
        if s["arm"] == arm and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def describe(doc: dict, per: dict) -> dict:
    slots = slot_map(doc)
    same = {}
    for set_name, labels in doc["header"]["seed_sets"].items():
        ids = doc["items"].get(set_name, [])
        reps = range(1, len(labels) + 1)
        eq = {lb: sum(slots[(set_name, i, "rule", r)]["text"] == slots[(set_name, i, "gemma", r)]["text"] for i in ids)
              for r, lb in zip(reps, labels, strict=True)}
        eq["every_set"] = sum(all(slots[(set_name, i, "rule", r)]["text"] == slots[(set_name, i, "gemma", r)]["text"]
                                  for r in reps) for i in ids)
        same[set_name] = {"n_items": len(ids), **eq}
    cards = {}
    for arm in ARMS:
        u = _unique_cards(doc, arm)
        with_card = [s for s in u if s["card"]]
        cards[arm] = {"distinct_slots": len(u), "cards": len(with_card), "no_card": len(u) - len(with_card),
                      "mean_chars": mean([s["chars"] for s in with_card]),
                      "mean_lines": mean([s["lines"] for s in with_card]),
                      "rows_dropped_total": sum(s["rows_dropped"] for s in with_card),
                      "cards_with_rows_dropped": sum(s["rows_dropped"] > 0 for s in with_card),
                      "cards_guard_blocked": sum(bool(s["guard_blocked"]) for s in with_card),
                      "by_source": _count(s["seed_source"] for s in u)}
    rule_seeded = [s for s in _unique_cards(doc, "rule") if s["seed_source"] == "rule" and s["card"]]
    out = {"same_card_items": same, "cards": cards,
           "rule_seeded_mean_chars": mean([s["chars"] for s in rule_seeded]),
           "rule_abstained": {st: sorted(i for i, r in rr.items() if not r["ids"]) for st, rr in doc["rule"].items()},
           "rule_reasons": {st: {i: r["reason"] for i, r in rr.items() if not r["ids"]}
                            for st, rr in doc["rule"].items()},
           "n_taken": {st: len(v) for st, v in doc["items"].items()}, "not_taken": doc["not_fired"]}
    if per.get("confirm"):
        units: dict = {}
        for it in per["confirm"].values():
            for arm in ARMS:
                units.setdefault(it["unit"], {}).setdefault(arm, []).append(it["mean"][arm])
        out["confirm_units"] = {u: {arm: mean(v) for arm, v in a.items()} for u, a in sorted(units.items())}
    for set_name, rows in per.items():
        out[f"{set_name}_items"] = {i: r["mean"] for i, r in rows.items()}
        out[f"{set_name}_calls"] = {arm: {"format_fail": sum(bool(v and v["format_fail"]) for v in r_items(rows, arm)),
                                          "trap": sum(bool(v and v["trap"]) for v in r_items(rows, arm))}
                                    for arm in ARMS}
    return out


def r_items(rows: dict, arm: str):
    """The arm's call records (None where a call is missing)."""
    for r in rows.values():
        for rep in range(1, REPS + 1):
            yield r["reps"].get(f"{arm}|{rep}")


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# ---------------------------------------------------------------- a run
def run_problems(meta: dict, doc: dict, jobs: list[dict]) -> list[str]:
    """Why these cards and jobs are not the ones this run ran (empty = they are)."""
    out = []
    if not meta.get("dry_run") and any(c.get("fake") for c in meta.get("digest_checks", [])):
        out.append("a formal run holds fake digest checks")
    if jobs_sha256(jobs) != meta["jobs_sha256"]:
        out.append("jobs_sha256 of the jobs differs from run_meta's (another build's jobs)")
    slots = slot_map(doc)
    keys = {(j["set"], j["item"], j["arm"], j["rep"]) for j in jobs}
    if keys != set(slots):
        out.append("the cards' slots are not the jobs' slots")
    for j in jobs:
        s = slots.get((j["set"], j["item"], j["arm"], j["rep"]))
        if s is None:
            continue
        text_sha = C.sha256_text(s["text"]) if s["text"] else None
        if (s["text_sha256"], s["seed_source"]) != (text_sha, j["seed_source"]) or j["card_sha256"] != text_sha \
                or (s["text"] and s["text"] not in j["user"]):
            out.append(f"card of {j['job_id']} differs from the job's")
            break
    pins = meta.get("pins") or {}
    for k in ("layer_sha256", "lexicon_sha256", "backend_sha256"):
        if k in pins and pins[k] != doc["header"][k]:
            out.append(f"{k.removesuffix('_sha256')} sha of the cards differs from the run's pins")
    return out


def score_run(out: Path, doc: dict, jobs: list[dict], items_by_set: dict,
              require_clean: bool = False) -> tuple[dict, dict]:
    """Reads out/gen.jsonl and run_meta.json; writes out/scores.json and out/verdict.json. Refuses unless
    the cards and jobs are the run's (``run_problems``), the harness is committed (require_clean, the
    command line's ``score``), and the scorers first reproduce experiment A's recorded G-auto scores."""
    out = Path(out)
    meta = C.read_json(out / RUN_META)
    bad = run_problems(meta, doc, jobs)
    if bad:
        raise SystemExit(f"{out}: not this run's cards and jobs: {bad}")
    harness = C.harness_pins()
    if require_clean and harness["dirty"]:
        raise SystemExit(f"the harness directory has uncommitted changes (HEAD {harness['git_head']}): "
                         "score only committed code")
    repro = reproduce()
    if not (repro["confirm"]["ok"] and repro["dev"]["ok"]):
        raise SystemExit(f"the scorers do not reproduce scores.json: {repro}")
    opts = meta["options"]
    recs, errs = answers(out / GEN), error_lines(out / GEN)
    errored = {e["job_id"] for e in errs}
    missing = [j["job_id"] for j in jobs if j["job_id"] not in recs and j["job_id"] not in errored]
    VR = C.ref_view()
    by_id = {s: {it["id"]: it for it in its} for s, its in items_by_set.items()}
    per = {}
    if "confirm" in doc["items"]:
        per["confirm"], _ = score_confirm([by_id["confirm"][i] for i in doc["items"]["confirm"]], recs, VR,
                                          opts["num_ctx"])
    if "dev" in doc["items"]:
        per["dev"], _ = score_dev([by_id["dev"][i] for i in doc["items"]["dev"]], recs, VR, opts["num_ctx"])
    units, d1 = unit_delta(per["confirm"]) if "confirm" in per else ({}, None)
    d2 = item_delta(per["dev"]) if "dev" in per else None
    run_harness = (meta.get("harness") or {}).get("sha256")
    v = verdict(d1, d2, r3(list(recs.values()), errs, opts), missing, digest_state(meta), bool(meta.get("dry_run")))
    v = {**v, "confirm_units_delta": units, "n_units": len(units), "describe": describe(doc, per),
         "layer_sha256": doc["header"]["layer_sha256"], "lexicon_sha256": doc["header"]["lexicon_sha256"],
         "backend_sha256": doc["header"]["backend_sha256"], "jobs_sha256": meta["jobs_sha256"],
         "dry_run": meta.get("dry_run", False), "in_sample": True, "pins": meta.get("pins"),
         "harness_at_run": meta.get("harness"), "harness_at_score": harness,
         "harness_same_as_run": run_harness == harness["sha256"] if run_harness else None,
         "scorer_reproduced": {k: {kk: r[kk] for kk in ("ok", "n_items", "g_auto_item_mean")}
                               for k, r in repro.items()}}
    scores = {"options": opts, "trap_rule_confirm": "chain", "n_records": len(recs), "n_errors": len(errs),
              "items": per}
    C.write_json(out / "scores.json", scores)
    C.write_json(out / "verdict.json", v)
    return scores, v


# ---------------------------------------------------------------- the scorers on the store's records
def _norm(x):
    return json.loads(json.dumps(x, ensure_ascii=False))


def reproduce() -> dict:
    """G-auto of A_confirm (score_c.score_items, chain) and of stage-0 A (score_a.arm_rep_scores) rescored
    from the store's records; ok = every item's G-auto calls and means equal scores.json (and the other
    arms' means too)."""
    import score_a
    import score_c
    from keys_a import item_ctx, king_lexicon
    VR = C.ref_view()
    out = {}
    items = C.read_json(C.A_CONFIRM / "items.json")["items"]
    meta = C.read_json(C.A_CONFIRM / "arms_meta.json")
    per, missing = score_c.score_items(items, meta, C.cc.done_jobs(C.A_CONFIRM / "gen_arms.jsonl"), VR,
                                       score_c.run_num_ctx(C.A_CONFIRM, "arms"))
    rec = C.read_json(C.A_CONFIRM / "scores.json")["items"]
    bad = [i for i in per if _norm(per[i]["mean"]) != rec[i]["mean"]
           or any(_norm(per[i]["reps"][f"G-auto|{r}"]) != rec[i]["reps"][f"G-auto|{r}"] for r in range(1, 4))]
    out["confirm"] = {"ok": not bad and not missing, "n_items": len(per), "n_units": len({it["unit"] for it in items}),
                      "mismatches": bad, "missing": missing,
                      "g_auto_item_mean": mean([per[i]["mean"]["G-auto"] for i in per])}
    items = C.read_json(C.A_DEV / "items.json")["items"]
    meta = C.read_json(C.A_DEV / "arms_meta.json")
    by_job = C.cc.done_jobs(C.A_DEV / "gen_arms.jsonl")
    nc = score_a.run_num_ctx(C.A_DEV, "arms", None)
    rec = C.read_json(C.A_DEV / "scores.json")["items"]
    base, bad, got = king_lexicon(VR), [], {}
    for it in items:
        reps = score_a.arm_rep_scores(it, meta[it["id"]], by_job, item_ctx(it, VR, base), nc)
        n = score_a.REPS["G-auto"]
        got[it["id"]] = mean([reps[("G-auto", r)]["score"] for r in range(1, n + 1)])
        if got[it["id"]] != rec[it["id"]]["mean"]["G-auto"] or \
                any(_norm(reps[("G-auto", r)]) != rec[it["id"]]["reps"][f"G-auto|{r}"] for r in range(1, n + 1)):
            bad.append(it["id"])
    out["dev"] = {"ok": not bad, "n_items": len(items), "mismatches": bad, "g_auto_item_mean": mean(list(got.values()))}
    return out
