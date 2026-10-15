"""Container entry of the book_anchor ablation (prereg §2, §3, §6, §9; §0.1 M1).

Runs in the one-off batch container of prereg §9 ("${BA_RUN[@]}"): image
bible_rag-backend:r2, PYTHONPATH=/app/packages:/app/backend, this directory at /exp and
$OUT at /in, both read-only. Writes no file: records go to stdout as JSON lines (every one
has "kind"; file descriptor 1 is moved to stderr first, so nothing else can reach the
records), logs go to stderr. Exit 2 with a one-line error on bad input or setup, 3 when I7
fails.

retrieve --questions Q [--ids-file F] [--force-ids F] [--resume R]
    With no question left to do, exits 0 at once (no model loaded, nothing written).
    Otherwise initialises as backend main.py's lifespan does (main.load_models,
    serving.startup.run, the LLM health check); a failed handshake or health check exits 2
    before any record, so a resume starts clean. Then a meta line (encoder_fingerprint in
    /health's {embedder, reranker} shape, as every collector run_meta.json has it), and for
    every question not yet in R:
    classify_intent once (ba_arms.intent_retry, §6 I4) and, on that one intent, ctrl →
    nopin → off strictly in sequence (ba_arms.arm). When ctrl never called
    routes._book_anchor, nopin and off are not run (arms_skipped "book_anchor_not_invoked")
    unless the qid is in --force-ids (M1). Any strategy_errors re-run the three arms on the
    same intent, at most twice. One "q" line per question: the intent, per arm the full
    results, stats, ctx_sha, the pool summary, signals, pins and _book_anchor calls.
generate --plan P --retrieval R [--resume G] [--retry-failed]
    No embedder, reranker or database. Every plan item's ctx_sha is first recomputed from
    the stored results with backend generator.build_context_blocks and must equal the
    retrieval record's and the plan's (I7, else exit 3 before anything is written); with no
    item left to do it then exits 0 writing nothing; a failed LLM health check exits 2
    before any record. Then a meta line and, for each item not in G (with --retry-failed:
    not or not successfully): generate_answer
    through a generator.get_llm_client proxy that hashes the messages sent; an answer that
    starts with 生成回答時發生錯誤 or is empty is retried at most twice and written as it is.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TextIO

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _ba_io as bio  # noqa: E402
import ba_arms  # noqa: E402

logger = logging.getLogger("ba_driver")

TOP_K = 5                  # what eval3c's collector sent (evaluation TOP_K=5)
USE_GRAPH = True           # run_eval --graph; graph_strategies / fusion_alpha: backend defaults
ARM_RETRIES = 2            # §6 I4: the three arms re-run at most twice on strategy_errors
INTENT_RETRIES = 2         # §6 I4
GEN_RETRIES = 2            # §6 I6
GEN_FAILURE_PREFIX = "生成回答時發生錯誤"
SKIPPED = "book_anchor_not_invoked"
BACKEND_ROOT = Path("/app/backend")
BACKEND_FILES = tuple(f"utils/retrieval/{n}.py" for n in (
    "routes", "router", "pins", "dense", "candidates", "event_registry")) + tuple(
    f"utils/{n}.py" for n in ("signal_detector", "intent_classifier", "generator", "reranker",
                              "embedder")) + (
    "routers/query.py", "models/request.py", "models/response.py", "config.py", "main.py",
    "utils/llm/ollama_client.py", "serving/startup.py")
POOL_FIELDS = ("id", "source_strategy", "weight", "semantic_score", "rerank_score",
               "fused_score", "book_id", "chapter_num", "found_by")
SETTINGS_FIELDS = ("rag_env", "rag_build_id", "strict_build_check", "rag_rank_fusion_enabled",
                   "rag_rank_fusion_alpha", "default_top_k", "rag_use_graph",
                   "rag_graph_strategies", "rag_event_registry_slots", "llm_provider",
                   "ollama_model", "ollama_base_url", "llm_temperature", "llm_max_tokens",
                   "semantic_search_top_k")
# main.load_models() names the embedder "bge_m3"; routers/health.py, and so every collector
# run_meta.json (eval3c full's, which §6 I0 compares with), name it "embedder".
LOAD_MODELS_TO_HEALTH = {"bge_m3": "embedder", "reranker": "reranker"}
ENV_FIELDS = ("RAG_ENV", "RAG_BUILD_ID", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
              "HF_HUB_OFFLINE", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


class DriverError(RuntimeError):
    """Bad input or setup: exit 2."""


class I7Error(RuntimeError):
    """The context to generate from is not the one retrieval hashed (§6 I7): exit 3."""


@dataclass(frozen=True)
class Deps:
    ic: Any                      # utils.intent_classifier
    router: Any                  # utils.retrieval.router
    routes: Any                  # utils.retrieval.routes
    generator: Any               # utils.generator
    build_blocks: Callable       # generator.build_context_blocks


# ---------------------------------------------------------------- retrieve

def intent_record(intent: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": intent["type"], "entities": list(intent.get("entities") or []),
            "keywords": list(intent.get("keywords") or []),
            "verse_refs": [getattr(r, "display", str(r)) for r in intent.get("verse_refs", [])],
            "rejected_refs": list(intent.get("rejected_refs") or [])}


def _signals(gathered: Any) -> dict[str, Any] | None:
    if gathered is None:
        return None
    signals = getattr(gathered, "signals", None)
    out = dataclasses.asdict(signals) if dataclasses.is_dataclass(signals) else {}
    return {**out, "route": getattr(gathered, "route", None),
            "multi_book": bool(getattr(gathered, "multi_book", False))}


def pool_summary(gathered: Any) -> list[dict[str, Any]]:
    candidates = getattr(gathered, "candidates", None) or []
    return [{k: c.get(k) for k in POOL_FIELDS} for c in candidates]


def prod_ctx_sha(deps: Deps, results: Sequence[Mapping[str, Any]]) -> str:
    """ctx_sha of the blocks joined as _ba_io does, which must be generator._build_context's
    own string (the context generate_answer sends); otherwise DriverError."""
    text = bio.context_text(results, deps.build_blocks)
    if text != deps.generator._build_context(results):
        raise DriverError("joined build_context_blocks != generator._build_context")
    return bio.sha256_bytes(text.encode("utf-8"))


def arm_output(rec: ba_arms.ArmRecord, results: list[dict], stats: Mapping[str, Any],
               deps: Deps) -> dict[str, Any]:
    """One arm's record; serialised at once, before the next arm runs."""
    return {"results": bio.to_jsonable(results), "stats": bio.to_jsonable(dict(stats)),
            "ctx_sha": prod_ctx_sha(deps, results),
            "ids": [r["id"] for r in results],
            "n_core": int(stats.get("reranked_top_k", len(results))),
            "pool": bio.to_jsonable(pool_summary(rec.gathered)),
            "signals": bio.to_jsonable(_signals(rec.gathered)),
            "pins": bio.to_jsonable(rec.pins), "ba_calls": rec.ba_calls, "ba_new": rec.ba_new}


async def _call(deps: Deps, question: str, intent: Mapping[str, Any]) -> tuple[list, dict]:
    """retrieve_and_rerank as routers/query.py calls it for eval3c's requests."""
    return await deps.router.retrieve_and_rerank(
        query=question, verse_refs=intent["verse_refs"], intent_type=intent["type"],
        entity_names=intent["entities"], top_k=TOP_K, keywords=intent.get("keywords"),
        use_graph=USE_GRAPH)


async def run_arms(deps: Deps, question: str, intent: Mapping[str, Any],
                   forced: bool) -> tuple[dict[str, Any], str | None]:
    """ctrl → nopin → off in sequence; nopin and off only when M1 allows."""
    arms: dict[str, Any] = {}
    with ba_arms.arm("ctrl", router=deps.router, routes=deps.routes) as ctrl:
        results, stats = await _call(deps, question, intent)
    arms["ctrl"] = arm_output(ctrl, results, stats, deps)
    if not ctrl.ba_invoked and not forced:
        return {**arms, "nopin": None, "off": None}, SKIPPED
    with ba_arms.arm("nopin", router=deps.router, routes=deps.routes,
                     snapshot=ctrl.snapshot) as nopin:
        results, stats = await _call(deps, question, intent)
    arms["nopin"] = arm_output(nopin, results, stats, deps)
    with ba_arms.arm("off", router=deps.router, routes=deps.routes) as off:
        results, stats = await _call(deps, question, intent)
    arms["off"] = arm_output(off, results, stats, deps)
    return arms, None


def _errors(arms: Mapping[str, Any]) -> dict[str, Any]:
    return {name: out["stats"]["strategy_errors"] for name, out in arms.items()
            if out and out["stats"].get("strategy_errors")}


async def retrieve_question(qid: str, question: str, deps: Deps, forced: bool) -> dict:
    """One question's "q" record: one intent, then the arms (re-run on strategy_errors)."""
    started = time.monotonic()
    with ba_arms.intent_retry(deps.ic, INTENT_RETRIES) as ilog:
        intent = await deps.ic.classify_intent(question)
    history: list[dict] = []
    for attempt in range(1, ARM_RETRIES + 2):
        arms, skipped = await run_arms(deps, question, intent, forced)
        errors = _errors(arms)
        if not errors:
            break
        history.append(errors)
        logger.warning("%s attempt %d strategy_errors %s", qid, attempt, errors)
    return {"kind": "q", "qid": qid, "question": question, "forced": forced,
            "arms_skipped": skipped, "intent": intent_record(intent), "intent_ok": ilog.ok,
            "intent_attempts": ilog.attempts, "intent_errors": ilog.errors,
            "arm_attempts": attempt, "error_history": history,
            "elapsed_s": round(time.monotonic() - started, 3), "arms": arms}


def select_questions(questions: Sequence[Mapping[str, str]], ids: Iterable[str] | None,
                     done: set[str]) -> list[Mapping[str, str]]:
    """Questions in file order: the --ids-file ones (all when None) not yet done."""
    known = {q["question_id"] for q in questions}
    wanted = None if ids is None else set(ids)
    if wanted is not None and wanted - known:
        raise DriverError(f"unknown question ids: {sorted(wanted - known)[:5]}")
    return [q for q in questions if (wanted is None or q["question_id"] in wanted)
            and q["question_id"] not in done]


async def retrieve_all(deps: Deps, todo: Sequence[Mapping[str, str]], force: set[str],
                       out: TextIO) -> int:
    for n, q in enumerate(todo, 1):
        row = await retrieve_question(q["question_id"], q["question"], deps,
                                      q["question_id"] in force)
        out.write(bio.dumps_line(row))
        out.flush()
        logger.info("[%d/%d] %s route=%s skipped=%s %.1fs", n, len(todo), row["qid"],
                    row["arms"]["ctrl"]["stats"].get("route_used"), row["arms_skipped"],
                    row["elapsed_s"])
    return len(todo)


# ---------------------------------------------------------------- generate

def _checked_sha(item: Mapping[str, Any], row: Mapping[str, Any], deps: Deps) -> str:
    rec = row["arms"].get(item["arm"])
    if rec is None:
        raise DriverError(f"{item['qid']}: the plan names arm {item['arm']}, which retrieval "
                          f"skipped ({row.get('arms_skipped')})")
    sha = prod_ctx_sha(deps, rec["results"])
    if not (sha == rec["ctx_sha"] == item.get("ctx_sha")):
        raise I7Error(f"{item['qid']} {item['arm']} r{item['rep']}: ctx_sha of the stored "
                      f"results {sha[:12]}, retrieval {str(rec['ctx_sha'])[:12]}, plan "
                      f"{str(item.get('ctx_sha'))[:12]}")
    return sha


def expected_messages(generator: Any, question: str, results: Sequence[Mapping[str, Any]],
                      build_blocks: Callable) -> list[dict[str, str]]:
    context = bio.context_text(results, build_blocks)
    return [{"role": "system", "content": generator.SYSTEM_PROMPT},
            {"role": "user", "content": generator.CONTEXT_TEMPLATE.format(
                context=context, question=question)}]


def _failed(answer: str | None) -> bool:
    return not (answer or "").strip() or answer.startswith(GEN_FAILURE_PREFIX)


async def generate_item(item: Mapping[str, Any], row: Mapping[str, Any], deps: Deps) -> dict:
    """One plan item's "gen" record; I7 before the LLM, failures retried (§6 I6)."""
    sha = _checked_sha(item, row, deps)
    results = row["arms"][item["arm"]]["results"]
    expected = bio.messages_sha(expected_messages(deps.generator, row["question"], results,
                                                  deps.build_blocks))
    started, failures = time.monotonic(), []
    for attempt in range(1, GEN_RETRIES + 2):
        with ba_arms.llm_capture(deps.generator) as cap:
            answer = await deps.generator.generate_answer(row["question"], results)
        if not _failed(answer):
            break
        failures.append((answer or "")[:300])
        logger.warning("%s %s r%s attempt %d failed: %s", item["qid"], item["arm"],
                       item["rep"], attempt, (answer or "")[:120])
    return {"kind": "gen", "qid": item["qid"], "arm": item["arm"], "rep": int(item["rep"]),
            "order": item.get("order"), "answer": answer, "ok": not _failed(answer),
            "attempts": attempt, "failures": failures, "ctx_sha": sha,
            "messages_sha": cap.messages_sha, "messages_expected_sha": expected,
            "messages_match": (cap.messages_sha == expected) if cap.n_calls else None,
            "llm_options": cap.options, "n_llm_calls": cap.n_calls,
            "elapsed_s": round(time.monotonic() - started, 3)}


def verify_plan(deps: Deps, plan: Sequence[Mapping[str, Any]],
                rows: Mapping[str, Mapping[str, Any]]) -> None:
    """I7 for every plan item, before any LLM call or record."""
    for item in plan:
        if item["qid"] not in rows:
            raise DriverError(f"{item['qid']}: in the plan but not in the retrieval file")
        _checked_sha(item, rows[item["qid"]], deps)


def pending(plan: Sequence[Mapping[str, Any]], done: set) -> list[Mapping[str, Any]]:
    return [it for it in plan if (it["qid"], it["arm"], int(it["rep"])) not in done]


async def generate_items(deps: Deps, todo: Sequence[Mapping[str, Any]],
                         rows: Mapping[str, Mapping[str, Any]], out: TextIO) -> int:
    for n, item in enumerate(todo, 1):
        rec = await generate_item(item, rows[item["qid"]], deps)
        out.write(bio.dumps_line(rec))
        out.flush()
        logger.info("[%d/%d] %s %s r%d ok=%s %.1fs", n, len(todo), rec["qid"], rec["arm"],
                    rec["rep"], rec["ok"], rec["elapsed_s"])
    return len(todo)


async def generate_all(deps: Deps, plan: Sequence[Mapping[str, Any]],
                       rows: Mapping[str, Mapping[str, Any]], done: set,
                       out: TextIO) -> int:
    verify_plan(deps, plan, rows)
    return await generate_items(deps, pending(plan, done), rows, out)


# ---------------------------------------------------------------- files

def _json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DriverError(f"cannot read {path}: {exc}") from None


def load_questions(path: Path) -> list[dict[str, str]]:
    doc = _json(path)
    if not isinstance(doc, list) or not all(
            isinstance(q, dict) and q.get("question_id") and q.get("question") for q in doc):
        raise DriverError(f"{path}: expected a list of {{question_id, question}}")
    return doc


def load_id_list(path: Path | None) -> list[str] | None:
    if path is None:
        return None
    doc = _json(path)
    if not isinstance(doc, list) or not all(isinstance(x, str) for x in doc):
        raise DriverError(f"{path}: expected a JSON list of question ids")
    return doc


def retrieval_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in bio.read_jsonl(path):
        if row["kind"] != "q":
            continue
        if row["qid"] in rows:
            raise DriverError(f"{path}: {row['qid']} recorded twice")
        rows[row["qid"]] = row
    return rows


def load_plan(path: Path) -> list[dict]:
    doc = _json(path)
    items = doc.get("items") if isinstance(doc, dict) else None
    keys = ("qid", "arm", "rep", "ctx_sha")
    if not isinstance(items, list) or not all(isinstance(i, dict) and all(k in i for k in keys)
                                              for i in items):
        raise DriverError(f"{path}: expected {{'items': [{{{', '.join(keys)}}}]}}")
    return items


# ---------------------------------------------------------------- container setup (§6 I0)

def file_shas(root: Path, names: Iterable[str]) -> dict[str, str]:
    return {name: bio.sha256_file(root / name) for name in names}


def _meta(mode: str, settings: Any, argv: Sequence[str], **extra: Any) -> dict[str, Any]:
    return {"kind": "meta", "mode": mode,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "settings": {k: getattr(settings, k, None) for k in SETTINGS_FIELDS},
            "call": {"top_k": TOP_K, "use_graph": USE_GRAPH, "graph_strategies": None,
                     "fusion_alpha": None},
            "backend_sha256": file_shas(BACKEND_ROOT, BACKEND_FILES),
            "exp_sha256": file_shas(_HERE, sorted(p.name for p in _HERE.glob("*.py"))),
            "env": {k: os.environ.get(k) for k in ENV_FIELDS},
            "python": sys.version.split()[0], "hostname": platform.node(), "pid": os.getpid(),
            "argv": list(argv), **extra}


def health_encoder(fingerprints: Mapping[str, Any]) -> dict[str, Any]:
    """main.load_models()'s fingerprints under /health's keys ({embedder, reranker})."""
    if set(fingerprints) != set(LOAD_MODELS_TO_HEALTH):
        raise DriverError(f"main.load_models() returned {sorted(fingerprints)}, expected "
                          f"{sorted(LOAD_MODELS_TO_HEALTH)}")
    return {LOAD_MODELS_TO_HEALTH[k]: fingerprints[k] for k in LOAD_MODELS_TO_HEALTH}


def retrieve_meta(settings: Any, argv: Sequence[str], *, fingerprints: Mapping[str, Any],
                  **extra: Any) -> dict[str, Any]:
    """The retrieve meta line; written only after the handshake and LLM check passed."""
    return _meta("retrieve", settings, argv, encoder_fingerprint=health_encoder(fingerprints),
                 load_models_fingerprint=dict(fingerprints), llm_health=True, **extra)


async def _llm_ready() -> Any:
    """The LLM client after a passing health check; DriverError (no record) otherwise."""
    from utils.llm import get_llm_client

    llm = get_llm_client()
    if not await llm.health_check():
        raise DriverError(f"LLM health check failed ({llm.provider_name}); nothing written, "
                          "run the same command again")
    return llm


async def _run_retrieve(args: argparse.Namespace, out: TextIO, argv: Sequence[str]) -> None:
    questions = load_questions(args.questions)
    todo = select_questions(questions, load_id_list(args.ids_file),
                            bio.done_questions(bio.read_jsonl(args.resume, missing_ok=True))
                            if args.resume else set())
    force = set(load_id_list(args.force_ids) or [])
    if not todo:
        logger.info("retrieve: nothing to do; no model loaded, nothing written")
        return

    import main as backend_main  # the lifespan's own load_models; logging as prod
    import torch
    from config import settings
    from serving import context, startup
    from utils import embedder, generator, intent_classifier
    from utils.retrieval import router, routes

    started = time.monotonic()
    fingerprints = backend_main.load_models()
    try:
        handshake = await startup.run(fingerprints)
        if not handshake.ok:
            raise DriverError("build handshake failed: " + "; ".join(handshake.mismatches))
        llm = await _llm_ready()
        out.write(bio.dumps_line(retrieve_meta(
            settings, argv, fingerprints=fingerprints, build_id=context.active().build.build_id,
            handshake=handshake.to_json(), device=embedder.get_device(),
            torch_threads=torch.get_num_threads(), llm_provider=llm.provider_name,
            n_todo=len(todo), n_force=len(force))))
        out.flush()
        deps = Deps(intent_classifier, router, routes, generator, generator.build_context_blocks)
        n = await retrieve_all(deps, todo, force, out)
        out.write(bio.dumps_line({"kind": "end", "mode": "retrieve", "n_done": n,
                                  "elapsed_s": round(time.monotonic() - started, 1)}))
    finally:
        await startup.stop()


async def _run_generate(args: argparse.Namespace, out: TextIO, argv: Sequence[str]) -> None:
    from config import settings
    from utils import generator, intent_classifier

    plan = load_plan(args.plan)
    rows = retrieval_rows(args.retrieval)
    done = (bio.done_gens(bio.read_jsonl(args.resume, missing_ok=True), args.retry_failed)
            if args.resume else set())
    deps = Deps(intent_classifier, None, None, generator, generator.build_context_blocks)
    verify_plan(deps, plan, rows)                    # I7 (exit 3) before anything is written
    todo = pending(plan, done)
    if not todo:
        logger.info("generate: nothing to do (%d plan items done); nothing written", len(plan))
        return
    started = time.monotonic()
    llm = await _llm_ready()
    out.write(bio.dumps_line(_meta("generate", settings, argv, build_id=settings.rag_build_id,
                                   llm_health=True, llm_provider=llm.provider_name,
                                   n_plan=len(plan), n_done_before=len(done))))
    out.flush()
    n = await generate_items(deps, todo, rows, out)
    out.write(bio.dumps_line({"kind": "end", "mode": "generate", "n_done": n,
                              "elapsed_s": round(time.monotonic() - started, 1)}))


# ---------------------------------------------------------------- CLI

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("retrieve")
    r.add_argument("--questions", type=Path, required=True)
    r.add_argument("--ids-file", type=Path, default=None)
    r.add_argument("--force-ids", type=Path, default=None)
    r.add_argument("--resume", type=Path, default=None)
    g = sub.add_parser("generate")
    g.add_argument("--plan", type=Path, required=True)
    g.add_argument("--retrieval", type=Path, required=True)
    g.add_argument("--resume", type=Path, default=None)
    g.add_argument("--retry-failed", action="store_true")
    return parser.parse_args(argv)


def _claim_stdout() -> TextIO:
    """The records' stream: the original stdout; fd 1 itself now points at stderr."""
    sys.stdout.flush()
    stream = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    return stream


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    out = _claim_stdout()
    runner = _run_retrieve if args.cmd == "retrieve" else _run_generate
    try:
        asyncio.run(runner(args, out, argv))
        return 0
    except I7Error as exc:
        print(f"ba_driver: I7 failed: {exc}", file=sys.stderr)
        return 3
    except (DriverError, bio.BaIoError) as exc:
        print(f"ba_driver: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — traceback to the log, one line last
        logger.exception("unexpected failure")
        print(f"ba_driver: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        out.flush()


if __name__ == "__main__":
    sys.exit(main())
