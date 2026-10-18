"""Base contexts of the confirmation set (confirm_A.md §4) → store A_confirm/contexts.json (F3 input).

One POST {BACKEND_QUERY} per frozen question, sequential, body c_common.request_body (prod as-is:
top_k 5, include_sources, include_context, retrieval_only; event_registry aux lane at prod default).
Timeout 180 s; an HTTP error, a timeout or an infrastructure failure (src.validity.infra_failed) is
retried at most 2 times. Then every source must carry its context block, every build_id must be
b20261008_e05d3e55, and items_c.source_c(s) re-rendered by cards_common.context_block must give the
same block (sha256, position by position). Any question that still fails stops the run: nothing is
written to contexts.json (no partial freeze), only collect_failed.json with the reasons.
/api/ps is read before and after. Refuses unless questions_frozen.json matches the F2 sha that
ho_a/freeze_a.py wrote into inputs_manifest.json and k_u2.json (stop false, same sha), and refuses to
overwrite an existing contexts.json.

Only main() (run_c.py collect) talks to the backend and Ollama; tests inject `post` and `ps`.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import items_c
from c_common import (BACKEND_QUERY, COLLECT_RETRIES, COLLECT_TIMEOUT_S, CONTEXTS, K_U2, MANIFEST, OUT,
                      PROD_BUILD_ID, QUESTIONS_FROZEN, TOP_K, ac, cc, read_json, request_body, sha256_file)

sys.path.insert(0, str(ac.EVAL_DIR))
from src.validity import AUXILIARY_STRATEGIES, infra_failed  # noqa: E402

FAILED = OUT / "collect_failed.json"
JOIN = "\n\n"  # quick_retrieval_eval.context_digest: blocks joined as the generator joins them


class Retryable(Exception):
    """HTTP error, timeout or infrastructure failure: tried again (≤ COLLECT_RETRIES)."""


class Rejected(Exception):
    """A deterministic check failed (no context block, build_id, re-render): no retry."""


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def post_json(url: str, body: dict, timeout: float) -> dict:
    """POST JSON; HTTP ≥ 400, a refused connection or a timeout raise Retryable."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise Retryable(f"HTTP {e.code} {e.read()[:300]!r}") from e
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, json.JSONDecodeError) as e:
        raise Retryable(repr(e)) from e


def context_digest(sources: list[dict]) -> str:
    """sha256 of every context block in order, joined by a blank line (quick_retrieval_eval)."""
    return sha(JOIN.join(s["context"] for s in sources))


def check_response(data: dict) -> dict:
    """The §4 checks on one /api/v1/query response; returns the record fields to freeze."""
    stats, srcs = data.get("retrieval_stats") or {}, data.get("sources") or []
    errors = stats.get("strategy_errors") or {}
    if infra_failed([s.get("strategy") for s in srcs], errors):
        raise Retryable(f"infra_failed: strategy_errors {sorted(errors)}")
    no_ctx = [i for i, s in enumerate(srcs, 1) if not isinstance(s.get("context"), str)]
    if no_ctx:
        raise Rejected(f"no context block at source positions {no_ctx}")
    bad_build = sorted({str(s.get("build_id")) for s in srcs if s.get("build_id") != PROD_BUILD_ID})
    if bad_build:
        raise Rejected(f"build_id {bad_build} is not {PROD_BUILD_ID}")
    rerender = [i for i, s in enumerate(srcs, 1)
                if sha(cc.context_block(i, items_c.source_c(s))) != sha(s["context"])]
    if rerender:
        raise Rejected(f"re-rendered block differs at source positions {rerender}")
    if cc.build_context([items_c.source_c(s) for s in srcs]) != JOIN.join(s["context"] for s in srcs):
        raise Rejected("re-rendered context differs from the returned blocks")
    intent = data.get("intent") or {}
    return {"sources": srcs, "intent": intent, "route_used": stats.get("route_used"),
            "strategies_used": stats.get("strategies_used"), "strategy_errors": errors,
            "event_registry_events": stats.get("event_registry_events"),
            "n_sources": len(srcs), "n_aux": sum(s.get("strategy") in AUXILIARY_STRATEGIES for s in srcs),
            "context_sha": context_digest(srcs) if srcs else sha(""),
            "block_sha": [sha(s["context"]) for s in srcs]}


def query_checked(question: str, post=post_json, retries: int = COLLECT_RETRIES, sleep=time.sleep) -> dict:
    """One question: ≤ 1 + retries attempts on Retryable; Rejected stops at once. Raises with the log."""
    body, log = request_body(question), []
    for attempt in range(1, retries + 2):
        t0 = time.time()
        try:
            rec = check_response(post(BACKEND_QUERY, body, COLLECT_TIMEOUT_S))
        except Retryable as e:
            log.append({"attempt": attempt, "retryable": True, "error": str(e)})
            if attempt <= retries:
                sleep(min(5 * attempt, 15))
            continue
        except Rejected as e:
            log.append({"attempt": attempt, "retryable": False, "error": str(e)})
            raise Rejected(json.dumps(log, ensure_ascii=False)) from e
        return {"request": body, **rec, "attempts": attempt, "attempt_log": log,
                "elapsed_s": round(time.time() - t0, 2), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    raise Retryable(json.dumps(log, ensure_ascii=False))


def safe_ps(ps) -> dict:
    try:
        return {"ok": True, "ps": ps()}
    except Exception as e:  # noqa: BLE001 - diagnostics only, recorded
        return {"ok": False, "error": repr(e)}


def write_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def f2_sha(manifest: Path = MANIFEST, k_u2: Path = K_U2) -> str:
    """questions_frozen.json sha recorded at F2 by freeze_a (manifest {"frozen": {"questions_frozen.json": sha}}),
    confirmed by k_u2.json (stop false, same sha)."""
    if not manifest.is_file():
        raise SystemExit(f"{manifest} missing: F2 has not frozen the questions")
    got = (read_json(manifest).get("frozen") or {}).get(QUESTIONS_FROZEN.name)
    if not got:
        raise SystemExit(f"{manifest} has no frozen {QUESTIONS_FROZEN.name} sha (F2)")
    if not k_u2.is_file():
        raise SystemExit(f"{k_u2} missing: K-U2 was not run (F2)")
    ku = read_json(k_u2)
    if ku.get("stop") is not False:
        raise SystemExit(f"K-U2 stopped or undecided: {ku.get('wording')}")
    if ku.get("questions_frozen_sha256") != got:
        raise SystemExit(f"{k_u2.name} sha {ku.get('questions_frozen_sha256')} is not the {manifest.name} sha {got}")
    return got


def frozen_questions(path: Path = QUESTIONS_FROZEN, manifest: Path = MANIFEST,
                     k_u2: Path = K_U2) -> tuple[list[dict], str]:
    want, have = f2_sha(manifest, k_u2), sha256_file(path) if path.is_file() else None
    if have != want:
        raise SystemExit(f"{path} sha {have} is not the F2 manifest sha {want}")
    qs = items_c.questions_of(read_json(path))
    ids = [q["id"] for q in qs]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate question ids in the frozen set")
    return qs, have


def collect(questions: list[dict], q_sha: str, out: Path = CONTEXTS, failed: Path = FAILED, post=post_json,
            ps=cc.api_ps, log=print, sleep=time.sleep) -> dict:
    """Every question or nothing: contexts.json is written only when all of them pass."""
    if out.exists():
        raise SystemExit(f"{out} exists (F3 is frozen once); move it away only by a recorded infra fix")
    meta = {"endpoint": BACKEND_QUERY, "build_id": PROD_BUILD_ID, "top_k": TOP_K, "timeout_s": COLLECT_TIMEOUT_S,
            "retries": COLLECT_RETRIES, "questions_frozen_sha256": q_sha, "n_questions": len(questions),
            "request_template": request_body("{question}"), "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "api_ps_before": safe_ps(ps)}
    items, bad = {}, {}
    for i, q in enumerate(questions, 1):
        try:
            items[q["id"]] = query_checked(q["question"], post=post, sleep=sleep)
            log(f"[{i}/{len(questions)}] {q['id']} ok, {items[q['id']]['n_sources']} sources")
        except (Retryable, Rejected) as e:
            bad[q["id"]] = {"kind": type(e).__name__, "log": json.loads(str(e))}
            log(f"[{i}/{len(questions)}] {q['id']} FAILED ({type(e).__name__})")
    meta.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S"), api_ps_after=safe_ps(ps))
    if bad:
        write_atomic(failed, {"meta": meta, "n_failed": len(bad), "failed": bad, "passed": sorted(items)})
        raise SystemExit(f"{len(bad)} of {len(questions)} questions failed; nothing frozen, see {failed}")
    doc = {"meta": {**meta, "n_items": len(items), "n_empty": sum(not r["n_sources"] for r in items.values())},
           "items": items}
    write_atomic(out, doc)
    log(f"{out} sha256 {sha256_file(out)} (F3: record it in run_meta)")
    return doc


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="收集凍結題的 prod 基底 context（§4；只在授權的 Ollama 時段跑）")
    ap.parse_args(argv)
    qs, q_sha = frozen_questions()
    collect(qs, q_sha)


if __name__ == "__main__":
    main()
