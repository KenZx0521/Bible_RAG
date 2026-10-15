"""Invariants, subsets, plan and overlap of the book_anchor ablation (prereg §4, §6, §9 3.3).

Host only; pure functions over the driver's records (ba_analyze.py does the file I/O).
A retrieval record ("q" line) carries per arm: results, ids, n_core (the top-k before the
event-registry aux slot), ctx_sha, stats, pool (id, source_strategy, weight, …), pins and
ba_calls; nopin / off are None when M1 skipped them.

  C        ctrl pool holds a source_strategy == "book_anchor" candidate
  P_s/P_m  ctrl pin recorder: book_gate False / True with pinned ids
  D_x      ctx_sha(x) != ctx_sha(ctrl);  U = D_nopin ∪ D_off
  I0 meta lines and exp_meta (build, encoder, settings, threads, 18 backend + /exp sha256,
     image id, Ollama digests); I1 ctrl = eval3c full on same-route questions (top-5 + aux
     ids; max|Δscore| reported); I2 non-C questions that ran three arms are identical, no C
     question was skipped; I3 D_nopin = P_s; I4 one route per question, no strategy_errors,
     the applied settings; I5 (report) off pool = ctrl pool minus the anchors.
eval3c_ref.json (frozen, make-ref) is built from eval3c full's raw responses and the
build's routing lexicon by build_eval3c_ref and cross-checked against the design-stage
ba39.json.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import _ba_io as bio

__all__ = ["CheckError", "BUILD_ID", "IMAGE_PREFIX", "GEN_MODEL", "JUDGE_MODEL",
           "REFUSAL_SHA_PREFIX", "BACKEND_FILES", "EXPECT_SETTINGS", "EXPECT_CALL", "ARMS",
           "SEED", "REPS", "STRICT_REPS", "FROZEN", "SKIPPED", "load_retrieval", "core_ids",
           "aux_ids", "in_c", "subsets", "check_i0", "check_i1", "check_i2", "check_i3",
           "check_i4", "check_i5", "mechanisms", "gen_plan", "judge_ids", "judge_order",
           "freeze_record", "verify_freeze", "overlap", "smoke_problems", "smoke_plan",
           "pin_count", "build_eval3c_ref"]

BUILD_ID = "b20261008_e05d3e55"
IMAGE_PREFIX = "sha256:c79266296cb0"
GEN_MODEL = "gemma4:e4b-it-q8_0"
JUDGE_MODEL = "gemma4:26b-a4b-it-q8_0"
REFUSAL_SHA_PREFIX = "ea3060c6"
TORCH_THREADS = 24
BACKEND_FILES = tuple(f"utils/retrieval/{n}.py" for n in (
    "routes", "router", "pins", "dense", "candidates", "event_registry")) + tuple(
    f"utils/{n}.py" for n in ("signal_detector", "intent_classifier", "generator", "reranker",
                              "embedder")) + (
    "routers/query.py", "models/request.py", "models/response.py", "config.py", "main.py",
    "utils/llm/ollama_client.py", "serving/startup.py")
EXPECT_SETTINGS = {"rag_env": "prod", "rag_build_id": BUILD_ID, "rag_rank_fusion_enabled": True,
                   "rag_rank_fusion_alpha": 0.3, "rag_use_graph": True,
                   "rag_graph_strategies": ["event_registry"], "ollama_model": GEN_MODEL,
                   "llm_temperature": 0.1, "llm_max_tokens": 10000}
EXPECT_CALL = {"top_k": 5, "use_graph": True, "graph_strategies": None, "fusion_alpha": None}
ARMS = ("ctrl", "nopin", "off")
BA = "book_anchor"
SKIPPED = "book_anchor_not_invoked"
SEED = 20261015
REPS, STRICT_REPS = 6, 3
FROZEN = ("subsets.json", "gen_plan.json", "judge_ids_ctrl.json", "judge_ids_nopin.json",
          "judge_ids_off.json", "judge_order.json")


class CheckError(ValueError):
    """Records or references that cannot be checked as they are."""


# ---------------------------------------------------------------- records

def load_retrieval(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """(meta lines, {qid: q record}) of retrieval.jsonl; a duplicate or unknown kind raises."""
    metas, rows = [], {}
    for rec in bio.read_jsonl(path):
        if rec["kind"] == "meta":
            metas.append(rec)
        elif rec["kind"] == "q":
            if rec["qid"] in rows:
                raise CheckError(f"{path}: {rec['qid']} recorded twice")
            rows[rec["qid"]] = rec
        elif rec["kind"] != "end":
            raise CheckError(f"{path}: unexpected kind {rec['kind']!r}")
    return metas, rows


def core_ids(rec: Mapping[str, Any]) -> list[str]:
    return list(rec["ids"][:rec["n_core"]])


def aux_ids(rec: Mapping[str, Any]) -> list[str]:
    return list(rec["ids"][rec["n_core"]:])


def _ran(row: Mapping[str, Any]) -> bool:
    return row["arms"].get("nopin") is not None and row["arms"].get("off") is not None


def in_c(row: Mapping[str, Any]) -> bool:
    return any(p.get("source_strategy") == BA for p in row["arms"]["ctrl"]["pool"])


def _pinned(row: Mapping[str, Any], gate: bool) -> bool:
    return any(p["pinned"] and bool(p["book_gate"]) == gate for p in row["arms"]["ctrl"]["pins"])


def _differs(row: Mapping[str, Any], arm: str) -> bool:
    return _ran(row) and row["arms"][arm]["ctx_sha"] != row["arms"]["ctrl"]["ctx_sha"]


def subsets(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """§4: C, P_s, P_m, D_nopin, D_off, U (sorted qids)."""
    q = sorted(rows)
    d_nopin = [x for x in q if _differs(rows[x], "nopin")]
    d_off = [x for x in q if _differs(rows[x], "off")]
    return {"C": [x for x in q if in_c(rows[x])],
            "P_s": [x for x in q if _pinned(rows[x], False)],
            "P_m": [x for x in q if _pinned(rows[x], True)],
            "D_nopin": d_nopin, "D_off": d_off, "U": sorted(set(d_nopin) | set(d_off))}


# ---------------------------------------------------------------- I0

def _neq(problems: list[str], where: str, got: Any, want: Any) -> None:
    if got != want:
        problems.append(f"{where}: {got!r} != {want!r}")


def _meta_problems(n: int, m: Mapping[str, Any], backend: Mapping[str, str],
                   exp: Mapping[str, str], encoder: Mapping[str, Any]) -> list[str]:
    where, out = f"meta[{n}] {m.get('mode')}", []
    settings = m.get("settings") or {}
    for key, want in EXPECT_SETTINGS.items():
        _neq(out, f"{where} settings.{key}", settings.get(key), want)
    _neq(out, f"{where} call", m.get("call"), EXPECT_CALL)
    _neq(out, f"{where} build_id", m.get("build_id"), BUILD_ID)
    _neq(out, f"{where} llm_health", m.get("llm_health"), True)
    _neq(out, f"{where} env.RAG_ENV", (m.get("env") or {}).get("RAG_ENV"), "prod")
    _neq(out, f"{where} backend_sha256", m.get("backend_sha256"), dict(backend))
    _neq(out, f"{where} exp_sha256", m.get("exp_sha256"), dict(exp))
    if m.get("mode") == "retrieve":
        _neq(out, f"{where} encoder_fingerprint", m.get("encoder_fingerprint"), dict(encoder))
        _neq(out, f"{where} torch_threads", m.get("torch_threads"), TORCH_THREADS)
        _neq(out, f"{where} handshake.ok", (m.get("handshake") or {}).get("ok"), True)
    return out


def _exp_meta_problems(exp_meta: Mapping[str, Any] | None) -> list[str]:
    if not exp_meta:
        return ["exp_meta.json missing"]
    out = []
    if not str(exp_meta.get("image_id", "")).startswith(IMAGE_PREFIX):
        out.append(f"exp_meta image_id {exp_meta.get('image_id')!r} is not {IMAGE_PREFIX}…")
    digests = exp_meta.get("ollama_digests") or {}
    out += [f"exp_meta: no Ollama digest of {m}" for m in (GEN_MODEL, JUDGE_MODEL)
            if not digests.get(m)]
    if not str(exp_meta.get("refusal_v2_sha256", "")).startswith(REFUSAL_SHA_PREFIX):
        out.append("exp_meta refusal_v2_sha256 is not the frozen ea3060c6…")
    return out


def check_i0(metas: Sequence[Mapping[str, Any]], *, backend_expected: Mapping[str, str],
             exp_expected: Mapping[str, str], encoder_expected: Mapping[str, Any],
             exp_meta: Mapping[str, Any] | None, mode: str = "retrieve") -> list[str]:
    """§6 I0 problems (empty: pass) of retrieval.jsonl's meta lines (mode "retrieve") or
    gen.jsonl's ("generate"); there must be at least one, all of that mode."""
    problems = [] if any(m.get("mode") == mode for m in metas) else [f"no {mode} meta line"]
    problems += [f"meta[{n}] mode {m.get('mode')!r} is not {mode!r}"
                 for n, m in enumerate(metas) if m.get("mode") != mode]
    for n, m in enumerate(metas):
        problems += _meta_problems(n, m, backend_expected, exp_expected, encoder_expected)
    return problems + _exp_meta_problems(exp_meta)


# ---------------------------------------------------------------- I1–I5

def _score(r: Mapping[str, Any]) -> float | None:
    fused = r.get("fused_score")
    return fused if fused is not None else r.get("rerank_score")


def check_i1(rows: Mapping[str, Mapping[str, Any]],
             eval3c: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """ctrl's top-k + aux ids = eval3c full's on every same-route question."""
    mismatch, route_diff, missing, drift, compared = [], [], [], 0.0, 0
    for qid in sorted(rows):
        ctrl, ref = rows[qid]["arms"]["ctrl"], eval3c.get(qid)
        if ref is None:
            missing.append(qid)
            continue
        route = ctrl["stats"].get("route_used")
        if route != ref.get("route_used"):
            route_diff.append({"qid": qid, "eval3c": ref.get("route_used"), "now": route})
            continue
        compared += 1
        ref_ids = [s["id"] for s in ref["sources"]]
        if ctrl["ids"] != ref_ids:
            mismatch.append({"qid": qid, "ctrl": ctrl["ids"], "eval3c": ref_ids})
        ours = {r["id"]: _score(r) for r in ctrl["results"]}
        for s in ref["sources"]:
            if s.get("score") is not None and ours.get(s["id"]) is not None:
                drift = max(drift, abs(ours[s["id"]] - s["score"]))
    return {"ok": not mismatch and not missing, "compared": compared, "mismatch": mismatch,
            "route_diff": route_diff, "missing": missing, "max_abs_dscore": drift}


def check_i2(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Non-C questions that ran every arm: nopin / off ids and ctx_sha = ctrl's (M1)."""
    checked, mismatch, skipped_in_c, inconsistent = [], [], [], []
    for qid in sorted(rows):
        row = rows[qid]
        if not _ran(row):
            if in_c(row):
                skipped_in_c.append(qid)
            if (row.get("arms_skipped") != SKIPPED or row["arms"]["ctrl"]["ba_calls"]
                    or row.get("forced")):
                inconsistent.append(qid)
            continue
        if in_c(row):
            continue
        checked.append(qid)
        ctrl = row["arms"]["ctrl"]
        for arm in ("nopin", "off"):
            rec = row["arms"][arm]
            what = "ids" if rec["ids"] != ctrl["ids"] else (
                "ctx_sha" if rec["ctx_sha"] != ctrl["ctx_sha"] else None)
            if what:
                mismatch.append({"qid": qid, "arm": arm, "what": what})
    return {"ok": not (mismatch or skipped_in_c or inconsistent), "checked": checked,
            "mismatch": mismatch, "skipped_in_c": skipped_in_c,
            "skip_inconsistent": inconsistent}


def check_i3(subs: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    d_nopin, p_s = set(subs["D_nopin"]), set(subs["P_s"])
    d_off = set(subs["D_off"])
    return {"ok": d_nopin == p_s, "d_nopin_minus_p_s": sorted(d_nopin - p_s),
            "p_s_minus_d_nopin": sorted(p_s - d_nopin),
            "d_nopin_not_in_d_off": sorted(d_nopin - d_off),
            "p_m_not_in_d_off": sorted(set(subs["P_m"]) - d_off)}


def _applied_ok(stats: Mapping[str, Any]) -> bool:
    route = stats.get("route_used")
    alpha_ok = stats.get("fusion_alpha") == (None if route == "R1" else 0.3)
    return (alpha_ok and stats.get("use_graph") is True
            and stats.get("graph_strategies") == ["event_registry"])


def check_i4(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """One route per question, no strategy_errors, the applied settings; intent listed."""
    route_mismatch, errors, applied = [], {}, []
    for qid in sorted(rows):
        arms = {a: r for a, r in rows[qid]["arms"].items() if r is not None}
        if len({r["stats"].get("route_used") for r in arms.values()}) != 1:
            route_mismatch.append(qid)
        bad = [a for a in ARMS if a in arms and arms[a]["stats"].get("strategy_errors")]
        if bad:
            errors[qid] = bad
        if not all(_applied_ok(r["stats"]) for r in arms.values()):
            applied.append(qid)
    return {"ok": not (route_mismatch or errors or applied), "route_mismatch": route_mismatch,
            "strategy_errors": errors, "applied": applied,
            "intent_failed": sorted(q for q, r in rows.items() if r.get("intent_ok") is False),
            "intent_retried": sorted(q for q, r in rows.items() if r.get("intent_attempts", 1) > 1),
            "arms_retried": sorted(q for q, r in rows.items() if r.get("arm_attempts", 1) > 1)}


def check_i5(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """(report) For C: off pool {id: weight} = ctrl pool minus book_anchor candidates."""
    exceptions = []
    for qid in sorted(rows):
        row = rows[qid]
        if not in_c(row) or not _ran(row):
            continue
        want = {p["id"]: p.get("weight") for p in row["arms"]["ctrl"]["pool"]
                if p.get("source_strategy") != BA}
        got = {p["id"]: p.get("weight") for p in row["arms"]["off"]["pool"]}
        if want != got:
            exceptions.append({
                "qid": qid, "extra_in_off": sorted(set(got) - set(want)),
                "missing_in_off": sorted(set(want) - set(got)),
                "weight_diff": sorted(i for i in set(got) & set(want) if got[i] != want[i]),
                "tags": mechanisms(row)["tags"]})
    return {"exceptions": exceptions}


def mechanisms(row: Mapping[str, Any]) -> dict[str, Any]:
    """§4 D_off tags: (i) a ctrl core anchor left the core; (ii) common non-anchor core
    passages changed order; (iii) the off pool has an id ctrl's lacks; (iv) aux slot changed."""
    ctrl, off = row["arms"]["ctrl"], row["arms"]["off"]
    strategy = {r["id"]: r.get("source_strategy") for r in ctrl["results"]}
    cc, oc = core_ids(ctrl), core_ids(off)
    tags = []
    if any(strategy.get(i) == BA and i not in oc for i in cc):
        tags.append("i")
    common = [i for i in cc if strategy.get(i) != BA and i in oc]
    if common != [i for i in oc if i in set(common)]:
        tags.append("ii")
    if {p["id"] for p in off["pool"]} - {p["id"] for p in ctrl["pool"]}:
        tags.append("iii")
    if aux_ids(ctrl) != aux_ids(off):
        tags.append("iv")
    rr = {p["id"]: p.get("rerank_score") for p in ctrl["pool"]}
    drifts = [abs(p["rerank_score"] - rr[p["id"]]) for p in off["pool"]
              if p.get("rerank_score") is not None and rr.get(p["id"]) is not None]
    return {"tags": tags, "max_abs_drr": max(drifts) if drifts else None}


# ---------------------------------------------------------------- plan, judge ids, order

def gen_plan(rows: Mapping[str, Mapping[str, Any]], subs: Mapping[str, Sequence[str]],
             reps: int = REPS, seed: int = SEED) -> dict[str, Any]:
    """§2: (q, rep) blocks shuffled, arms shuffled within a block; ctrl on U, nopin on
    D_nopin, off on D_off (an arm whose context equals ctrl's is not generated)."""
    rng = random.Random(seed)
    blocks = [(q, rep) for q in sorted(subs["U"]) for rep in range(1, reps + 1)]
    rng.shuffle(blocks)
    members = {"nopin": set(subs["D_nopin"]), "off": set(subs["D_off"])}
    items = []
    for qid, rep in blocks:
        arms = [a for a in ARMS if a == "ctrl" or qid in members[a]]
        rng.shuffle(arms)
        for a in arms:
            items.append({"order": len(items), "qid": qid, "arm": a, "rep": rep,
                          "ctx_sha": rows[qid]["arms"][a]["ctx_sha"]})
    counts = Counter(i["arm"] for i in items)
    return {"meta": {"seed": seed, "reps": reps, "n_items": len(items),
                     "counts": {a: counts.get(a, 0) for a in ARMS}}, "items": items}


def judge_ids(subs: Mapping[str, Sequence[str]]) -> dict[str, list[str]]:
    return {"ctrl": sorted(subs["U"]), "nopin": sorted(subs["D_nopin"]),
            "off": sorted(subs["D_off"])}


def judge_order(ids: Mapping[str, Sequence[str]], seed: int = SEED, reps: int = REPS,
                strict_reps: int = STRICT_REPS) -> dict[str, list[str]]:
    """§9 3.7/3.8: rep by rep (r1's arms, then r2's …), arms shuffled per rep by seed."""
    rng = random.Random(seed)
    coverage = []
    for rep in range(1, reps + 1):
        arms = [a for a in ARMS if ids.get(a)]
        rng.shuffle(arms)
        coverage += [f"{a}_r{rep}" for a in arms]
    strict = [d for d in coverage if int(d.rsplit("_r", 1)[1]) <= strict_reps]
    return {"seed": seed, "coverage": coverage, "strict": strict}


def freeze_record(checks_dir: Path) -> dict[str, str]:
    return {name: bio.sha256_file(Path(checks_dir) / name) for name in FROZEN}


def verify_freeze(checks_dir: Path, record: Mapping[str, str]) -> list[str]:
    """Names in FROZEN whose file is missing or differs from the record."""
    bad = []
    for name in FROZEN:
        path = Path(checks_dir) / name
        if not path.exists() or bio.sha256_file(path) != record.get(name):
            bad.append(name)
    return bad


# ---------------------------------------------------------------- overlap with eval3c (§4)

def _reason(qid: str, rows: Mapping[str, Mapping[str, Any]], ref: Mapping[str, Any],
            missing_side: str) -> str:
    if qid not in rows:
        return "not retrieved in this run"
    now, before = rows[qid]["arms"]["ctrl"]["stats"].get("route_used"), ref["routes"].get(qid)
    if now != before:
        return f"route {before}→{now}"
    if missing_side != "D":
        return missing_side
    if not in_c(rows[qid]):
        return "not in C"
    return "context unchanged" if _ran(rows[qid]) else str(rows[qid].get("arms_skipped"))


def overlap(rows: Mapping[str, Mapping[str, Any]], subs: Mapping[str, Sequence[str]],
            ref: Mapping[str, Any]) -> dict[str, Any]:
    d_nopin, d_off, c = set(subs["D_nopin"]), set(subs["D_off"]), set(subs["C"])
    ba39, single, c43 = set(ref["ba39"]), set(ref["pinned_single19"]), set(ref["c43"])

    def listed(ids: Iterable[str], side: str) -> list[dict[str, str]]:
        return [{"qid": q, "reason": _reason(q, rows, ref, side)} for q in sorted(ids)]

    route_diff = [{"qid": q, "eval3c": ref["routes"].get(q),
                   "now": rows[q]["arms"]["ctrl"]["stats"].get("route_used"),
                   "in_c": q in c, "in_c43": q in c43}
                  for q in sorted(rows)
                  if rows[q]["arms"]["ctrl"]["stats"].get("route_used") != ref["routes"].get(q)]
    return {"n": {"D_nopin&ba39": len(d_nopin & ba39), "D_off&ba39": len(d_off & ba39),
                  "D_nopin&pinned_single19": len(d_nopin & single)},
            "only_d_nopin": listed(d_nopin - single, "not in eval3c's single-book pinned 19"),
            "only_pinned_single19": listed(single - d_nopin, "D"),
            "only_d_off": listed(d_off - ba39, "not in eval3c's 39"),
            "only_ba39": listed(ba39 - d_off, "D"),
            "c_union_c43": sorted(c | c43), "c_only": sorted(c - c43),
            "c43_only": sorted(c43 - c), "route_diff": route_diff}


# ---------------------------------------------------------------- smoke expectations (§6)

GBQ = "GENERAL_BIBLE_QUESTION_"


def _plain(ids: Sequence[str]) -> list[str]:
    return [i[3:] if i.startswith("ps:") else i for i in ids]


def _core(row: Mapping[str, Any], arm: str) -> list[str]:
    return _plain(core_ids(row["arms"][arm]))


def _same(row: Mapping[str, Any], arm: str) -> bool:
    rec, ctrl = row["arms"][arm], row["arms"]["ctrl"]
    return rec["ids"] == ctrl["ids"] and rec["ctx_sha"] == ctrl["ctx_sha"]


def _smoke_024(r):
    return [f"{GBQ}024 {a}: {_core(r, a)}" for a, want in (
        ("nopin", ["mrk.1.1", "mat.3.1", "luk.3.1", "jhn.1.19", "isa.40.1"]),
        ("off", ["mrk.1.1", "mat.3.1", "luk.3.1", "jhn.1.19", "mat.11.2"])) if _core(r, a) != want]


def _smoke_096(r):
    want = ["exo.40.34", "2ch.5.11", "ezk.43.1", "exo.16.1", "isa.4.2"]
    return ([] if _same(r, "nopin") else [f"{GBQ}096 nopin != ctrl"]) + (
        [] if _core(r, "off") == want else [f"{GBQ}096 off: {_core(r, 'off')}"])


def _smoke_001(r):
    ok = ("isa.30.19" in _core(r, "ctrl") and "isa.30.19" not in _core(r, "off")
          and _core(r, "off")[:4] == _core(r, "ctrl")[:4])
    return ([] if _same(r, "nopin") else [f"{GBQ}001 nopin != ctrl"]) + (
        [] if ok else [f"{GBQ}001 off: {_core(r, 'off')}"])


def _smoke_050(r):
    want = ["mat.22.23", "mrk.12.18", "luk.20.27", "jhn.12.12", "mat.16.21"]
    return [f"{GBQ}050 {a}: {_core(r, a)}" for a in ("nopin", "off") if _core(r, a) != want]


def _smoke_013(r):
    head = ["1co.15.12", "1co.15.35", "1co.15.1"]
    out = [f"{GBQ}013 {a} head: {_core(r, a)[:3]}" for a in ARMS if _core(r, a)[:3] != head]
    off = r["arms"]["off"]
    fifth = off["results"][4].get("source_strategy") if len(off["results"]) > 4 else None
    ok = ("gen.15.1" in _core(r, "ctrl") and "gen.15.1" not in _core(r, "off")
          and _core(r, "off")[3:4] == ["2co.6.14"] and fifth not in (None, BA))
    return out + ([] if _same(r, "nopin") else [f"{GBQ}013 nopin != ctrl"]) + (
        [] if ok else [f"{GBQ}013 off: {_core(r, 'off')} (5th {fifth})"])


SMOKE: dict[str, Callable] = {f"{GBQ}024": _smoke_024, f"{GBQ}096": _smoke_096,
                              f"{GBQ}001": _smoke_001, f"{GBQ}050": _smoke_050,
                              f"{GBQ}013": _smoke_013}


def smoke_problems(rows: Mapping[str, Mapping[str, Any]], first_r1: str) -> list[str]:
    """§6 smoke expectations (ctrl = eval3c full is I1, checked apart)."""
    out = []
    for qid, check in [*SMOKE.items(), (first_r1, None)]:
        row = rows.get(qid)
        if row is None or not _ran(row):
            out.append(f"{qid}: missing or arms skipped")
            continue
        if check is not None:
            out += check(row)
        elif not (_same(row, "nopin") and _same(row, "off")):
            out.append(f"{qid} (first R1): the three arms differ")
    return out


def smoke_plan(rows: Mapping[str, Mapping[str, Any]], qid: str = f"{GBQ}024") -> dict[str, Any]:
    """§9 smoke 3: GBQ_024's three arms, one generation each."""
    items = [{"order": n, "qid": qid, "arm": a, "rep": 1,
              "ctx_sha": rows[qid]["arms"][a]["ctx_sha"]} for n, a in enumerate(ARMS)]
    return {"meta": {"smoke": True, "n_items": len(items)}, "items": items}


# ---------------------------------------------------------------- eval3c reference

def pin_count(sources: Sequence[Mapping[str, Any]]) -> int:
    """Pins read from eval3c scores (pins.py: base + 0.004·(2−i)): two anchors 0.004 apart
    above the next, or one anchor 0.008 above it; aux passages left out."""
    core = [s for s in sources if s.get("strategy") != "event_registry"]
    sc = [s.get("score") for s in core]
    if (len(core) >= 3 and core[0]["strategy"] == core[1]["strategy"] == BA
            and None not in sc[:3] and abs(sc[0] - sc[1] - 0.004) < 1e-6
            and abs(sc[1] - sc[2] - 0.004) < 1e-6):
        return 2
    if (len(core) >= 2 and core[0]["strategy"] == BA and None not in sc[:2]
            and abs(sc[0] - sc[1] - 0.008) < 1e-6):
        return 1
    return 0


def build_eval3c_ref(raw: Sequence[Mapping[str, Any]], match_books: Callable[[str], list],
                     ba39: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """43 / 39 / 20 / single-book 19 of eval3c full, every route and the first R1 question;
    with the design-stage ba39.json the 39, the pins and single/multi must agree."""
    items = sorted(raw, key=lambda x: x["question_id"])
    c43 = [x["question_id"] for x in items if BA in (x.get("strategies_used") or [])]
    b39 = [x["question_id"] for x in items
           if any(s.get("strategy") == BA for s in x.get("sources") or [])]
    pins = {x["question_id"]: n for x in items if (n := pin_count(x.get("sources") or []))}
    books = {x["question_id"]: list(match_books(x["question"])) for x in items}
    single = [q for q in sorted(pins) if len(books[q]) <= 1]
    ref = {"c43": c43, "ba39": b39, "pinned20": sorted(pins), "pinned_single19": single,
           "pinned_multi": sorted(set(pins) - set(single)), "n_pinned": pins,
           "detected_books": {q: books[q] for q in c43},
           "routes": {x["question_id"]: x.get("route_used") for x in items},
           "first_r1": next((x["question_id"] for x in items if x.get("route_used") == "R1"),
                            None)}
    if ba39 is not None:
        theirs = (sorted(r["qid"] for r in ba39),
                  sorted(r["qid"] for r in ba39 if r["n_pinned"]),
                  sorted(r["qid"] for r in ba39 if r["n_pinned"] and not r["multi_book"]))
        if theirs != (b39, ref["pinned20"], single):
            raise CheckError("eval3c raw and ba39.json disagree on the 39 / pins / single-book")
        ref["ba39_crosscheck"] = True
    return ref


def dumps(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True,
                      default=bio.json_default) + "\n"
