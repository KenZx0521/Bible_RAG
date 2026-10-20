"""K-S0 verdict and descriptives of the ordered-chain arithmetic stage-0 (prereg §7, §8) -> store report.json, report.md.

Inputs: ``scores`` = score_x.score_all's output; ``items`` (a list or the items.json document); ``cards_meta`` =
arms_x's meta {item id: {covered, block_chars {arm: chars}, dropped_rows, dropped_lines, ...}}; keyword-only
``k0`` {"K0-n": {"pass": bool[, "dyn": bool, "gen": bool]} or bool} (K0-3's dynasty / Genesis parts; a missing
key is a failure), ``run_meta`` {digest_before, digest_after, version_before, version_after[, dry_run]} or a list
of them (one per formal-run segment), ``records`` {job id: generation record} (prompt tokens, seconds),
``pilot_authorized`` (None = Kay has not decided, a bool, or {family: bool}), ``pilot`` {family: {pR, gap}},
``gen_dir`` (the run directory: the scores' ``gen_sha256`` must equal its generation files now) and
``jobs_unrecoverable`` (run_x's --jobs-unrecoverable).

Refused (SystemExit, no report): scores of other generation files than gen_dir's; and, unless
``jobs_unrecoverable``, a run with missing calls (§1: fix and resume) or with a check that got no answer
(run_x state "unknown": resume to check again) while nothing else voids the run. With the flag both are 作廢.

Per judged family (DYN, GEN), in this order:
- 作廢 (§7-6): K0-1 and K0-3's dynasty part void DYN and mark S6's and SYNC's descriptives; K0-2 and K0-3's
  Genesis part void GEN; a digest or Ollama version that changed (or was not the pinned one), K0-4/5/6, and a
  missing job void every family; §1's truncation limit (counted in calls, B0′ not counted) voids that family.
- §7-1..3 on exact Fractions (floats are refused): stop when gap2 < +0.45 or gap1 < +0.45 or pR ≥ 0.40; else
  pass when gap2 ≥ +0.60; else gray (+0.45 ≤ gap2 < +0.60). GEN: pC := pB, gap1 = pG − pB.
- §1: with truncated calls, the same rules on the values without the items holding them; a changed verdict
  makes the family gray.
- Scoring sensitivity (執行紀錄): the same rules on the lenient score_any values; a changed verdict makes the
  family gray too, with a note. Both judgements are reported.
- A gray family follows §7-3: Kay undecided → 「灰區，需要盲 pilot…」; not authorized → stop (第 3 條); an
  authorized pilot's {pR, gap} stops when pR ≥ 0.65 or gap < +0.25, else passes (FE §4.1 option one).
Each judged family gets exactly one of §7-6's fixed sentences; S6 and SYNC get none. §7-4 (B0′ per GEN question
type), §7-5 (power_x.power_report on the families whose final status is pass, gray, gray_pilot_pending or
pilot_pass) and §8 are description only. Everything is 開發集. A dry run (假 chat) prefixes every sentence with
DRY_RUN and its status with 「dry_run:」. Nothing here calls an LLM; ``write_report`` writes report.json and
report.md (store only, numbers and ids: no question, answer, card or scripture text).
"""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from statistics import median

import power_x as P
import score_x as S
import x_common as X

STOP_GAP, PASS_GAP2, PR_MAX = Fraction(45, 100), Fraction(60, 100), Fraction(40, 100)   # §7-1..3
PILOT_PR_STOP, PILOT_GAP_STOP = Fraction(65, 100), Fraction(25, 100)                   # §7-3 (FE §4.1)
B0P_NAMED = Fraction(1, 2)                                                              # §7-4
POWER_C = {"DYN": 9, "GEN": 8}                                                          # §7-5 (both: 17)
A_S1_TEMPLATE_GAP2 = Fraction(11, 18)   # §8: experiment A's 18 S1 template items, G-auto 0.917 − T-rows 0.306
FAMILIES = ("DYN", "S6", "SYNC", "GEN")
DYN_SIDE = ("DYN", "S6", "SYNC")         # what K0-1 and K0-3's dynasty part void or mark
GEN_TYPES = ("F1_5", "F1_11", "F3", "F5")
SUBTYPE_ORDER = ("S5_L3", "S5_L4", "S5_L5", "S5_L6", "S6", "SYNC2", "SYNC3") + GEN_TYPES
K0_KEYS = ("K0-1", "K0-2", "K0-3", "K0-4", "K0-5", "K0-6")
LABEL = "開發集 stage-0（不構成證據）"
DRY_RUN = "【dry run，假 chat，無意義】"
POWER_STATUS = ("pass", "gray", "gray_pilot_pending", "pilot_pass")    # §7-5: passing or gray, not stopped
RUN_KEYS = ("digest_before", "digest_after", "version_before", "version_after")
NON_NAMED = "確認集該題型改出非名題"

# §7-6, verbatim; {why}, {pR}, {gap}, {family} fill the prereg's …, 〈族〉 and K0-〈n〉
SENTENCE = {
    "stop": "依事先規則停止（第 1 條：{why}），不構成無效證據",
    "pass": "開發集通過，可以請 Kay 授權確認集",
    "gray": "灰區，需要盲 pilot（約 6 USD），請 Kay 決定",
    "gray_not_authorized": "灰區，Kay 未授權盲 pilot，依事先規則停止（第 3 條），不構成無效證據",
    "pilot_stop": "盲 pilot 依事先規則停止（pR＝{pR}／gap＝{gap}），不構成無效證據",
    "pilot_pass": "盲 pilot 通過，可以請 Kay 授權確認集",
    "void": "作廢（{family}，{why}）",
}
VOID_WHY = {"run_meta": "run_meta 缺", "digest": "digest", "version": "Ollama 版本", "missing": "缺漏 job",
            "truncation": "截斷超限"}
CLAUSE = {"gap2": ("<", "+0.45", True), "gap1": ("<", "+0.45", True), "pR": ("≥", "0.40", False)}


# ---------------------------------------------------------------- exact values
def frac(v) -> Fraction | None:
    """A score_x value ({"frac": …}), Fraction, int or "a/b" as a Fraction; floats are refused (exactness)."""
    if v is None:
        return None
    if isinstance(v, dict):
        return Fraction(v["frac"])
    if isinstance(v, (bool, float)) or not isinstance(v, (Fraction, int, str)):
        raise TypeError(f"{v!r}: exact values only (Fraction, int, 'a/b' or a score_x value)")
    return Fraction(v)


def fx(f: Fraction | None, n: int | None = None) -> dict | None:
    return S.fx(f, n)


def _sub(a: Fraction | None, b: Fraction | None) -> Fraction | None:
    return None if a is None or b is None else a - b


def family_values(means: dict, family: str) -> dict:
    """pG, pR, pC (GEN: pC := pB), pB, gap2 = pG − pR, gap1 = pG − pC, from {arm: Fraction | None}."""
    pc_arm = "B0" if family == "GEN" else "T-canon"
    g, r, c, b = (means.get(a) for a in ("G", "T-rows", pc_arm, "B0"))
    return {"pG": g, "pR": r, "pC": c, "pB": b, "gap2": _sub(g, r), "gap1": _sub(g, c), "pC_arm": pc_arm}


def values_json(v: dict) -> dict:
    return {k: (x if k == "pC_arm" else fx(x)) for k, x in v.items()}


def judge(gap2: Fraction | None, gap1: Fraction | None, pR: Fraction | None) -> dict:
    """§7-1..3: {"category": "stop" | "pass" | "gray" | None (a value undefined), "clauses": [stop clauses]}."""
    vals = {"gap2": gap2, "gap1": gap1, "pR": pR}
    if any(x is None for x in vals.values()):
        return {"category": None, "clauses": []}
    for k, x in vals.items():
        if isinstance(x, (bool, float)) or not isinstance(x, (Fraction, int)):
            raise TypeError(f"{k}={x!r}: the verdict compares exact Fractions only (prereg §5)")
    clauses = [k for k, bad in (("gap2", gap2 < STOP_GAP), ("gap1", gap1 < STOP_GAP), ("pR", pR >= PR_MAX)) if bad]
    if clauses:
        return {"category": "stop", "clauses": clauses}
    return {"category": "pass" if gap2 >= PASS_GAP2 else "gray", "clauses": []}


def num(f: Fraction, signed: bool = True) -> str:
    return f"{float(f):+.3f}（{f}）" if signed else f"{float(f):.3f}（{f}）"


def stop_why(v: dict, clauses: list[str]) -> str:
    return "；".join(f"{c}＝{num(v[c], CLAUSE[c][2])}{CLAUSE[c][0]}{CLAUSE[c][1]}" for c in clauses)


# ---------------------------------------------------------------- 作廢 (§7-6, §1)
def _ok(entry, part: str | None = None) -> bool:
    if isinstance(entry, bool):
        return entry
    if not isinstance(entry, dict) or entry.get("pass") is False:
        return False
    if part is not None and part in entry:
        return entry[part] is True
    return entry.get("pass") is True


def k0_voids(k0: dict | None) -> dict[str, list[str]]:
    """{family: K0 reasons} under §7-6's scopes (S6 and SYNC carry the dynasty reasons as a mark)."""
    k0, out = k0 or {}, {f: [] for f in FAMILIES}

    def add(fams, why):
        for f in fams:
            if why not in out[f]:
                out[f].append(why)

    if not _ok(k0.get("K0-1")):
        add(DYN_SIDE, "K0-1")
    if not _ok(k0.get("K0-2")):
        add(("GEN",), "K0-2")
    if not _ok(k0.get("K0-3"), "dyn"):
        add(DYN_SIDE, "K0-3")
    if not _ok(k0.get("K0-3"), "gen"):
        add(("GEN",), "K0-3")
    for k in ("K0-4", "K0-5", "K0-6"):
        if not _ok(k0.get(k)):
            add(FAMILIES, k)
    return out


def _metas(run_meta) -> list[dict]:
    return [run_meta] if isinstance(run_meta, dict) else list(run_meta or [])


def run_problems(run_meta, known_only: bool = False) -> list[str]:
    """§1: every digest check the pinned digest, and one Ollama version before and after (all segments).
    known_only: a check that got no answer (None) is left out (``run_unknown`` lists those)."""
    metas = _metas(run_meta)
    if not metas:
        return ["run_meta"]
    out = []
    digests = [m.get(k) for m in metas for k in ("digest_before", "digest_after")]
    if any(d != X.EXPECTED_DIGEST for d in digests if not (known_only and d is None)):
        out.append("digest")
    versions = [m.get(k) for m in metas for k in ("version_before", "version_after")]
    if (None in versions and not known_only) or len({v for v in versions if v is not None}) > 1:
        out.append("version")
    return out


def run_unknown(run_meta) -> list[str]:
    """segment|key of every check value that got no answer (run_x's state "unknown")."""
    return [f"{i}|{k}" for i, m in enumerate(_metas(run_meta), 1) for k in RUN_KEYS if m.get(k) is None]


def gen_problems(scores: dict, gen_dir: Path | str | None) -> list[str]:
    """The scored generation files (scores' gen_sha256) against gen_dir's files now; [] without gen_dir."""
    if gen_dir is None:
        return []
    rec = scores.get("gen_sha256")
    if not rec:
        return ["the scores record no gen_sha256 (an older score_x)"]
    now = S.gen_sha256(gen_dir, tuple(rec))
    return [f"{n}: scored {rec[n]}, now {now[n]}" for n in rec if rec[n] != now[n]]


def refusals(scores: dict, missing: list[str], run_meta, gen_dir, jobs_unrecoverable: bool) -> list[str]:
    """Why no report is made yet (score again, or resume the run); [] = go on."""
    out = [f"scores are not of the current generation files ({p}): run score again"
           for p in gen_problems(scores, gen_dir)]
    if jobs_unrecoverable or run_problems(run_meta, known_only=True):
        return out                                   # the flag, or a run that is void anyway: 作廢 is reported
    jobs = scores.get("missing_jobs") or []
    if missing or jobs:
        out.append(f"{len(missing)} prereg calls without a scored record, {len(jobs)} jobs missing: fix and resume "
                   "the run (§1); only if they cannot be done pass jobs_unrecoverable (the report is then 作廢)")
    unknown = run_unknown(run_meta)
    if unknown:
        out.append(f"checks without an answer ({'、'.join(unknown)}): resume the run to check again; only if that "
                   "cannot be done pass jobs_unrecoverable (the report is then 作廢)")
    return out


def expected_arms(family: str) -> tuple[str, ...]:
    return X.ARMS[family] + ((X.B0_BARE,) if family == "GEN" else ())


def expected_calls(items: list[dict]) -> int:
    return sum(X.REPS_BY_ARM[a] for it in items for a in expected_arms(it["family"]))


def missing_calls(scores: dict, items: list[dict]) -> list[str]:
    """item|arm|rep of every prereg call (§4 次數) without a scored record."""
    out = []
    for it in items:
        reps = (scores["items"].get(it["id"]) or {}).get("reps") or {}
        out += [f"{it['id']}|{a}|{r}" for a in expected_arms(it["family"]) for r in range(1, X.REPS_BY_ARM[a] + 1)
                if reps.get(f"{a}|{r}") is None]
    return out


def void_reasons(scores: dict, families: list[str], k0, run_meta, missing: list[str]) -> dict[str, list[str]]:
    out = k0_voids(k0)
    every = [VOID_WHY[p] for p in run_problems(run_meta)]
    if missing or scores.get("missing_jobs"):
        every.append(VOID_WHY["missing"])
    trunc = S.truncation_problems(scores.get("truncation") or {})
    for f in FAMILIES:
        out[f] += every + ([VOID_WHY["truncation"]] if f in trunc else [])
    return {f: out[f] for f in families}


# ---------------------------------------------------------------- one judged family
def auth_of(pilot_authorized, family: str) -> bool | None:
    a = pilot_authorized.get(family) if isinstance(pilot_authorized, dict) else pilot_authorized
    if a is not None and not isinstance(a, bool):
        raise TypeError(f"pilot_authorized[{family}] = {a!r}: None, True or False")
    return a


def pilot_outcome(res: dict) -> tuple[str, str, dict]:
    pr, gap = frac(res["pR"]), frac(res["gap"])
    vals = {"pR": fx(pr), "gap": fx(gap)}
    if pr >= PILOT_PR_STOP or gap < PILOT_GAP_STOP:
        return "pilot_stop", SENTENCE["pilot_stop"].format(pR=f"{float(pr):.3f}", gap=f"{float(gap):+.3f}"), vals
    return "pilot_pass", SENTENCE["pilot_pass"], vals


def outcome(family: str, category: str | None, v: dict, clauses: list[str], voids: list[str],
            auth: bool | None, pilot_res: dict | None) -> dict:
    """The family's status and its one §7-6 sentence."""
    if pilot_res is not None and (voids or category != "gray" or auth is not True):
        raise ValueError(f"{family}: blind-pilot results need a gray family and Kay's authorization")
    if voids:
        return {"status": "void", "sentence": SENTENCE["void"].format(family=family, why="、".join(voids))}
    if category is None:
        raise ValueError(f"{family}: a family value is undefined but nothing voids the family")
    if category == "stop":
        return {"status": "stop", "sentence": SENTENCE["stop"].format(why=stop_why(v, clauses))}
    if category == "pass":
        return {"status": "pass", "sentence": SENTENCE["pass"]}
    if auth is None:
        return {"status": "gray", "sentence": SENTENCE["gray"]}
    if auth is False:
        return {"status": "gray_not_authorized", "sentence": SENTENCE["gray_not_authorized"]}
    if pilot_res is None:
        return {"status": "gray_pilot_pending", "sentence": SENTENCE["gray"],
                "note": "Kay 已授權盲 pilot，等 pilot 結果（另立事前登記）"}
    status, sentence, vals = pilot_outcome(pilot_res)
    return {"status": status, "sentence": sentence, "pilot": vals}


def any_note(strict: str | None, lenient: str | None) -> str:
    return f"寬鬆計分（score_any）判定 {lenient}，嚴格計分判定 {strict}：判定改變，改判灰區（執行紀錄）"


def rejudge(block: dict | None, family: str, full: dict) -> dict:
    """§7-1..3 on another set of family means; changed = its category differs from the full judgement's."""
    ev = family_values({a: frac(m) for a, m in (block or {}).items()}, family)
    ej = judge(ev["gap2"], ev["gap1"], ev["pR"])
    return {"values": values_json(ev), "category": ej["category"], "clauses": ej["clauses"],
            "changed": ej["category"] != full["category"]}


def family_verdict(family: str, scores: dict, voids: list[str], auth: bool | None, pilot_res: dict | None) -> dict:
    means = {a: frac(m) for a, m in (scores["families"].get(family) or {}).items()}
    v = family_values(means, family)
    full = judge(v["gap2"], v["gap1"], v["pR"])
    category, excl = full["category"], None
    ex = (scores.get("families_excl_truncated") or {}).get(family) or {}
    if ex.get("items_dropped"):
        excl = {"items_dropped": list(ex["items_dropped"]), **rejudge(ex["means"], family, full)}
        if excl["changed"]:
            category = "gray"
    if "families_any" not in scores:
        raise ValueError("the scores have no families_any (an older score_x): run score again")
    lenient = rejudge(scores["families_any"].get(family), family, full)
    if lenient["changed"]:
        category = "gray"
    out = outcome(family, category, v, full["clauses"], voids, auth, pilot_res)
    if lenient["changed"] and out["status"] != "void":
        out["note"] = "；".join(n for n in (out.get("note"), any_note(full["category"], lenient["category"])) if n)
    return {"family": family, "values": values_json(v), "rule": full, "excl_truncated": excl, "score_any": lenient,
            "category": category, "gray_by_truncation": bool(excl and excl["changed"]),
            "gray_by_score_any": lenient["changed"], "void": list(voids), "pilot_authorized": auth, **out}


def mark_dry_run(v: dict) -> dict:
    """A dry run's verdict: every sentence prefixed with DRY_RUN, the status with 「dry_run:」."""
    return {**v, "status": f"dry_run:{v['status']}", "sentence": DRY_RUN + v["sentence"]}


# ---------------------------------------------------------------- §7-4 B0′
def b0_bare(scores: dict, items: list[dict], voids: list[str]) -> dict:
    n = {t: sum(S.subtype(it) == t for it in items) for t in GEN_TYPES}
    types = {}
    for t in GEN_TYPES:
        g = scores["groups"].get(t)
        if not g:
            continue
        b = frac(g.get(X.B0_BARE))
        named = b is not None and b >= B0P_NAMED
        types[t] = {"n_items": n[t], "B0p": fx(b), "B0": fx(frac(g.get("B0"))), "G": fx(frac(g.get("G"))),
                    "non_named": named, "note": NON_NAMED if named else None}
    fam = scores["families"].get("GEN") or {}
    return {"rule": f"B0′ ≥ 0.5 時{NON_NAMED}（設計註記，不是判定）", "types": types,
            "family": {"B0p": fx(frac(fam.get(X.B0_BARE))), "B0": fx(frac(fam.get("B0")))}, "void": list(voids)}


# ---------------------------------------------------------------- §7-5 power
def power_section(scores: dict, items: list[dict], cards_meta: dict, verdicts: dict, nsim: int) -> dict:
    fams = tuple(f for f in X.JUDGED if f in verdicts and verdicts[f]["status"] in POWER_STATUS)
    if not fams:
        return {"families": [], "C": None, "report": None, "notes": ["沒有通過或灰區（未停）的族，不算檢定力"]}
    C = sum(POWER_C[f] for f in fams)
    covered = {it["id"]: bool(cards_meta[it["id"]]["covered"]) for it in items if it["family"] in fams}
    rows = P.rows_from_scores(scores, items, covered, fams)
    rep = P.power_report(rows, (C,), P.M_VALUES, nsim)
    notes = [f"{f}：nested {c['n_nested']}/{c['n_items']}，{c['note']}" for f, c in rep["nested_check"].items()
             if c["redefine_units"]]
    for sub in ("all", "nested"):
        s = (rep["subsets"].get(sub) or {}).get("min_C") or {}
        notes += [f"{sub} ({k}) m={m}：{v['note']}" for k, by_m in s.items() for m, v in by_m.items() if v["note"]]
    return {"families": list(fams), "C": C, "proposal_set": "ii", "report": rep, "notes": notes}


# ---------------------------------------------------------------- §8 descriptives
def arm_table(block: dict | None, family: str) -> dict:
    block = block or {}
    return {"means": dict(block), **S.gaps_of({a: frac(m) for a, m in block.items()}, family)}


def subset_means(scores: dict, ids: list[str], field: str = "mean") -> dict:
    rows = [scores["items"][i] for i in ids]
    arms = [a for a in S.ARM_ORDER if any(a in (r.get(field) or {}) for r in rows)]
    return {a: S.mean_f([frac(r[field][a]) for r in rows if a in (r.get(field) or {})]) for a in arms}


def subset_table(scores: dict, ids: list[str], family: str, n_family: int) -> dict:
    m = subset_means(scores, ids) if ids else {}
    return {"n_items": len(ids), "n_family": n_family, "ids": list(ids),
            "means": {a: fx(x, len(ids)) for a, x in m.items()}, **S.gaps_of(m, family)}


def sync_desc(scores: dict) -> dict:
    fz = scores.get("families_z") or {}
    gz = scores.get("groups_z") or {}
    both, z = arm_table(scores["families"].get("SYNC"), "SYNC"), arm_table(fz.get("SYNC"), "SYNC")
    return {"both_keys": both, "z_only": z,
            "by_k": {t: {"both_keys": arm_table(scores["groups"].get(t), "SYNC"), "z_only": arm_table(gz.get(t), "SYNC")}
                     for t in ("SYNC2", "SYNC3") if t in scores["groups"]},
            "A_S1_template_gap2": fx(A_S1_TEMPLATE_GAP2),
            "note": "SYNC 不單獨判定；H2 主要量「數第 k 位」，和 A 開發集 S1 模板題的 G−T-rows 並列"}


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "min": None, "max": None}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "min": min(xs), "max": max(xs)}


def block_chars(items: list[dict], cards_meta: dict) -> dict:
    out = {}
    for f in FAMILIES:
        ids = [it["id"] for it in items if it["family"] == f]
        if not ids:
            continue
        chars = [cards_meta[i].get("block_chars") or cards_meta[i].get("aux_chars") or {} for i in ids]
        arms = [a for a in S.ARM_ORDER if any(a in c for c in chars)]
        out[f] = {a: _stats([c[a] for c in chars if c.get(a) is not None]) for a in arms}
    over = sorted(i for i, m in cards_meta.items() if any(n > X.CAP_CHARS for n in
                                                         (m.get("block_chars") or m.get("aux_chars") or {}).values()
                                                         if n is not None))
    return {"by_family": out, "cap": X.CAP_CHARS, "over_cap_items": over}


def drops(cards_meta: dict) -> dict:
    return {"rows": sum(m.get("dropped_rows") or 0 for m in cards_meta.values()),
            "lines": sum(m.get("dropped_lines") or 0 for m in cards_meta.values()),
            "items": sorted(i for i, m in cards_meta.items() if (m.get("dropped_rows") or 0) + (m.get("dropped_lines") or 0))}


def call_stats(scores: dict, records: dict | None) -> dict | None:
    """Prompt and eval tokens and seconds per call, per family and arm, from the generation records."""
    if records is None:
        return None
    acc: dict = {}
    for row in scores["items"].values():
        for k, v in row["reps"].items():
            rec = records.get(v["job_id"]) if v else None
            if rec is None:
                continue
            a = acc.setdefault(row["family"], {}).setdefault(k.split("|")[0], {"p": [], "e": [], "s": []})
            for key, name in (("p", "prompt_eval_count"), ("e", "eval_count"), ("s", "elapsed_s")):
                if rec.get(name) is not None:
                    a[key].append(rec[name])
    out, secs = {}, []
    for f, by_arm in acc.items():
        out[f] = {}
        for arm in [a for a in S.ARM_ORDER if a in by_arm] + sorted(set(by_arm) - set(S.ARM_ORDER)):
            a = by_arm[arm]
            secs += a["s"]
            out[f][arm] = {"prompt_tokens": _stats(a["p"]), "eval_tokens": _stats(a["e"]),
                           "seconds": dict(_stats(a["s"]), median=median(a["s"]) if a["s"] else None,
                                           total=sum(a["s"]))}
    return {"by_family": out, "seconds_total": sum(secs), "seconds_per_call": sum(secs) / len(secs) if secs else None}


def truncated_calls(scores: dict) -> list[str]:
    return sorted(f"{i}|{k}" for i, row in scores["items"].items() for k, v in row["reps"].items()
                  if v and v.get("truncated"))


def describe(scores: dict, items: list[dict], cards_meta: dict, records: dict | None) -> dict:
    fam_of = {S.subtype(it): it["family"] for it in items}
    by_fam = {f: [it for it in items if it["family"] == f] for f in FAMILIES}
    subs = [t for t in SUBTYPE_ORDER if t in scores["groups"]] + sorted(set(scores["groups"]) - set(SUBTYPE_ORDER))
    tc = {f: subset_table(scores, [it["id"] for it in by_fam[f] if it.get("tcanon_complete")], f, len(by_fam[f]))
          for f in DYN_SIDE if by_fam[f]}
    nested = {f: subset_table(scores, [it["id"] for it in by_fam[f] if it.get("nested")], f, len(by_fam[f]))
              for f in FAMILIES if by_fam[f]}
    cov = [it["id"] for it in items if cards_meta[it["id"]]["covered"]]
    return {"families": {f: arm_table(scores["families"][f], f) for f in FAMILIES if f in scores["families"]},
            "families_any": {f: arm_table((scores.get("families_any") or {}).get(f), f) for f in FAMILIES
                             if f in (scores.get("families_any") or {})},
            "subtypes": {t: dict(arm_table(scores["groups"][t], fam_of.get(t, "")), family=fam_of.get(t)) for t in subs},
            "sync": sync_desc(scores) if by_fam["SYNC"] else None,
            "tcanon_complete": tc, "nested": nested, "counts": scores.get("counts") or {},
            "truncation": scores.get("truncation") or {}, "truncated_calls": truncated_calls(scores),
            "covered": {"a": fx(Fraction(len(cov), len(items))) if items else None,
                        "not_covered": sorted(set(it["id"] for it in items) - set(cov))},
            "block_chars": block_chars(items, cards_meta), "drops": drops(cards_meta),
            "calls": call_stats(scores, records)}


# ---------------------------------------------------------------- the report
def _items(items) -> list[dict]:
    return items["items"] if isinstance(items, dict) else list(items)


def check_inputs(scores: dict, items: list[dict], cards_meta: dict) -> None:
    ids = [it["id"] for it in items]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate item ids")
    extra = sorted(set(scores["items"]) - set(ids))
    if extra:
        raise ValueError(f"scores for unknown items {extra}")
    bad = sorted(i for i in ids if "covered" not in (cards_meta.get(i) or {}))
    if bad:
        raise ValueError(f"cards_meta without covered for {bad}")
    unknown = sorted({it["family"] for it in items} - set(FAMILIES))
    if unknown:
        raise ValueError(f"unknown families {unknown}")


def _pilot_json(pilot: dict) -> dict:
    return {f: {k: fx(frac(v)) for k, v in r.items()} for f, r in pilot.items()}


def analyze(scores: dict, items, cards_meta: dict, *, pilot_authorized=None, pilot: dict | None = None,
            k0: dict | None = None, run_meta=None, records: dict | None = None, nsim: int = P.NSIM,
            gen_dir: Path | str | None = None, jobs_unrecoverable: bool = False) -> dict:
    """The stage-0 report (prereg §7, §8) as a JSON-ready dict; writes nothing (``write_report`` does)."""
    items, pilot = _items(items), dict(pilot or {})
    check_inputs(scores, items, cards_meta)
    fams = [f for f in FAMILIES if any(it["family"] == f for it in items)]
    judged = [f for f in X.JUDGED if f in fams]
    stray = sorted(set(pilot) - set(judged))
    if stray:
        raise ValueError(f"blind-pilot results for families that are not judged here: {stray}")
    missing = missing_calls(scores, items)
    refused = refusals(scores, missing, run_meta, gen_dir, jobs_unrecoverable)
    if refused:
        raise SystemExit("analyze refused, no report: " + "; ".join(refused))
    voids = void_reasons(scores, fams, k0, run_meta, missing)
    verdicts = {f: family_verdict(f, scores, voids[f], auth_of(pilot_authorized, f), pilot.get(f)) for f in judged}
    power = power_section(scores, items, cards_meta, verdicts, nsim)
    dry = any(m.get("dry_run") for m in _metas(run_meta))
    if dry:
        verdicts = {f: mark_dry_run(v) for f, v in verdicts.items()}
    gen_items = [it for it in items if it["family"] == "GEN"]
    return {
        "schema": "arith.report.v2", "label": LABEL, "dry_run": dry,
        "n_items": len(items), "families": fams,
        "calls": {"expected": expected_calls(items), "scored": sum(v is not None for r in scores["items"].values()
                                                                    for v in r["reps"].values()),
                  "missing_calls": missing, "missing_jobs": list(scores.get("missing_jobs") or [])},
        "verdicts": verdicts, "sentences": {f: v["sentence"] for f, v in verdicts.items()},
        "described": {f: {"sentence": None, "void": voids[f]} for f in X.DESCRIBED if f in fams},
        "b0_bare": b0_bare(scores, gen_items, voids["GEN"]) if gen_items else None,
        "power": power,
        "descriptive": describe(scores, items, cards_meta, records),
        "thresholds": {"stop_gap": str(STOP_GAP), "pass_gap2": str(PASS_GAP2), "pR_max": str(PR_MAX),
                       "pilot_pR_stop": str(PILOT_PR_STOP), "pilot_gap_stop": str(PILOT_GAP_STOP),
                       "b0p_named": str(B0P_NAMED), "power_C": POWER_C},
        "inputs": {"k0": k0, "run_meta": run_meta, "pilot_authorized": pilot_authorized, "pilot": _pilot_json(pilot),
                   "gen_sha256": scores.get("gen_sha256"), "gen_checked": gen_dir is not None,
                   "jobs_unrecoverable": bool(jobs_unrecoverable)},
        "code_sha256": {p: X.sha256_file(X.HERE / p)
                        for p in ("prereg.md", "analyze_x.py", "score_x.py", "keys_x.py", "power_x.py")},
    }


# ---------------------------------------------------------------- report.md (store only)
def f3(x) -> str:
    if isinstance(x, dict):
        x = x.get("float")
    return "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def fs(x) -> str:
    if isinstance(x, dict):
        x = x.get("float")
    return "—" if x is None else f"{x:+.3f}"


def fr(x) -> str:
    return "—" if x is None else f"{x['float']:.3f}（{x['frac']}）"


def _verdict_lines(rep: dict) -> list[str]:
    lines = ["## K-S0 判定（只判 DYN、GEN；門檻：停 gap2<+0.45 或 gap1<+0.45 或 pR≥0.40；過 gap2≥+0.60）", "",
             "| 族 | pG | pR | pC | pB | gap2（H2） | gap1（H1） | 規則 | 判定 |", "|---|---|---|---|---|---|---|---|---|"]
    for f, v in rep["verdicts"].items():
        x = v["values"]
        lines.append(f"| {f} | {fr(x['pG'])} | {fr(x['pR'])} | {fr(x['pC'])}（{x['pC_arm']}） | {fr(x['pB'])} | "
                     f"{fr(x['gap2'])} | {fr(x['gap1'])} | {v['rule']['category'] or '—'} | {v['status']} |")
    lines.append("")
    for f, v in rep["verdicts"].items():
        lines.append(f"- **{f}**：{v['sentence']}")
        if v.get("note"):
            lines.append(f"  - {v['note']}")
        ex = v["excl_truncated"]
        if ex:
            lines.append(f"  - 剔除含截斷呼叫的題（{'、'.join(ex['items_dropped'])}）：gap2 {fs(ex['values']['gap2'])}、"
                         f"gap1 {fs(ex['values']['gap1'])}、pR {f3(ex['values']['pR'])} → {ex['category']}"
                         + ("；判定改變，改判灰區（§1）" if ex["changed"] else "；判定不變"))
        sa = v.get("score_any")
        if sa:
            lines.append(f"  - 寬鬆計分 score_any（敏感度，執行紀錄）：gap2 {fs(sa['values']['gap2'])}、gap1 "
                         f"{fs(sa['values']['gap1'])}、pR {f3(sa['values']['pR'])} → {sa['category'] or '—'}"
                         + ("；判定改變，改判灰區" if sa["changed"] else "；判定不變"))
        if v.get("pilot"):
            lines.append(f"  - 盲 pilot：pR {f3(v['pilot']['pR'])}、gap {fs(v['pilot']['gap'])}"
                         "（停：pR≥0.65 或 gap<+0.25）")
    for f, d in rep["described"].items():
        lines.append(f"- {f}：只描述，沒有判定句" + (f"；描述標作廢（{'、'.join(d['void'])}）" if d["void"] else ""))
    return lines + [""]


def _b0_lines(rep: dict) -> list[str]:
    b = rep["b0_bare"]
    if not b:
        return []
    lines = ["## GEN 名數字檢查（§7-4，B0′，描述）", "", f"- {b['rule']}", "",
             "| 題型 | 題數 | B0′ | B0 | G | 註記 |", "|---|---|---|---|---|---|"]
    for t, r in b["types"].items():
        lines.append(f"| {t} | {r['n_items']} | {fr(r['B0p'])} | {f3(r['B0'])} | {f3(r['G'])} | {r['note'] or '—'} |")
    return lines + [""]


def _power_lines(rep: dict) -> list[str]:
    pw = rep["power"]
    lines = ["## 檢定力（§7-5，描述，不是停損；確認集提案只用 (ii)）", ""]
    if not pw["report"]:
        return lines + [f"- {n}" for n in pw["notes"]] + [""]
    r = pw["report"]
    lines += [f"- 族：{'、'.join(pw['families'])}；C＝{pw['C']}；nsim {r['model']['nsim']}；種子 {r['model']['seed']}（每格重設）", ""]
    for sub, s in r["subsets"].items():
        if not s:
            lines.append(f"- {sub}：沒有題")
            continue
        lines += [f"### {sub}（{len(s['ids'])} 題）", "", "| 輸入 | a | h | pR | pC | gap | m | pow_H1 | pow_H1_and_H2 | 最小 C（≥0.7） |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for k in ("i", "ii"):
            inp = s["inputs"][k]
            for c in s["cells"][k]:
                mc = s["min_C"][k][str(c["m"])]
                lines.append(f"| ({k}) | {inp['a']:.3f} | {inp['h']:.3f} | {inp['pR']:.3f} | {inp['pC']:.3f} | "
                             f"{inp['gap']:.3f} | {c['m']} | {c['pow_H1']} | {c['pow_H1_and_H2']} | {mc['C'] or mc['note']} |")
        lines.append("")
    return lines + [f"- {n}" for n in pw["notes"]] + [""]


def _means_row(label: str, t: dict, arms) -> str:
    return (f"| {label} | " + " | ".join(f3((t["means"] or {}).get(a)) for a in arms)
            + f" | {fs(t['gap2'])} | {fs(t['gap1'])} |")


def _desc_lines(rep: dict) -> list[str]:
    d, arms = rep["descriptive"], S.ARM_ORDER
    head = "| " + " | ".join(arms) + " | H2 | H1 |"
    lines = ["## 描述（§8，不進判定）", "", "### 各族的各臂平均（題層）", "",
             "| 族 " + head, "|---|" + "---|" * (len(arms) + 2)]
    lines += [_means_row(f, t, arms) for f, t in d["families"].items()]
    if d.get("families_any"):
        lines += ["", "### 寬鬆計分 score_any 的各臂平均（敏感度，執行紀錄）", "", "| 族 " + head,
                  "|---|" + "---|" * (len(arms) + 2)]
        lines += [_means_row(f, t, arms) for f, t in d["families_any"].items()]
    lines += ["", "### 各題型的各臂平均（S5 依 L、F1 依章）", "", "| 題型 " + head, "|---|" + "---|" * (len(arms) + 2)]
    lines += [_means_row(t, r, arms) for t, r in d["subtypes"].items()]
    if d["sync"]:
        s = d["sync"]
        lines += ["", "### SYNC（兩鍵都中／只看 Z；並列 A 開發集 S1 模板 G−T-rows）", "", "| 組 " + head,
                  "|---|" + "---|" * (len(arms) + 2), _means_row("SYNC 兩鍵", s["both_keys"], arms),
                  _means_row("SYNC 只看 Z", s["z_only"], arms)]
        lines += [_means_row(f"{k} {lab}", v[key], arms) for k, v in s["by_k"].items()
                  for key, lab in (("both_keys", "兩鍵"), ("z_only", "只看 Z"))]
        lines += ["", f"- A 開發集 S1 模板題 G−T-rows：{fs(s['A_S1_template_gap2'])}；{s['note']}"]
    for title, key in (("tcanon_complete 子集（T-canon 窗含齊依據節）", "tcanon_complete"), ("nested 子集", "nested")):
        lines += ["", f"### {title}", "", "| 族 | 題數 " + head, "|---|---|" + "---|" * (len(arms) + 2)]
        lines += [_means_row(f"{f} | {t['n_items']}/{t['n_family']}", t, arms) for f, t in d[key].items()]
    lines += ["", "### 呼叫層", "", "| 族 | 臂 | 呼叫 | 答對 | 寬鬆答對 | 格式失敗 | 截斷 | hedge | 沒取到值 | 干擾值 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for f, by_arm in d["counts"].items():
        for a, c in by_arm.items():
            dist = "、".join(f"{k} {n}" for k, n in c["distractor"].items()) or "—"
            lines.append(f"| {f} | {a} | {c['calls']} | {c['correct']} | {c.get('correct_any', '—')} | "
                         f"{c['format_fail']} | {c['truncated']} | {c['hedge']} | {c['no_value']} | {dist} |")
    lines += ["", f"- 截斷呼叫：{'、'.join(d['truncated_calls']) or '無'}",
              f"- 推導行含 gold 的題比例 a＝{f3(d['covered']['a'])}；不含的題：{'、'.join(d['covered']['not_covered']) or '無'}",
              f"- 刪列 {d['drops']['rows']}、刪行 {d['drops']['lines']}；超過 {d['block_chars']['cap']} 字的題："
              f"{'、'.join(d['block_chars']['over_cap_items']) or '無'}", "",
              "### 附加區塊字數", "", "| 族 | 臂 | n | 平均 | 最小 | 最大 |", "|---|---|---|---|---|---|"]
    for f, by_arm in d["block_chars"]["by_family"].items():
        lines += [f"| {f} | {a} | {s['n']} | {f3(s['mean'])} | {f3(s['min'])} | {f3(s['max'])} |" for a, s in by_arm.items()]
    if d["calls"]:
        c = d["calls"]
        lines += ["", "### prompt token 與秒數", "", "| 族 | 臂 | 呼叫 | prompt 平均 | prompt 最大 | eval 平均 | 秒／次 | 秒中位數 |",
                  "|---|---|---|---|---|---|---|---|"]
        for f, by_arm in c["by_family"].items():
            lines += [f"| {f} | {a} | {s['prompt_tokens']['n']} | {f3(s['prompt_tokens']['mean'])} | "
                      f"{f3(s['prompt_tokens']['max'])} | {f3(s['eval_tokens']['mean'])} | {f3(s['seconds']['mean'])} | "
                      f"{f3(s['seconds']['median'])} |" for a, s in by_arm.items()]
        lines += ["", f"- 總秒數 {f3(c['seconds_total'])}；每次 {f3(c['seconds_per_call'])}"]
    return lines + [""]


def render_md(rep: dict) -> str:
    c = rep["calls"]
    lines = [f"# 有序鏈算術 stage-0 報告（{rep['label']}{'，dry run' if rep['dry_run'] else ''}）", "",
             f"- 題數 {rep['n_items']}；應有呼叫 {c['expected']}、已計分 {c['scored']}；缺漏 {len(c['missing_calls'])}", ""]
    lines += _verdict_lines(rep) + _b0_lines(rep) + _power_lines(rep) + _desc_lines(rep)
    lines += ["- 措辭依 prereg §0：結果是開發集的 go/no-go；過關只表示可以請 Kay 授權確認集。",
              f"- 程式 sha256：{'、'.join(f'{k} {v[:12]}' for k, v in rep['code_sha256'].items())}", ""]
    return "\n".join(lines)


def write_text(path: Path | str, text: str) -> Path:
    """x_common.write_json's guard and atomic replace, for report.md."""
    p = X.writable(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return p


def write_report(rep: dict, out_dir: Path | str = X.OUT_ROOT) -> tuple[Path, Path]:
    """report.json (x_common.write_json) and report.md under out_dir (never inside the repository)."""
    json.dumps(rep, ensure_ascii=False)
    out_dir = Path(out_dir)
    return X.write_json(out_dir / "report.json", rep), write_text(out_dir / "report.md", render_md(rep))
