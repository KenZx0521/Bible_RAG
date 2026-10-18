"""Run guards of the confirmation set (confirm_A.md §0, §5; stage-0 appendix A.6), shared by run_c and analyze_c.

Every function returns a list of problems (empty = pass); run_c refuses to run on any, analyze_c
marks the run 作廢. Frozen inputs: questions_frozen.json (F2), contexts.json and items.json (F3)
against store A_confirm/inputs_manifest.json {"frozen": {name: sha256}}; the stage-0 layers,
cards_common.py, the four prompts and the A0 code through c_common.frozen_mismatches(). K0: store
A_confirm/k0_status.json needs K0_1, K0_2, K0_3 pass=true (K0_3 at num_ctx 131072) and a K0_1b
record taken from Kay's ho/kay/k0_1b.json (same sha; K0_1b pass=false is a pre-registered stop, see
k0_1b_stop, not an infra problem). Code: confirm/*.py against inputs_manifest.json code_confirm.
"""
from __future__ import annotations

from pathlib import Path

from c_common import (CONTEXTS, HERE, ITEMS, K0_STATUS, KAY_K0_1B, KAY_LAYER_ROWS, KAY_LAYER_STOP_WRONG, MANIFEST,
                      NUM_CTX, OPTIONS, PROMPT_SHA, QUESTIONS_FROZEN, WORDING, cc, frozen_mismatches, read_json,
                      sha256_file, sha256_text)

FROZEN_FILES = (QUESTIONS_FROZEN, CONTEXTS, ITEMS)
K0_PASS = ("K0_1", "K0_2", "K0_3")


def manifest_frozen(manifest: Path = MANIFEST) -> dict:
    return (read_json(manifest).get("frozen") or {}) if Path(manifest).is_file() else {}


def current_frozen(files=FROZEN_FILES) -> dict:
    return {Path(p).name: sha256_file(p) for p in files if Path(p).is_file()}


def frozen_problems(manifest: Path = MANIFEST, files=FROZEN_FILES, stage0: bool = True) -> list[str]:
    """Frozen files that are missing, unrecorded or changed; items.json must name the frozen inputs."""
    bad = [f"stage-0 frozen input differs: {x}" for x in (frozen_mismatches() if stage0 else [])]
    want = manifest_frozen(manifest)
    for p in map(Path, files):
        if p.name not in want:
            bad.append(f"{p.name}: no sha in {Path(manifest).name}")
        elif not p.is_file():
            bad.append(f"{p.name}: missing")
        elif sha256_file(p) != want[p.name]:
            bad.append(f"{p.name}: sha differs from {Path(manifest).name}")
    items = next((Path(p) for p in files if Path(p).name == ITEMS.name), None)
    if items and items.is_file():
        got = read_json(items).get("inputs_sha256") or {}
        bad += [f"items.json built from another {n}" for n in (QUESTIONS_FROZEN.name, CONTEXTS.name)
                if n in want and got.get(n) != want[n]]
    return bad


def prompt_problems(seed_jobs=(), arm_jobs=()) -> list[str]:
    """The four prompt sha values must be stage-0's; every job must carry its system prompt verbatim."""
    import seeds_a
    got = {"system_prompt": sha256_text(cc.SYSTEM_PROMPT), "user_template": sha256_text(cc.USER_TEMPLATE),
           "seed_system": sha256_text(seeds_a.SEED_SYSTEM), "seed_user_template": sha256_text(seeds_a.SEED_USER)}
    bad = [f"prompt sha {k} is {v[:12]}…, stage-0 {PROMPT_SHA[k][:12]}…" for k, v in got.items() if v != PROMPT_SHA[k]]
    bad += [f"{j['job_id']}: seed system prompt differs" for j in seed_jobs
            if sha256_text(j["system"]) != PROMPT_SHA["seed_system"]]
    bad += [f"{j['job_id']}: arm system prompt differs" for j in arm_jobs
            if sha256_text(j["system"]) != PROMPT_SHA["system_prompt"]]
    return bad


def k0_problems(k0_path: Path = K0_STATUS, kay_path: Path = KAY_K0_1B) -> list[str]:
    if not Path(k0_path).is_file():
        return [f"{k0_path} missing: record K0 before any Ollama call"]
    k0 = read_json(k0_path)
    bad = [f"{k} not pass" for k in K0_PASS if (k0.get(k) or {}).get("pass") is not True]
    if (k0.get("K0_3") or {}).get("num_ctx") != NUM_CTX:
        bad.append(f"K0_3 num_ctx {(k0.get('K0_3') or {}).get('num_ctx')} is not {NUM_CTX}")
    rec = k0.get("K0_1b") or {}
    if rec.get("pass") not in (True, False):
        bad.append("K0_1b (Kay layer check) not recorded")
    elif not Path(kay_path).is_file() or rec.get("src_sha256") != sha256_file(kay_path):
        bad.append(f"K0_1b is not the record in {Path(kay_path).name} (missing, or changed after it was recorded)")
    return bad


def k0_1b_from_kay(kay_path: Path = KAY_K0_1B) -> dict:
    """K0_1b from Kay's recorded layer verdict (kay_a.py apply), the only source; ValueError if inconsistent."""
    if not Path(kay_path).is_file():
        raise ValueError(f"{kay_path} missing: Kay's page (§7) has not been applied")
    doc = read_json(kay_path)
    n, n_wrong, wrong = doc.get("n"), doc.get("n_wrong"), doc.get("wrong")
    if n != KAY_LAYER_ROWS or not isinstance(wrong, list) or n_wrong != len(wrong) \
            or doc.get("stop") is not (n_wrong >= KAY_LAYER_STOP_WRONG):
        raise ValueError(f"{kay_path}: inconsistent layer record (n {n}, n_wrong {n_wrong}, stop {doc.get('stop')})")
    return {**k0_1b_record(n_wrong, n, src=str(kay_path)), "src_sha256": sha256_file(kay_path)}


def k0_1b_record(wrong: int, n: int = KAY_LAYER_ROWS, src: str | None = None) -> dict:
    ok = wrong < KAY_LAYER_STOP_WRONG
    rec = {"pass": ok, "wrong": wrong, "n": n, "stop_at": KAY_LAYER_STOP_WRONG, "src": src}
    if not ok:
        rec["wording"] = WORDING["stop"].format(rule="K0-1b", value=f"{wrong}/{n}", state="未跑")
    return rec


def k0_1b_stop(k0: dict | None) -> str | None:
    rec = (k0 or {}).get("K0_1b") or {}
    if rec.get("pass") is False:
        return rec.get("wording") or k0_1b_record(rec.get("wrong", KAY_LAYER_STOP_WRONG), rec.get("n", KAY_LAYER_ROWS))["wording"]
    return None


def code_sha(here: Path = HERE) -> dict:
    return {p.name: sha256_file(p) for p in sorted(Path(here).glob("*.py"))}


def code_problems(manifest: Path = MANIFEST, here: Path = HERE) -> list[str]:
    """confirm/*.py files added, removed or changed since inputs_manifest.json code_confirm (prepare)."""
    want = read_json(manifest).get("code_confirm") if Path(manifest).is_file() else None
    if want is None:
        return ["code_confirm missing: run prepare first"]
    got = code_sha(here)
    return sorted(f for f in set(want) | set(got) if want.get(f) != got.get(f))


def options_problems(opts: dict) -> list[str]:
    return [] if opts == OPTIONS else [f"options {opts} are not {OPTIONS}"]
