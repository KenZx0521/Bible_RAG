"""The report of the book_anchor ablation (prereg §5, §8, §9 3.9, §13); ba_analyze.py report.

Reads $OUT (checks/, gen.jsonl, judge/, retr/), re-verifies the freeze, the judge metas
(§5 量尺: context_format generator_blocks, every context_source backend, judge gemma4:26b,
GT v2, the build), each judge file's .src_sha (run_ba.sh: the sha256 of the ans
raw_responses.json it judged, which must be the one there now) and the retrieval
metric_version, then computes per question and arm the
coverage / strict means (_ba_stats.unit_mean; a failed generation or invalid judgement is
not a valid repetition), the three pairs with Holm, verdict() and prod_action(), and the
descriptive items of §5. An arm that was not generated for a question (its context equals
ctrl's) takes ctrl's values there. Nothing here changes a verdict.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import _ba_checks as ck
import _ba_io as bio
import _ba_stats as st

ARMS = ck.ARMS
PAIR_NAMES = tuple(f"{x}:{y}" for x, y in st.PAIRS)
POPULATION = {"nopin:ctrl": "D_nopin", "off:ctrl": "D_off", "off:nopin": "U"}
METRIC_VERSION = "4d0826bb8d14"
NAMED = tuple(f"GENERAL_BIBLE_QUESTION_{n}" for n in ("008", "024", "040", "050", "071", "096"))
REPS, STRICT_REPS = ck.REPS, ck.STRICT_REPS


class ReportError(ValueError):
    """An input the report must refuse (§5 量尺, freeze, missing file)."""


def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from None


@dataclass(frozen=True)
class Inputs:
    out: Path
    rows: Mapping[str, Mapping[str, Any]]
    subs: Mapping[str, list[str]]
    ids: Mapping[str, list[str]]
    plan: Sequence[Mapping[str, Any]]
    gens: Mapping[tuple, Mapping[str, Any]]
    gen_metas: Sequence[Mapping[str, Any]]
    exp_meta: Mapping[str, Any]
    invariants: Mapping[str, Any]
    gt: Mapping[str, Any]
    eval3c_strict: Mapping[str, float | None]


def load_inputs(out: Path, eval3c_faith: Path) -> Inputs:
    checks = out / "checks"
    bad = ck.verify_freeze(checks, _json(checks / "freeze.json"))
    if bad:
        raise ReportError(f"frozen files changed since check: {bad}")
    _, rows = ck.load_retrieval(out / "retrieval.jsonl")
    if ck.subsets(rows) != _json(checks / "subsets.json"):
        raise ReportError("subsets.json is not what retrieval.jsonl gives")
    from src.data_loader import load_gt

    faith = _json(eval3c_faith)
    gen_lines = bio.read_jsonl(out / "gen.jsonl")
    return Inputs(out, rows, _json(checks / "subsets.json"),
                  {a: _json(checks / f"judge_ids_{a}.json") for a in ARMS},
                  _json(checks / "gen_plan.json")["items"], bio.latest_gens(gen_lines),
                  [m for m in gen_lines if m["kind"] == "meta"], _json(out / "exp_meta.json"),
                  _json(checks / "invariants.json"), load_gt("v2").by_id(),
                  {s["question_id"]: (None if s.get("invalid") else
                                      s.get("ragas_faithfulness_strict"))
                   for s in faith["samples"]})


# ---------------------------------------------------------------- judge and retrieval files

def check_judge_meta(meta: Mapping[str, Any], where: str) -> None:
    sources = meta.get("context_sources") or {}
    problems = [k for k, ok in (
        ("context_format", meta.get("context_format") == "generator_blocks"),
        ("context_sources", bool(sources) and set(sources) == {"backend"}),
        ("judge_model", meta.get("judge_model") == ck.JUDGE_MODEL),
        ("gt_version", meta.get("gt_version") == "v2"),
        ("data_build_id", meta.get("data_build_id") == ck.BUILD_ID)) if not ok]
    if problems:
        raise ReportError(f"{where}: refused, meta {problems} (§5 量尺)")


SRC_SHA = ".src_sha"          # run_ba.sh: sha256 of the ans raw_responses.json judged


def check_judge_source(out: Path, arm: str, rep: int, name: str) -> None:
    """The judge file was made from ans/{arm}_r{rep}/raw_responses.json as it is now (an
    I6 regeneration re-exports it; run_ba.sh then judges that directory again)."""
    side = out / "judge" / (name + SRC_SHA)
    raw = out / "ans" / f"{arm}_r{rep}" / "raw_responses.json"
    try:
        recorded = side.read_text(encoding="utf-8").strip()
    except OSError:
        raise ReportError(f"judge/{name}: no {side.name} (judged outside run_ba.sh?)") from None
    if not raw.exists() or recorded != bio.sha256_file(raw):
        raise ReportError(f"judge/{name}: judged from another {raw.relative_to(out)}; "
                          "run run_ba.sh again to re-judge it")


def judge_file(out: Path, arm: str, rep: int, kind: str, suffix: str = "") -> dict[str, Any]:
    name = f"{arm}_r{rep}.{'faith' if kind == 'strict' else 'cov'}{suffix}.json"
    doc = _json(out / "judge" / name)
    check_judge_meta(doc["meta"], name)
    check_judge_source(out, arm, rep, name)
    field = "ragas_faithfulness_strict" if kind == "strict" else "coverage"
    return {"values": {r["question_id"]: (None if r.get("invalid") else r.get(field))
                       for r in doc["samples"]}, "rows": {r["question_id"]: r
                                                          for r in doc["samples"]}}


def rep_values(inp: Inputs, kind: str) -> dict[str, dict[str, list[float | None]]]:
    """{arm: {q: [value of r1 … rR]}} over the arm's judge ids; failed generations → None."""
    reps = REPS if kind == "cov" else STRICT_REPS
    out: dict[str, dict[str, list]] = {}
    for arm in ARMS:
        if not inp.ids[arm]:
            out[arm] = {}
            continue
        files = [judge_file(inp.out, arm, r, kind)["values"] for r in range(1, reps + 1)]
        out[arm] = {q: [None if not (inp.gens.get((q, arm, r)) or {}).get("ok")
                        else files[r - 1].get(q) for r in range(1, reps + 1)]
                    for q in inp.ids[arm]}
    return out


def unit_values(inp: Inputs, reps: Mapping[str, Mapping[str, list]],
                kind: str) -> dict[str, dict[str, float | None]]:
    """Per arm and question of U: the unit mean; nopin / off outside D take ctrl's."""
    units = {a: {q: st.unit_mean(v, kind) for q, v in reps[a].items()} for a in ARMS}
    for arm, sub in (("nopin", "D_nopin"), ("off", "D_off")):
        for q in set(inp.subs["U"]) - set(inp.subs[sub]):
            units[arm][q] = units["ctrl"].get(q)
    return units


def retr_file(out: Path, arm: str, k: int) -> dict[str, Any]:
    doc = _json(out / "retr" / f"{arm}.k{k}.json")
    cfg = doc.get("config") or {}
    if (cfg.get("metric_version") != METRIC_VERSION or cfg.get("metric_k") != k
            or cfg.get("top_k") != 5 or (doc.get("meta") or {}).get("gt_version") != "v2"):
        raise ReportError(f"retr/{arm}.k{k}.json: metric_version / k / GT not as registered")
    return doc


def vrec_values(out: Path) -> dict[str, dict[str, float | None]]:
    out_v = {}
    for arm in ARMS:
        per_q = retr_file(out, arm, 5)["per_question"]
        out_v[arm] = {q: (None if r.get("invalid") else r.get("verse_recall_at_k"))
                      for q, r in per_q.items()}
    return out_v


# ---------------------------------------------------------------- decision

def i7_status(inp: Inputs) -> dict[str, Any]:
    missing = [it for it in inp.plan if (it["qid"], it["arm"], int(it["rep"])) not in inp.gens]
    gens = [inp.gens[k] for k in inp.gens]
    sha_bad = [bio.gen_key(g) for g in gens
               if g.get("ctx_sha") != ((inp.rows.get(g["qid"]) or {"arms": {}})["arms"].get(
                   g["arm"]) or {}).get("ctx_sha")]
    msg_bad = [bio.gen_key(g) for g in gens if g.get("messages_match") is False]
    opts_bad = [bio.gen_key(g) for g in gens if g.get("n_llm_calls") and g.get("llm_options")
                != {"temperature": 0.1, "max_tokens": 10000}]
    return {"ok": not (missing or sha_bad or msg_bad or opts_bad),
            "missing_gen": [[i["qid"], i["arm"], i["rep"]] for i in missing],
            "ctx_sha_mismatch": sha_bad, "messages_mismatch": msg_bad, "llm_options_bad": opts_bad,
            "failed_final": sorted(bio.gen_key(g) for g in gens if not g.get("ok")),
            "retried": sum(1 for g in gens if g.get("attempts", 1) > 1)}


def i0_generate(inp: Inputs) -> dict[str, Any]:
    """§6 I0 on gen.jsonl's meta lines (model, temperature, max_tokens, code identity)."""
    problems = ck.check_i0(inp.gen_metas, backend_expected=inp.exp_meta.get("backend_sha256") or {},
                           exp_expected=inp.exp_meta.get("exp_sha256") or {},
                           encoder_expected={}, exp_meta=inp.exp_meta, mode="generate")
    return {"ok": not problems, "problems": problems}


def decide(inp: Inputs, cov_u, strict_u, vrec) -> dict[str, Any]:
    i7, i0_gen = i7_status(inp), i0_generate(inp)
    required = [v["ok"] for v in inp.invariants.values() if isinstance(v, Mapping) and "ok" in v]
    inv_ok = all(required) and i7["ok"] and i0_gen["ok"]
    raw = {name: st.compare(x, y, inp.subs[POPULATION[name]], cov_u, strict_u, vrec)
           for (x, y), name in zip(st.PAIRS, PAIR_NAMES)}
    cmps = st.add_holm(raw)
    s500 = {x: st.strict_500(inp.eval3c_strict,
                             {q: strict_u[x].get(q) for q in inp.subs[f"D_{x}"]},
                             inp.subs[f"D_{x}"]) for x in ("nopin", "off")}
    verdicts = {}
    for (x, y), name in zip(st.PAIRS, PAIR_NAMES):
        n_pop = len(inp.subs[POPULATION[name]])
        cmps[name]["cov"]["to_U"] = st.scale(cmps[name]["cov"]["mean"], n_pop,
                                             max(len(inp.subs["U"]), 1))
        cmps[name]["cov"]["to_500"] = st.scale(cmps[name]["cov"]["mean"], n_pop)
        cmps[name]["strict500"] = s500.get(x) if y == "ctrl" else None
        verdicts[name] = st.verdict(cmps[name], invariants_ok=inv_ok,
                                    strict500=cmps[name]["strict500"], vs_ctrl=y == "ctrl")
    ci = cmps["off:nopin"]["cov"]["ci975"]
    action = st.prod_action(verdicts, None if ci is None else ci[1])
    return {"invariants_ok": inv_ok, "i7": i7, "i0_generate": i0_gen, "comparisons": cmps,
            "verdicts": verdicts, "prod_action": action}


# ---------------------------------------------------------------- descriptive (§5)

def _brief(diffs: Mapping[str, float], qids: Sequence[str]) -> dict[str, Any]:
    d = [diffs[q] for q in qids if q in diffs]
    out = st.describe(d)
    return {k: out[k] for k in ("n", "mean", "wins", "losses", "ties", "mde975")}


def strata(inp: Inputs, cmps: Mapping[str, Any], only_ii: Sequence[str]) -> dict[str, Any]:
    rows = inp.rows
    multi = {q for q in rows if (rows[q]["arms"]["ctrl"].get("signals") or {}).get("multi_book")}
    pinned = set(inp.subs["P_s"]) | set(inp.subs["P_m"])
    legacy = {q for q, g in inp.gt.items() if (g.family or "legacy_head") == "legacy_head"}
    groups = {"single_book": lambda q: q not in multi, "multi_book": lambda q: q in multi,
              "pinned": lambda q: q in pinned, "natural": lambda q: q not in pinned,
              "legacy_head": lambda q: q in legacy, "expanded": lambda q: q not in legacy,
              "D_nopin": lambda q: q in inp.subs["D_nopin"],
              "D_off-D_nopin": lambda q: q not in inp.subs["D_nopin"],
              "only_mechanism_ii": lambda q: q in only_ii}
    out = {}
    for name, cmp in cmps.items():
        diffs = cmp["cov"]["diffs"]
        out[name] = {g: _brief(diffs, [q for q in sorted(diffs) if f(q)])
                     for g, f in groups.items()}
    return out


def named_book_presence(inp: Inputs) -> dict[str, Any]:
    out = {}
    for arm in ARMS:
        for sub in ("D_nopin", "D_off"):
            fractions = []
            for q in inp.subs[sub]:
                rec = inp.rows[q]["arms"][arm] or inp.rows[q]["arms"]["ctrl"]
                named = (inp.rows[q]["arms"]["ctrl"].get("signals") or {}).get(
                    "detected_book_ids") or []
                core = {r.get("book_id") for r in rec["results"][:rec["n_core"]]}
                if named:
                    fractions.append(sum(b in core for b in named) / len(named))
            out[f"{arm}@{sub}"] = {"n": len(fractions),
                                   "mean_fraction": statistics.fmean(fractions) if fractions else None,
                                   "all_present": sum(f == 1.0 for f in fractions)}
    return out


def answers_by_arm(inp: Inputs) -> dict[str, dict[str, list[str]]]:
    out = {a: defaultdict(list) for a in ARMS}
    for (q, arm, rep), g in sorted(inp.gens.items()):
        out[arm][q].append(g.get("answer") or "")
    for arm, sub in (("nopin", "D_nopin"), ("off", "D_off")):
        for q in set(inp.subs["U"]) - set(inp.subs[sub]):
            out[arm][q] = list(out["ctrl"].get(q, []))
    return out


def load_refusal(path: Path, sha_prefix: str):
    if not bio.sha256_file(path).startswith(sha_prefix):
        raise ReportError(f"{path} is not the frozen refusal_v2 ({sha_prefix}…)")
    spec = importlib.util.spec_from_file_location("ba_refusal_v2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def refusals(inp: Inputs, refusal_mod) -> dict[str, Any]:
    answers = answers_by_arm(inp)
    out = {}
    for (x, y), name in zip(st.PAIRS, PAIR_NAMES):
        pop = inp.subs[POPULATION[name]]
        out[name] = {kind: st.refusal_compare(answers, x, y, pop, fn) for kind, fn in (
            ("strict_refusal", refusal_mod.is_strict_refusal),
            ("refusal_or_hedge", refusal_mod.is_refusal))}
    return out


def retrieval_descriptives(out: Path, rows: Mapping[str, Any], subs) -> dict[str, Any]:
    """500-question vrec@5/@6, MRR@5 per arm; the ledger and gold_out vs ctrl; tail MRR."""
    import quick_retrieval_eval as qre
    from src import ab_stats
    from src.data_loader import load_gt
    from src.metrics.retrieval import compute_retrieval_metrics, gold_flags
    from src.provenance import make_context, read_run_meta

    overall = {arm: {f"k{k}": retr_file(out, arm, k)["overall"] for k in (5, 6)} for arm in ARMS}
    gt = load_gt("v2")
    ctx = make_context(gt, read_run_meta(out / "retr" / "ctrl"))
    samples = {arm: {s.question_id: s for s in qre.samples_from_raw(
        out / "retr" / arm / "raw_responses.json", gt.by_id())} for arm in ARMS}

    def tagged(s):
        return [{"id": src.id, "gold": g}
                for src, g in zip(s.sources, gold_flags(s, s.sources, ctx.ruler))]

    ledgers = {}
    for x, y in (("nopin", "ctrl"), ("off", "ctrl"), ("off", "nopin")):
        entries = {q: ab_stats.ledger_entry(tagged(samples[y][q]), tagged(samples[x][q]))
                   for q in sorted(samples[y])}
        ledgers[f"{x}:{y}"] = {"counts": ab_stats.summarize_ledger(entries),
                               "gold_out": sorted(q for q, e in entries.items()
                                                  if e["status"] in ("gold_out", "gold_swap")),
                               "gold_in": sorted(q for q, e in entries.items()
                                                 if e["status"] in ("gold_in", "gold_swap"))}
    return {"overall": overall, "ledger": ledgers,
            "tail_mrr": tail_mrr(rows, subs, samples["ctrl"], ctx.ruler,
                                 compute_retrieval_metrics)}


def tail_mrr(rows, subs, ctrl_samples, ruler, compute) -> dict[str, Any]:
    """Descriptive (§3 tail): ctrl's top-k with its pinned passages moved to the core's end."""
    pairs = []
    for q in sorted(set(subs["P_s"]) | set(subs["P_m"])):
        rec, s = rows[q]["arms"]["ctrl"], ctrl_samples[q]
        pinned = {p for call in rec["pins"] for p in call["pinned"]}
        core, aux = s.sources[:rec["n_core"]], s.sources[rec["n_core"]:]
        moved = [x for x in core if x.id not in pinned] + [x for x in core if x.id in pinned]
        before, after = (next(m.value for m in compute([v], k=5, ruler=ruler)[q] if m.name == "mrr")
                         for v in (s, s.model_copy(update={"sources": moved + aux})))
        pairs.append({"qid": q, "ctrl": before, "tail": after})
    d = [p["tail"] - p["ctrl"] for p in pairs]
    return {"n": len(pairs), "mean_ctrl": statistics.fmean([p["ctrl"] for p in pairs]) if pairs
            else None, "mean_delta": statistics.fmean(d) if d else None, "per_question": pairs}


def judge_determinism(out: Path) -> dict[str, Any]:
    """(descriptive) ctrl_r1's coverage judged twice: identical scores and point verdicts."""
    if not (out / "judge" / "ctrl_r1.cov_rep.json").exists():
        return {"n": 0, "note": "ctrl_r1.cov_rep.json missing (U empty or not judged)"}
    first = judge_file(out, "ctrl", 1, "cov")
    again = judge_file(out, "ctrl", 1, "cov", suffix="_rep")
    same, points, points_same = 0, 0, 0
    qids = sorted(first["values"])
    for q in qids:
        same += first["values"][q] == again["values"].get(q)
        a = ((first["rows"][q].get("judge") or {}).get("verdicts") or {})
        b = (((again["rows"].get(q) or {}).get("judge") or {}).get("verdicts") or {})
        points += len(a)
        points_same += sum(a[k] == b.get(k) for k in a)
    return {"n": len(qids), "same_coverage": same,
            "same_fraction": same / len(qids) if qids else None,
            "point_verdicts_same": points_same, "point_verdicts": points}


def named_cases(inp: Inputs, cov_u, strict_u, vrec) -> dict[str, Any]:
    out = {}
    for q in NAMED:
        row = inp.rows.get(q)
        if row is None:
            continue
        out[q] = {"in": [k for k, v in inp.subs.items() if q in v],
                  "route": row["arms"]["ctrl"]["stats"].get("route_used"),
                  **{arm: {"ids": (row["arms"][arm] or row["arms"]["ctrl"])["ids"],
                           "cov": cov_u[arm].get(q), "strict": strict_u[arm].get(q),
                           "vrec5": vrec[arm].get(q)} for arm in ARMS}}
    return out


# ---------------------------------------------------------------- assemble

def scope_notes(action: str) -> list[str]:
    notes = ["結論範圍：只適用於 GT v2 中走 R5（含 fallback 1–2 題）的跨卷題，並以本次單一 intent "
             "抽樣的路由為條件；假說來自同一批 39 題，沒有 holdout（§13）。"]
    if action == "off":
        notes.append("採 off：R3、R4、R6 在這份 GT 上從未產生 book_anchor 候選，fallback 也只有 1–2 題，"
                     "這些路由的效果沒有量到，屬於接受的風險（§8）。")
    if action == "nopin":
        notes.append("採 nopin：多書釘選只有 GBQ_096 一題，n=1，沒有量測，所以保留（§8）。")
    if action == "keep":
        notes.append("維持現行：pins.py 的「measured neutral」改成引用本次結果，下次建映像時一起處理（§12）。")
    return notes


def build(out: Path, *, eval3c_faith: Path, refusal: Path, refusal_sha: str) -> dict[str, Any]:
    inp = load_inputs(out, eval3c_faith)
    cov_u = unit_values(inp, rep_values(inp, "cov"), "cov")
    strict_u = unit_values(inp, rep_values(inp, "strict"), "strict")
    vrec = vrec_values(out)
    decision = decide(inp, cov_u, strict_u, vrec)
    mech = _json(out / "checks" / "mechanisms.json")
    descriptive = {
        "retrieval": retrieval_descriptives(out, inp.rows, inp.subs),
        "strata": strata(inp, decision["comparisons"], mech.get("only_ii", [])),
        "named_book_in_topk": named_book_presence(inp),
        "refusals": refusals(inp, load_refusal(refusal, refusal_sha)),
        "named_cases": named_cases(inp, cov_u, strict_u, vrec),
        "judge_determinism": judge_determinism(out),
        "mechanisms": mech,
        "overlap_eval3c": _json(out / "checks" / "overlap_eval3c.json")}
    return {"meta": {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "out": str(out), "subset_sizes": {k: len(v) for k, v in inp.subs.items()}},
            "subsets": inp.subs, "invariants": {**inp.invariants, "I0_generate":
                                                 decision["i0_generate"], "I7": decision["i7"]},
            **{k: decision[k] for k in ("invariants_ok", "comparisons", "verdicts",
                                        "prod_action")},
            "per_question": {"cov": cov_u, "strict": strict_u},
            "descriptive": descriptive, "scope": scope_notes(decision["prod_action"]["action"])}


def _f(x: Any, nd: int = 3) -> str:
    return "—" if x is None else (f"{x:+.{nd}f}" if isinstance(x, float) else str(x))


def _ci(ci: Any) -> str:
    return "—" if not ci else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def render_md(rep: Mapping[str, Any]) -> str:
    act = rep["prod_action"]
    lines = ["# book_anchor 消融結果與判定", "",
             f"**prod 動作**：{act['label_zh']}（§8 第 {act['rule']} 條）", "",
             *([f"無效配對：{'、'.join(act['invalid_pairs'])}（§8 verdict 1：先補跑；"
                "上列動作只在不需要這些配對就能判定時成立）", ""]
               if act.get("invalid_pairs") else []),
             "| 配對 | 母體 n | 判定 | Δcov | cov 97.5% t-CI | Δstrict | strict 97.5% t-CI | "
             "Δvrec@5 | Holm p（cov／strict／vrec） | 剔除 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name in PAIR_NAMES:
        c, v = rep["comparisons"][name], rep["verdicts"][name]
        label = v["label_zh"] + ("（顯著改善）" if v.get("improved") else "")
        holm = "／".join(f"{c[m].get('p_holm', 1.0):.3f}" for m in st.METRICS)
        lines.append(f"| {name} | {len(c['population'])} | {label} | {_f(c['cov']['mean'])} | "
                     f"{_ci(c['cov']['ci975'])} | {_f(c['strict']['mean'])} | "
                     f"{_ci(c['strict']['ci975'])} | {_f(c['vrec5']['mean'])} | {holm} | "
                     f"{len(c['excluded'])} |")
    lines += ["", "## 換算", ""]
    for name in PAIR_NAMES:
        c = rep["comparisons"][name]
        lines.append(f"- {name}：Δcov→U {_f(c['cov'].get('to_U'))}，→500 題 "
                     f"{_f(c['cov'].get('to_500'), 4)}；500 題 strict {_f(c.get('strict500'), 4)}")
    lines += ["", "## 不變量", ""]
    for key, val in rep["invariants"].items():
        ok = val.get("ok") if isinstance(val, Mapping) else None
        lines.append(f"- {key}：{'通過' if ok else ('只報告' if ok is None else '失敗')}")
    lines += ["", "## 子集", ""] + [f"- {k}：{len(v)} 題" for k, v in rep["subsets"].items()]
    lines += ["", "## 結論範圍", ""] + [f"- {n}" for n in rep["scope"]]
    lines += ["", "描述性指標、分層、具名個案、拒答、judge 決定性與 eval3c 重疊見 report.json。", ""]
    return "\n".join(lines)
