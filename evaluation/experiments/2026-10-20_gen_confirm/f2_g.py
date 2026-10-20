"""F2 steps 5–7 of the GEN confirmation set (prereg §8.1-10 steps 5–7, §5.5, §5.6 K-a, §4.3): store f2.json once.

Run after step 4 wrote questions_frozen.json and its sha256 entered prereg.md's 「執行紀錄」 (refused before):
  5. the first run of gencard on the frozen questions (arms_g's build; F2 is the first time it sees them):
     a_meas = a card with some derived line equal to the gold (Card.covers), w_meas = a card without one,
     R_trig = the rule fired, R_seed = the rule seeds are the gold pair, and the abstention reasons;
  6. K-a: power_g.gate(pool, a_meas, w_meas, slot_idx = the frozen slots' pool indices), the frozen gate (M1,
     nsim 10,000, seed 20261018, a capped at 0.875, w floored at 0.05); pass iff pow_H1_and_H2 ≥ 0.70; a stop
     carries §5.6's sentence (analyze_g.ka_stop_sentence: a = a_meas, n = the frozen questions);
  7. prompt parity (§4.3): for every G and T-rows job, backend/utils/generator.py's build_messages(question,
     context, aux) equals [system: the job's system prompt, user: the job's user prompt] byte for byte; the
     function is compiled from the repository source alone (its config / utils imports dropped, as the
     evaluation tests load backend modules) once the file's sha256 is backend_pins()'s, and the F1 manifest's
     prod items (f1_g.prod_pins(): backend_pins() and the trigger's trigger_pins()) must equal it before and after
     (§4.5).
The build reads order.json's writing order (arms_g's contract checks the attrition against it).
Refused (nothing written): f2.json exists; questions_frozen.json missing or its sha256 not in the log; the F1
manifest or order.json missing, or the card's files (f1_g.card_paths(): gencard/*.py and gen_names.json, by key)
not the manifest's sha256 (frozen since F1a); prod_pins() not the manifest's, before or after; a parity mismatch
(an infrastructure error of this experiment's prompt building: fixed here and F2 rerun; the rule's outputs are
deterministic, so a rerun measures the same a_meas and w_meas). Only when the main session decides that
cards_common or prod alone could fix it (§8.1-10.7) does ``--void-anchor A`` record the void: A is an anchor line
(f1_g.anchor_problems) added to the log after questions_frozen.json's sha256 line, parity must fail on this very
run (a passing parity refuses), the one void record (void_g, why parity: 「作廢（prompt 對等），不構成任何方向的證據」) is
written and then f2.json with parity failed (both paths checked writable first; a failed write leaves nothing, or a
void line without f2.json, never an f2.json of a failed parity without its void), so run_g's gate refuses every
Ollama call and analyze writes only that sentence. A K-a stop is a result: f2.json is written with it. The document
holds counts, ids and booleans (no question or card text); only counts are printed. Nothing here calls Ollama or any
LLM.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import analyze_g as AG
import arms_g as A
import f1_g as F1
import g_common as GC
import gencard
import void_g as V

OUT = GC.F2_FILE
PREREG = F1.PREREG
GENERATOR = GC.BACKEND_PIN_FILES[0]                  # backend/utils/generator.py
PARITY_ARMS = ("G", "T-rows")
Gate = Callable[[float, float, list[int]], dict]
log_text = F1.log_text


def backend_build_messages(repo: Path = GC.REPO, want_sha: str | None = None) -> Callable:
    """backend/utils/generator.py's build_messages, compiled from the repository source alone."""
    path = Path(repo) / GENERATOR
    if want_sha is not None and GC.sha256_file(path) != want_sha:
        raise SystemExit(f"{GENERATOR}: sha256 is not the pinned one")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0]
                                              in ("config", "utils"))]
    ns: dict = {"__name__": "gen_confirm_backend_generator", "settings": None, "get_llm_client": None}
    exec(compile(tree, GENERATOR, "exec"), ns)
    return ns["build_messages"]


def parity(build: dict, build_messages: Callable) -> dict:
    """§4.3 on every G and T-rows job: the backend's messages equal the job's prompts byte for byte."""
    items = {it["id"]: it for it in build["items"]}
    checked, bad = 0, []
    for j in build["jobs"]:
        if j["arm"] not in PARITY_ARMS:
            continue
        it = items[j["item"]]
        aux = A.blocks(build["cards"][it["id"]])[j["arm"]]
        got = build_messages(it["question"], A.context(it), aux)
        checked += 1
        if got != [{"role": "system", "content": j["system"]}, {"role": "user", "content": j["user"]}]:
            bad.append(j["job_id"])
    return {"n_checked": checked, "n_items": len({j["item"] for j in build["jobs"] if j["arm"] in PARITY_ARMS}),
            "mismatch": bad, "pass": not bad}


def default_gate(a_meas: float, w_meas: float, slot_idx: list[int]) -> dict:
    import power_g as PG
    return PG.gate(PG.load_pool(), a_meas, w_meas, slot_idx=slot_idx)


def measure(src: SimpleNamespace, gate: Gate = default_gate) -> tuple[dict, dict]:
    """Steps 5 and 6 on the frozen questions: (the build, {measures, per_question, K_a})."""
    build = A.build(src.frozen, src.pool, src.L, src.gen, src.item_of, order=src.order)
    m = A.rule_measures(build["meta"])
    index = {s["sid"]: i for i, s in enumerate(src.pool)}
    idx = sorted(index[it["sid"]] for it in build["items"])
    g = gate(m["a_meas"]["float"], m["w_meas"]["float"], idx)
    ka = {"slot_idx": idx, "a_meas": m["a_meas"]["float"], "w_meas": m["w_meas"]["float"], "gate": g, "pass": bool(g["pass"]),
          "sentence": None if g["pass"] else AG.ka_stop_sentence(m["a_meas"]["float"], m["n"], g["pow_H1_and_H2"])}
    per = [{"sid": mm["sid"], **{k: mm["rule"][k] for k in ("fired", "step", "reason", "shape")},
            **{k: mm[k] for k in ("seeds_ok", "carded", "covered", "wrong")}} for mm in build["meta"].values()]
    return build, {"measures": m, "per_question": per, "K_a": ka}


def pins_problems(manifest: dict, pins: dict) -> list[str]:
    files = manifest.get("files") or {}
    return [f"backend pin {k} differs from the F1 manifest" for k in pins if files.get(k) != pins[k]]


def frozen_group() -> dict[str, Path]:
    """{manifest key: file} of the card's files F2 checks: exactly the gencard/*.py and gen_names.json keys of
    f1_g.f1a_paths() (f1_g.card_paths()'s keys; the mech checks mech_g.py and mech_qg.py are not the card's)."""
    card = F1.card_paths()
    return {k: p for k, p in F1.f1a_paths().items() if k in card}


def frozen_file_problems(manifest: dict, group: dict[str, Path] | None = None) -> list[str]:
    """gencard/*.py and gen_names.json against the F1 manifest (frozen since F1a)."""
    now, files = F1.sha_map(frozen_group() if group is None else group), manifest.get("files") or {}
    return [f"{k} differs from the F1 manifest" for k, v in now.items() if v is None or files.get(k) != v]


def load_sources(frozen_path: Path = GC.QUESTIONS_FROZEN) -> SimpleNamespace:
    pool = GC.read_json(GC.POOL)["pool"]
    if GC.sha256_file(GC.POOL) != GC.POOL_SHA256:
        raise SystemExit(f"{GC.POOL}: sha256 is not {GC.POOL_SHA256[:12]} (prereg §2.1)")
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise SystemExit(f"{GC.GEN_LAYER}: sha256 is not {GC.GEN_LAYER_SHA256_PREFIX} (prereg §2)")
    if not GC.ORDER.is_file():
        raise SystemExit(f"{GC.ORDER} missing: the writing order comes before F2 (prereg §2.3)")
    S = GC.stage0()
    return SimpleNamespace(frozen=GC.read_json(frozen_path), pool=pool, gen=S.gen_layer.load(),
                           L=gencard.parse(GC.read_json(GC.GEN_LAYER), GC.read_json(GC.GEN_NAMES)), item_of=A.stage0_item,
                           order=GC.read_json(GC.ORDER)["order"])


def void_seen(prereg: Path, q_sha: str) -> list[str]:
    """sha256 of the log lines up to the one with questions_frozen.json's sha256 (the void's anchor is newer)."""
    lines = F1.log_lines(prereg)
    at = next((i for i, ln in enumerate(lines) if q_sha in ln), len(lines))
    return F1.lines_sha256(lines[:at + 1])


def void_path(out: Path) -> Path:
    """The void record beside f2.json (OUT_ROOT/void.json for the store's f2.json)."""
    return Path(out).with_name(GC.VOID_FILE.name)


def void_anchor_problems(anchor: str, prereg: Path, q_sha: str, out: Path = OUT) -> list[str]:
    """§8.1-10.7's void needs an anchor line added after the log line with questions_frozen.json's sha256, and no
    void recorded yet."""
    return F1.anchor_problems(anchor, prereg, seen=void_seen(prereg, q_sha)) + V.problems(void_path(out))


def run_f2(*, out: Path = OUT, frozen_path: Path = GC.QUESTIONS_FROZEN, manifest_path: Path = GC.F1_MANIFEST,
           prereg: Path = PREREG, src: SimpleNamespace | None = None, gate: Gate = default_gate,
           pins: Callable[[], dict] | None = None, build_messages: Callable | None = None,
           group: dict[str, Path] | None = None, void_anchor: str | None = None) -> dict:
    """F2 steps 5–7; writes ``out`` once (see the module docstring for the refusals and the void); ``pins`` stands
    for f1_g.prod_pins (tests)."""
    pins = pins or F1.prod_pins
    if Path(out).exists():
        raise SystemExit(f"{out} exists: F2 steps 5–7 are recorded once")
    bad = [] if Path(frozen_path).is_file() else [f"{frozen_path} missing (F2 step 4 first)"]
    bad += [] if Path(manifest_path).is_file() else [f"{manifest_path} missing (F1)"]
    if bad:
        raise SystemExit(f"F2 refused: {bad}")
    q_sha, manifest = GC.sha256_file(frozen_path), GC.read_json(manifest_path)
    bad += [] if q_sha in log_text(prereg) else ["questions_frozen.json's sha256 is not in prereg.md's 執行紀錄 (step 4)"]
    bad += frozen_file_problems(manifest, group) + pins_problems(manifest, pins())
    bad += [] if void_anchor is None else void_anchor_problems(void_anchor, prereg, q_sha, out)
    if bad:
        raise SystemExit(f"F2 refused: {bad}")
    build, res = measure(src or load_sources(frozen_path), gate)
    bm = build_messages or backend_build_messages(want_sha=pins()[GENERATOR])
    par, after = parity(build, bm), pins_problems(manifest, pins())
    if after or (not par["pass"] and void_anchor is None):
        raise SystemExit(f"F2 refused, nothing written: parity mismatches {len(par['mismatch'])}, backend pins {after} "
                         "(fix this experiment's prompt building, then rerun; only cards_common or prod could fix it: "
                         "作廢 before any Ollama call, prereg §8.1-10.7, with --void-anchor)")
    if par["pass"] and void_anchor is not None:
        raise SystemExit("F2 refused, nothing written: --void-anchor, but parity passes (no void)")
    doc = {"schema": "gen_confirm.f2.v1", "questions_frozen_sha256": q_sha,
           "f1_manifest_sha256": GC.sha256_file(manifest_path), **res, "parity": par,
           "backend_pins": {"equal_before": True, "equal_after": True}, "prompts_sha256": A.prompts_sha256(build["jobs"]),
           "n_jobs": len(build["jobs"]), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    GC.writable(out)
    if void_anchor is not None:                      # the void first: f2.json of a failed parity never stands alone
        GC.writable(void_path(out))
        V.write("parity", void_anchor, path=void_path(out), prereg=prereg, seen=void_seen(prereg, q_sha),
                detail={"f2_sha256": GC.sha256_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n"),
                        "mismatch": len(par["mismatch"])})
    GC.write_json(out, doc)
    return doc


def counts(doc: dict) -> dict:
    m, ka = doc["measures"], doc["K_a"]
    return {"n": m["n"], "a_meas": m["a_meas"]["frac"], "w_meas": m["w_meas"]["frac"], "R_trig": m["R_trig"]["frac"],
            "R_seed": m["R_seed"]["frac"], "abstentions": m["abstentions"], "K_a_power": ka["gate"]["pow_H1_and_H2"],
            "K_a_pass": ka["pass"], "parity_checked": doc["parity"]["n_checked"], "n_jobs": doc["n_jobs"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GEN 確認集 F2 第 5–7 步（prereg §8.1-10）")
    ap.add_argument("--void-anchor", default=None, metavar="ANCHOR",
                    help="對等不過且只能改 cards_common 或 prod 才修得好：記作廢；值是執行紀錄的錨點")
    a = ap.parse_args(argv)
    doc = run_f2(void_anchor=a.void_anchor)
    void = V.read(void_path(OUT)) if a.void_anchor is not None else None
    print(counts(doc))
    for s in ((void or {}).get("sentence"), None if doc["K_a"]["pass"] else doc["K_a"]["sentence"]):
        if s:
            print(s)
    return 1 if void or not doc["K_a"]["pass"] else 0


if __name__ == "__main__":
    sys.exit(main())
