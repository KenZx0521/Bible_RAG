"""P2-A — Generate grounded descriptions for entities lacking one.

Targets Person/Place/Group entities (4,223 records) whose `description` field
is empty in Neo4j. For each, fetches the canonical_name + a sample of
mentioning pericope titles and prompts a smaller LLM (default
gemma4:e4b-it-q8_0) for a <=80-character description constrained to the
provided context.

Description cache (docs/records/2026-10-04_kg_data_layer_fix_plan.md §3.1,
§3.5.1, EV-08): descriptions used to exist only in Neo4j, so a rebuild
(import_neo4j.py wipes the graph) lost them and re-running the LLM drifts.
Every accepted description is appended to output/frozen/descriptions.jsonl
(CACHE_FIELDS: the text plus model, temperature, prompt_version, titles_sha,
quality_flag, git_commit, generated_at) before it is written back. `--replay`
writes the cache back without calling the LLM. The cache is content-addressed
by (entity_id, titles_sha): an entity whose current title list hashes to no
cached entry is reported stale and left untouched (regeneration is batch 2B).
scripts/tools/export_live_state.py seeds the cache from live Neo4j and
`--promote`s the seed to the default cache path.

In the rebuild chain replay is a gate: every run writes a JSON report of the
stale and missing entities (--report, default output/frozen/replay_reports/),
and --fail-on-stale exits 1 when either list is non-empty.

Point at staging with NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (KG_TARGET=staging
refuses a production URI before connecting, see scripts/kg_target.py), and at
another cache with --cache or DESC_CACHE_PATH.

Usage:
    python -m scripts.relation_extraction.desc_generator \\
        [--target-types Person,Place,Group] [--limit N] [--dry-run]
    python -m scripts.relation_extraction.desc_generator --replay \\
        [--cache PATH] [--report PATH] [--fail-on-stale] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

import httpx
from dotenv import load_dotenv
from neo4j import GraphDatabase

from scripts import kg_target

from .config import Neo4jConfig

load_dotenv()
logger = logging.getLogger("desc_generator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = _REPO_ROOT / "output" / "frozen" / "descriptions.jsonl"
DEFAULT_REPORT_DIR = _REPO_ROOT / "output" / "frozen" / "replay_reports"

# Sampling temperature sent to the LLM, recorded per cache line (plan §3.1).
TEMPERATURE = 0.2

# Field order of one cache line; export_live_state.py writes the same shape
# through make_cache_entry so its seed replays like a generated entry.
CACHE_FIELDS = ("entity_id", "description", "model", "temperature", "prompt_version",
                "titles_sha", "quality_flag", "git_commit", "generated_at")

# quality_flag vocabulary. ok: parsed from the JSON reply; raw_text: the reply
# was not JSON and its first 80 chars were kept; unreviewed: seeded from live
# by export_live_state.py, generation path unknown. Plan D5 adds 'bad' for
# known factual errors (batch 2B).
QUALITY_OK = "ok"
QUALITY_RAW_TEXT = "raw_text"
QUALITY_UNREVIEWED = "unreviewed"


SYSTEM_PROMPT = """你是聖經實體百科編輯。給定一個實體 (人/地/群體) 與該實體相關的若干段聖經敘事,
請用繁體中文寫一句 60 字以內的客觀描述。

嚴格規則:
1. 描述必須完全基於提供的上下文,**不可加入未提及的事實**。
2. 不可使用「可能」「或許」「相傳」等不確定字眼。
3. 不可重述實體名稱本身;直接寫角色或屬性。
4. 一句話即可,不需多句。

回應格式 (JSON):
{"description": "..."}"""

_USER_PROMPT_TEMPLATE = (
    "實體名稱: {canonical}\n"
    "類型: {type_zh}\n"
    "出現於以下聖經段落:\n"
    "{title_lines}"
    "\n\n請用 60 字以內、純客觀的描述總結這個實體在聖經中的角色或位置。"
)


def _prompt_version(system_prompt: str, user_template: str) -> str:
    """Content hash of the prompt text: editing either prompt changes the
    version recorded in the cache without anyone having to remember a bump."""
    digest = hashlib.sha256(f"{system_prompt}\x00{user_template}".encode("utf-8"))
    return f"desc-{digest.hexdigest()[:12]}"


PROMPT_VERSION = _prompt_version(SYSTEM_PROMPT, _USER_PROMPT_TEMPLATE)


def titles_cypher(where: str) -> str:
    """Entity rows plus the prompt's title list, for entities matching `where`.

    The one place titles are computed — generation, --replay and
    export_live_state.py all use it, so titles_sha means the same thing
    everywhere. ORDER BY title before collect() makes the list the first six
    distinct titles in code-point order; without it collect() followed store
    order, so which six reached the prompt depended on import history.
    """
    return f"""
MATCH (e:Entity)
WHERE {where}
OPTIONAL MATCH (e)<-[:MENTIONS]-(src)
WHERE src:Pericope OR src:Chunk
WITH e, src,
     CASE
       WHEN src:Pericope THEN src.title
       WHEN src:Chunk    THEN src.pericope_title
       ELSE NULL
     END AS title
ORDER BY title
WITH e, [t IN collect(DISTINCT title) WHERE t IS NOT NULL AND t <> ''][0..6] AS titles
RETURN e.entity_id AS entity_id,
       e.canonical_name AS canonical_name,
       e.aliases AS aliases,
       [l IN labels(e) WHERE l <> 'Entity'][0] AS type,
       labels(e) AS labels,
       e.description AS description,
       titles
ORDER BY e.entity_id
"""


_FETCH_NEED_DESC_CYPHER = titles_cypher(
    "coalesce(e.description, '') = ''\n"
    "  AND any(label IN labels(e) WHERE label IN $target_types)"
)
_FETCH_BY_IDS_CYPHER = titles_cypher("e.entity_id IN $entity_ids")

# Phrases that signal the LLM refused for lack of context. Saving any of these
# as a description would pollute the graph; we treat them as failures and skip.
_REFUSAL_MARKERS = ("我無法", "請提供", "JSON 回應", "JSON回應", "未提供")


_UPDATE_DESC_CYPHER = """
UNWIND $rows AS row
MATCH (e:Entity {entity_id: row.entity_id})
SET e.description = row.description
"""


def titles_sha(titles: Optional[list[str]]) -> str:
    """sha256 of the ordered title list fed to the prompt (order is input)."""
    payload = json.dumps(list(titles or []), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_cache_entry(*, entity_id: str, description: str, model: str,
                     temperature: Optional[float], prompt_version: str,
                     titles: Optional[list[str]], quality_flag: str,
                     git_commit: Optional[str], generated_at: str) -> dict:
    """One cache line, keys in CACHE_FIELDS order."""
    return {
        "entity_id": entity_id,
        "description": description,
        "model": model,
        "temperature": temperature,
        "prompt_version": prompt_version,
        "titles_sha": titles_sha(titles),
        "quality_flag": quality_flag,
        "git_commit": git_commit,
        "generated_at": generated_at,
    }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git_commit() -> Optional[str]:
    """HEAD sha, suffixed -dirty when tracked files differ from it.

    prompt_version pins the prompt text but not the code around it (title
    query, reply parsing); the commit does, unless the tree was dirty, which
    the suffix says. None outside a git checkout.
    """
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=_REPO_ROOT,
                              capture_output=True, text=True, check=False)
    try:
        head = git("rev-parse", "HEAD")
        if head.returncode != 0:
            return None
        dirty = git("diff", "--quiet", "HEAD", "--").returncode != 0
    except OSError:
        return None
    return head.stdout.strip() + ("-dirty" if dirty else "")


def _fetch_targets(driver, target_types: list[str], limit: Optional[int]) -> list[dict]:
    with driver.session() as session:
        result = session.run(_FETCH_NEED_DESC_CYPHER, target_types=target_types)
        rows = [dict(r) for r in result]
    if limit:
        rows = rows[:limit]
    return rows


def _build_user_prompt(target: dict) -> str:
    titles = target.get("titles") or []
    return _USER_PROMPT_TEMPLATE.format(
        canonical=target["canonical_name"] or "",
        type_zh=target.get("type", "Entity"),
        title_lines="\n".join(f"- {t}" for t in titles if t),
    )


def _parse_reply(content: str) -> tuple[str, str]:
    """(description, quality_flag) from the raw LLM reply."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return str(data.get("description") or "").strip(), QUALITY_OK
        except json.JSONDecodeError:
            pass

    return text[:80].replace("\n", " ").strip(), QUALITY_RAW_TEXT


def _generate_description(
    client: httpx.Client,
    model: str,
    target: dict,
    num_ctx: int,
    num_predict: int,
) -> tuple[str, str]:
    response = client.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(target)},
            ],
            "stream": False,
            # Disable hidden reasoning — gemma4 *-it loops in thinking for some
            # entities (e.g. 艾城人 burnt 8192 tokens without producing JSON).
            # Same case finishes in ~55 tokens with think=false.
            "think": False,
            "options": {
                "temperature": TEMPERATURE,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        },
    )
    response.raise_for_status()
    payload = response.json()
    content = (payload.get("message") or {}).get("content", "")
    if not content:
        done_reason = payload.get("done_reason")
        eval_count = payload.get("eval_count")
        if done_reason == "length":
            raise RuntimeError(
                f"LLM truncated by num_predict={num_predict} (eval_count={eval_count}); "
                "raise DESC_NUM_PREDICT — reasoning models can emit hundreds of "
                "hidden thinking tokens before producing JSON."
            )
        raise RuntimeError(f"LLM returned empty content (done_reason={done_reason})")

    return _parse_reply(content)


def _write_back(driver, rows: list[dict]) -> None:
    if not rows:
        return
    with driver.session() as session:
        session.run(_UPDATE_DESC_CYPHER, rows=rows)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _open_cache(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8")


def _append_cache(fh: TextIO, entry: dict) -> None:
    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # Flush per line: a multi-hour run interrupted midway keeps every
    # description already paid for.
    fh.flush()


def load_cache(path: Path) -> dict[str, dict[str, dict]]:
    """entity_id -> titles_sha -> entry.

    The file is an append-only log, so a later line for the same
    (entity_id, titles_sha) supersedes an earlier one.
    """
    if not path.exists():
        raise SystemExit(f"description cache not found: {path}")
    cache: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{lineno}: invalid JSON ({e})") from e
            missing = [f for f in CACHE_FIELDS if f not in entry]
            if missing:
                raise SystemExit(f"{path}:{lineno}: cache line missing {missing}")
            cache.setdefault(entry["entity_id"], {})[entry["titles_sha"]] = entry
    return cache


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def plan_replay(cache: dict[str, dict[str, dict]],
                current: dict[str, dict]) -> dict[str, list]:
    """Classify cached entities against the target graph (no I/O).

    `current` maps entity_id -> row of _FETCH_BY_IDS_CYPHER. Only an entry
    whose titles_sha equals the entity's current one may be replayed; a
    description generated from other titles may describe the wrong person
    (e.g. person:maliya's text came from 撒馬利亞 mentions), so it is stale.
    """
    plan: dict[str, list] = {key: [] for key in (
        "rows", "written", "overwritten", "unchanged", "stale", "missing")}
    for eid in sorted(cache):
        row = current.get(eid)
        if row is None:
            plan["missing"].append(eid)
            continue
        entry = cache[eid].get(titles_sha(row["titles"]))
        if entry is None:
            plan["stale"].append(eid)
            continue
        have = row.get("description") or ""
        if have == entry["description"]:
            plan["unchanged"].append(eid)
            continue
        plan["rows"].append({"entity_id": eid, "description": entry["description"]})
        plan["written"].append(eid)
        if have:
            plan["overwritten"].append(eid)
    return plan


def build_report(cache_path: Path, cache: dict[str, dict[str, dict]],
                 current: dict[str, dict], summary: dict[str, list[str]], *,
                 dry_run: bool, neo4j_uri: Optional[str]) -> dict:
    """Machine-readable replay outcome.

    The rebuild chain is gated on exit codes, so a description lost to a
    stale or missing entity must not exist only as log lines. Stale entries
    carry the graph's current titles and the cached input hashes, enough to
    tell an upstream MENTIONS change from a wrong chain position.
    """
    return {
        "generated_at": _now(),
        "neo4j_uri": neo4j_uri,
        "cache": str(cache_path),
        "cache_sha256": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
        "dry_run": dry_run,
        "counts": {"cached": len(cache), **{key: len(ids) for key, ids in summary.items()}},
        "stale": [
            {"entity_id": eid,
             "canonical_name": current[eid].get("canonical_name"),
             "current_titles": list(current[eid]["titles"] or []),
             "current_titles_sha": titles_sha(current[eid]["titles"]),
             "cached_titles_sha": sorted(cache[eid])}
            for eid in summary["stale"]
        ],
        "missing": summary["missing"],
        "written": summary["written"],
        "overwritten": summary["overwritten"],
    }


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replay(driver, cache_path: Path, dry_run: bool, write_batch: int, *,
           report_path: Optional[Path] = None,
           neo4j_uri: Optional[str] = None) -> dict[str, list[str]]:
    """Write cached descriptions back to Neo4j without the LLM.

    Idempotent: rows already equal to the cache are left alone, so a second
    run writes nothing. Returns the plan's id lists (written / overwritten /
    unchanged / stale / missing); with report_path, also writes build_report
    there (dry runs included — classifying is their whole point).
    """
    cache = load_cache(cache_path)
    with driver.session() as session:
        current = {r["entity_id"]: dict(r) for r in
                   session.run(_FETCH_BY_IDS_CYPHER, entity_ids=sorted(cache))}
    plan = plan_replay(cache, current)
    rows = plan["rows"]
    if not dry_run:
        for start in range(0, len(rows), write_batch):
            _write_back(driver, rows[start:start + write_batch])

    summary = {key: ids for key, ids in plan.items() if key != "rows"}
    logger.info(
        "Replay %s: written=%d (overwrote %d non-empty) unchanged=%d stale=%d "
        "missing=%d (dry_run=%s)",
        cache_path, len(summary["written"]), len(summary["overwritten"]),
        len(summary["unchanged"]), len(summary["stale"]), len(summary["missing"]),
        dry_run,
    )
    for eid in summary["stale"]:
        logger.warning("Stale %s (%s): titles changed since cached — not replayed",
                       eid, current[eid].get("canonical_name"))
    for eid in summary["missing"]:
        logger.warning("Missing %s: cached but not in the target graph", eid)
    if report_path is not None:
        _write_report(report_path, build_report(cache_path, cache, current, summary,
                                                dry_run=dry_run, neo4j_uri=neo4j_uri))
        logger.info("Replay report: %s", report_path)
    return summary


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def _describe(http, args, target: dict, stats: Counter) -> Optional[tuple[str, str]]:
    """(description, quality_flag) for one target, or None when skipped."""
    if not (target.get("titles") or []):
        logger.warning("Skip %s (%s): no Pericope/Chunk context — "
                       "entity has no MENTIONS source",
                       target.get("entity_id"), target.get("canonical_name"))
        stats["skipped_no_context"] += 1
        return None

    try:
        desc, flag = _generate_description(
            http, args.model, target, args.num_ctx, args.num_predict,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM failed for %s (%s): %s",
                       target.get("entity_id"), target.get("canonical_name"), e)
        stats["failed"] += 1
        time.sleep(2)
        return None

    if not desc:
        return None
    if any(marker in desc for marker in _REFUSAL_MARKERS):
        logger.warning("Skip %s (%s): LLM refused — context insufficient. "
                       "Reply preview: %s",
                       target.get("entity_id"),
                       target.get("canonical_name"),
                       desc[:60])
        stats["skipped_refusal"] += 1
        return None
    return desc, flag


def run_generate(driver, http, args: argparse.Namespace) -> int:
    target_types = [t.strip() for t in args.target_types.split(",") if t.strip()]
    targets = _fetch_targets(driver, target_types, args.limit)
    logger.info("Found %d entities lacking description (types=%s)", len(targets), target_types)
    if not targets:
        return 0

    stats: Counter = Counter()
    pending: list[dict] = []
    # --dry-run keeps its no-side-effect promise for the cache too: a cache
    # line is a commitment that --replay will publish it.
    cache_fh = None if args.dry_run else _open_cache(args.cache)
    commit = None if args.dry_run else git_commit()
    try:
        for target in targets:
            result = _describe(http, args, target, stats)
            if result is None:
                continue
            desc, flag = result
            if cache_fh is not None:
                # Cache before the batched write-back so a crash between the
                # two loses nothing.
                _append_cache(cache_fh, make_cache_entry(
                    entity_id=target["entity_id"], description=desc,
                    model=args.model, temperature=TEMPERATURE,
                    prompt_version=PROMPT_VERSION, titles=target.get("titles"),
                    quality_flag=flag, git_commit=commit, generated_at=_now(),
                ))
            pending.append({"entity_id": target["entity_id"], "description": desc})
            stats["generated"] += 1

            if not args.dry_run and len(pending) >= args.write_batch:
                _write_back(driver, pending)
                pending = []
                logger.info("Updated %d/%d (failed=%d)",
                            stats["generated"], len(targets), stats["failed"])

        if pending and not args.dry_run:
            _write_back(driver, pending)
    finally:
        if cache_fh is not None:
            cache_fh.close()

    logger.info(
        "Done. generated=%d failed=%d skipped_no_context=%d skipped_refusal=%d "
        "(dry_run=%s)",
        stats["generated"], stats["failed"], stats["skipped_no_context"],
        stats["skipped_refusal"], args.dry_run,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-types", default="Person,Place,Group",
                        help="Comma-separated entity labels to target")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap entities processed (debug/dry runs)")
    parser.add_argument("--model", default=os.getenv("DESC_OLLAMA_MODEL", "gemma4:e4b-it-q8_0"))
    parser.add_argument("--base-url", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--num-ctx", type=int, default=int(os.getenv("DESC_NUM_CTX", "8192")))
    parser.add_argument("--num-predict", type=int, default=int(os.getenv("DESC_NUM_PREDICT", "2048")),
                        help="num_predict cap for the LLM. Reasoning models need "
                             ">=2048 to clear hidden thinking tokens before JSON.")
    parser.add_argument("--write-batch", type=int, default=50)
    parser.add_argument("--cache", type=Path, default=default_cache_path(),
                        help="Description cache JSONL: appended on generate, read by --replay "
                             "(default: DESC_CACHE_PATH, else output/frozen/descriptions.jsonl)")
    parser.add_argument("--replay", action="store_true",
                        help="Write cached descriptions back to Neo4j without the LLM. "
                             "Entities whose titles changed are listed as stale and "
                             "skipped. Covers every cached entity (--target-types and "
                             "--limit do not apply).")
    parser.add_argument("--report", type=Path, default=None,
                        help="--replay: JSON report of written/stale/missing entities "
                             "(default: output/frozen/replay_reports/replay_<timestamp>.json)")
    parser.add_argument("--fail-on-stale", action="store_true",
                        help="--replay: exit 1 when any cached entity is stale or missing "
                             "(matching rows are still written)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate but write neither Neo4j nor the cache; "
                             "with --replay, only classify")
    parser.add_argument("--verbose", action="store_true")
    return parser


def default_cache_path() -> Path:
    """The cache --replay reads when --cache is not given.

    export_live_state.py --promote writes the seed to this same path, so the
    rebuild chain replays the promoted cache without naming it.
    """
    return Path(os.getenv("DESC_CACHE_PATH") or DEFAULT_CACHE_PATH)


def _default_report_path() -> Path:
    return DEFAULT_REPORT_DIR / f"replay_{datetime.now():%Y%m%d_%H%M%S}.json"


def run_replay(driver, args: argparse.Namespace, neo4j_uri: str) -> int:
    report_path = args.report or _default_report_path()
    summary = replay(driver, args.cache, args.dry_run, args.write_batch,
                     report_path=report_path, neo4j_uri=neo4j_uri)
    if args.fail_on_stale and (summary["stale"] or summary["missing"]):
        logger.error("--fail-on-stale: %d stale, %d missing — see %s",
                     len(summary["stale"]), len(summary["missing"]), report_path)
        return 1
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.replay and (args.report or args.fail_on_stale):
        parser.error("--report and --fail-on-stale only apply to --replay")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    # Both modes write Neo4j; with KG_TARGET=staging a URI that is unset or
    # production stops here, before any connection.
    kg_target.assert_target("neo4j")
    neo4j_cfg = Neo4jConfig.from_env()
    # Name the target so a staging run (NEO4J_URI=bolt://...:7688) is visibly
    # not pointed at prod.
    logger.info("Neo4j target: %s", neo4j_cfg.uri)
    driver = GraphDatabase.driver(neo4j_cfg.uri, auth=(neo4j_cfg.user, neo4j_cfg.password))
    try:
        if args.replay:
            return run_replay(driver, args, neo4j_cfg.uri)
        http = httpx.Client(
            base_url=args.base_url,
            timeout=httpx.Timeout(120.0, connect=15.0, read=120.0, write=15.0),
        )
        try:
            return run_generate(driver, http, args)
        finally:
            http.close()
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
