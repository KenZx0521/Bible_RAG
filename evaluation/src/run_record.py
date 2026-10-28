"""What a collection run was, recorded beside its checkpoint (run_meta.json v2).

provenance.py records the build and encoder (/health). This module adds what a run
needs to be audited later without docker inspect, container logs or git archaeology
(2026-10-28 P0):

* ``collection``: when (started_at / finished_at), which arm (mode), the CLI argv,
  top_k, the graph strategies asked for, the ids file and its sha256, the number of
  questions asked and collected. The collector always starts fresh (it has no resume),
  so ``resumed`` stays []; the field is where a resumed run would list its restarts.
* ``eval_code``: the evaluation code's git HEAD and its uncommitted paths.
* ``backend_runtime``: the backend container's image and an allowlist of its
  environment. No secret is ever recorded (:func:`safe_env`): names are matched
  case-insensitively (the backend's settings read them so), secret-shaped names are
  dropped, and URL credentials and secret-shaped values are masked.
* ``generator``: the generator model, with its digest and size when it runs on Ollama.
* ``backend_health``: the /health handshake summary (ok, strict, mismatches).

Every probe is best effort: one that fails (docker missing, container gone, timeout,
Ollama down or answering an odd body, not a git checkout, or any unexpected error)
records ``{"error": ...}``, logs a warning, and the collection goes on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .config import settings

logger = logging.getLogger(__name__)

RUN_META_VERSION = 2
PROBE_TIMEOUT_S = 5.0
MAX_DIRTY_PATHS = 50
EVAL_ROOT = Path(__file__).resolve().parent.parent

# Backend env recorded by name (compared upper-cased). Reviewed by hand: none holds a secret.
ENV_ALLOWLIST = frozenset({
    "LLM_PROVIDER", "OLLAMA_MODEL", "CLAUDE_MODEL", "OPENAI_MODEL", "GEMINI_MODEL",
    "LLM_TEMPERATURE", "LLM_MAX_TOKENS", "RAG_RANK_FUSION_ALPHA", "RAG_USE_GRAPH",
    "RAG_GRAPH_STRATEGIES", "RAG_ENTITY_QUERY_TOP_K", "STRICT_BUILD_CHECK",
    # retrieval switches the README's ablation tables name
    "HYBRID_SEARCH_ENABLED", "HYBRID_FUSION_METHOD", "HYBRID_PREFETCH_LIMIT",
})
# Other RAG_* variables are recorded unless their (upper-cased) name says they may hold a secret.
_RAG_PREFIX = "RAG_"
_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASS", "PWD", "AUTH", "CRED", "DSN",
                   "PRIVATE", "CERT")
# Everything between scheme:// and the last @ of a URL value (user:password, whatever it
# contains) is masked whatever the name.
_URL_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)\S*@", re.I)
# A kept value that looks like a credential is masked whole: a known key prefix, or an
# opaque run of 24+ letters and digits (hex digest, base64) mixing both.
_SECRET_VALUE_PREFIX = re.compile(r"(sk-|sk_|ghp_|gho_|ghs_|github_pat_|AKIA|ASIA|AIza|xox[abprs]-|hf_)")
_OPAQUE_RUN = re.compile(r"[A-Za-z0-9+=]{24,}")
MASK = "***"
_MODEL_VAR = {"ollama": "OLLAMA_MODEL", "claude": "CLAUDE_MODEL",
              "openai": "OPENAI_MODEL", "gemini": "GEMINI_MODEL"}


def now_iso() -> str:
    """Local time, ISO 8601 with its UTC offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def collection_mode(use_graph: bool | None, semantic_only: bool) -> str:
    """The arm a collection ran, from the CLI flags (not from what the backend reports)."""
    if semantic_only:
        return "semantic"
    return {True: "graph", False: "no_graph", None: "default"}[use_graph]


def _run(cmd: list[str], timeout: float) -> str:
    """stdout of ``cmd``; raises on a non-zero exit (stderr in the message), a timeout or no binary."""
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} exited {done.returncode}: {done.stderr.strip()[:300]}")
    return done.stdout


def _get_json(url: str, timeout: float) -> Any:
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _error(what: str, exc: BaseException) -> dict[str, str]:
    message = f"{type(exc).__name__}: {exc}"[:500]
    logger.warning("[run_meta] %s unavailable: %s", what, message)
    return {"error": message}


# --- eval_code ----------------------------------------------------------------------------

def _porcelain_entries(status: str) -> list[tuple[str, str]]:
    """(XY status, path) per `git status --porcelain` line (a rename keeps its new path)."""
    entries = []
    for line in status.splitlines():
        if len(line) > 3:
            path = line[3:].rpartition(" -> ")[2]
            entries.append((line[:2], path))
    return entries


def _is_untracked_output(code: str, path: str) -> bool:
    """An untracked results*/ directory under evaluation/: run output, not code."""
    return code == "??" and path.startswith("evaluation/results")


def eval_code_state() -> dict[str, Any]:
    """git HEAD of the evaluation code and its uncommitted paths under evaluation/.

    ``git_dirty`` ignores untracked results*/ output directories; ``dirty_paths`` lists
    every entry (at most 50; ``n_dirty_paths`` counts them all).
    """
    git = ["git", "-C", str(EVAL_ROOT)]
    try:
        head = _run([*git, "rev-parse", "HEAD"], PROBE_TIMEOUT_S).strip()
        status = _run([*git, "-c", "core.quotePath=false", "status", "--porcelain", "--", "."],
                      PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - no git / not a checkout: recorded, not fatal
        return _error("git state", exc)
    entries = _porcelain_entries(status)
    return {
        "git_head": head,
        "git_dirty": any(not _is_untracked_output(code, path) for code, path in entries),
        "dirty_paths": [path for _, path in entries[:MAX_DIRTY_PATHS]],
        "n_dirty_paths": len(entries),
    }


# --- backend_runtime ----------------------------------------------------------------------

def _recordable(name: str) -> bool:
    upper = name.upper()       # the backend's pydantic settings match env names in any case
    if upper in ENV_ALLOWLIST:
        return True
    return upper.startswith(_RAG_PREFIX) and not any(m in upper for m in _SECRET_MARKERS)


def _looks_secret(value: str) -> bool:
    if _SECRET_VALUE_PREFIX.match(value.strip()):
        return True
    return any(re.search(r"[A-Za-z]", run) and re.search(r"\d", run)
               for run in _OPAQUE_RUN.findall(value))


def _masked(value: str) -> str:
    value = _URL_CREDENTIALS.sub(rf"\1{MASK}@", value)
    return MASK if _looks_secret(value) else value


def safe_env(env: Sequence[str]) -> dict[str, str]:
    """The recordable part of a container's ``NAME=value`` list (allowlist + safe RAG_*).

    Anything else (API keys, passwords, tokens, PATH, ...) is dropped by name; a kept
    value has its URL credentials masked, and is masked whole when it looks like a key.
    """
    kept = {}
    for item in env:
        name, sep, value = item.partition("=")
        if sep and _recordable(name):
            kept[name] = _masked(value)
    return dict(sorted(kept.items()))


def backend_runtime(container: str | None = None) -> dict[str, Any]:
    """Image, start time and allowlisted env of the backend container (docker inspect, read only)."""
    name = container or settings.eval_backend_container
    try:
        out = _run(["docker", "inspect", "--type", "container", name], PROBE_TIMEOUT_S)
        info = json.loads(out)[0]
        config = info.get("Config") or {}
        return {
            "container": name,
            "image": config.get("Image"),
            "image_id": info.get("Image"),
            "started_at": (info.get("State") or {}).get("StartedAt"),
            "env": safe_env(config.get("Env") or []),
        }
    except Exception as exc:  # noqa: BLE001 - docker missing / no container / timeout: recorded
        return {"container": name, **_error(f"docker inspect {name}", exc)}


# --- generator ----------------------------------------------------------------------------

def _ollama_model(model: str) -> dict[str, Any]:
    """Digest and size of ``model`` as the evaluation's Ollama (settings.ollama_base_url) lists it."""
    url = f"{settings.ollama_base_url}/api/tags"
    try:
        tags = _get_json(url, PROBE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - Ollama down: recorded
        return _error(url, exc)
    models = tags.get("models") if isinstance(tags, Mapping) else None
    if not isinstance(models, list):
        return _error(url, TypeError(f"not an Ollama tags body: {str(tags)[:200]}"))
    wanted = {model} if ":" in model else {model, f"{model}:latest"}
    for entry in models:
        names = (entry.get("name"), entry.get("model")) if isinstance(entry, Mapping) else ()
        if any(isinstance(n, str) and n in wanted for n in names):
            return {"digest": entry.get("digest"), "size": entry.get("size")}
    return _error("ollama model", LookupError(f"{model} is not among {url}'s models"))


def generator_info(runtime: Mapping[str, Any]) -> dict[str, Any]:
    """The backend's generator (provider, model; digest and size on Ollama), from its env."""
    env = runtime.get("env")
    if not isinstance(env, Mapping):
        return {"error": f"backend runtime unknown ({runtime.get('error', 'no env')})"}
    provider = env.get("LLM_PROVIDER")
    if not provider:
        return {"error": "LLM_PROVIDER is not in the backend env"}
    model = env.get(_MODEL_VAR.get(provider.lower(), ""))
    if provider.lower() != "ollama":
        return {"provider": provider, "model": model}
    if not model:
        return {"provider": provider, "error": "OLLAMA_MODEL is not in the backend env"}
    return {"provider": provider, "model": model, **_ollama_model(model)}


# --- health and the record ----------------------------------------------------------------

def health_summary(health: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """/health beyond build_id and encoder (already in run_meta): status, services, handshake."""
    if health is None:
        return None
    handshake = health.get("handshake")
    handshake = handshake if isinstance(handshake, Mapping) else {}
    return {"status": health.get("status"), "services": health.get("services"),
            "ok": handshake.get("ok"), "strict": handshake.get("strict"),
            "mismatches": handshake.get("mismatches")}


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        _error(f"ids file {path}", exc)
        return None


@dataclass(frozen=True)
class CollectionInputs:
    """What the CLI gave a collection beyond the collector's own arguments."""
    argv: tuple[str, ...] = ()
    ids_file: Path | None = None
    health: Mapping[str, Any] | None = None     # the /health body the run was bound to


def _probe(what: str, fn, *args) -> Any:
    """``fn(*args)``; an error the probe did not expect is recorded the same way, never raised."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - a probe must never stop the collection
        return _error(what, exc)


def start_record(*, mode: str, graph_strategies: list[str] | None, n_questions: int,
                 inputs: CollectionInputs) -> dict[str, Any]:
    """The run_meta.json v2 sections, written as collection starts (finished_at null)."""
    runtime = _probe("backend runtime", backend_runtime)
    ids_file = inputs.ids_file
    return {
        "run_meta_version": RUN_META_VERSION,
        "collection": {
            "started_at": now_iso(), "finished_at": None, "mode": mode,
            "argv": list(inputs.argv), "top_k": settings.top_k,
            "graph_strategies_requested": graph_strategies,
            "ids_file": None if ids_file is None else str(ids_file),
            "ids_file_sha256": None if ids_file is None else _file_sha256(ids_file),
            "n_questions": n_questions, "resumed": [],
        },
        "eval_code": _probe("git state", eval_code_state),
        "backend_runtime": runtime,
        "generator": _probe("generator", generator_info, runtime),
        "backend_health": _probe("health summary", health_summary, inputs.health),
    }


def finish_record(record: Mapping[str, Any], *, n_collected: int,
                  n_request_failures: int) -> dict[str, Any]:
    """A copy of ``record`` stamped finished, with what was collected."""
    collection = {**record["collection"], "finished_at": now_iso(), "n_collected": n_collected,
                  "n_request_failures": n_request_failures}
    return {**record, "collection": collection}
