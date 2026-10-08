"""The old backend's live matches on the probe texts, frozen in the store (K4, G-ROUTE).

G-ROUTE requires the matcher rebuilt from the frozen lexicon to give, text for text, what
the old ``entity_dicts`` gives on the probe texts. ``entity_dicts`` is gone from the
repository (R1 serves the contract lexicon), so its matches are taken once, outside the
DAG, by ``ragdata freeze probe`` in a checkout and venv that still have it, and stored per
probe set: ``{root}/{probes sha256}/live.json`` with a ``SHA256SUMS`` (``paths.ROUTE_LIVE``),
only when the files the backend actually imported are the lexicon's ``header.frozen_from``.
K4's build and G-ROUTE read them back for exactly their probe texts and for the backend
sources the lexicon was frozen from (its ``header.frozen_from``). No file for these texts,
a changed file or other sources fail closed, naming the command that regenerates it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragdata import reference
from ragdata.gates.base import Snapshot
from ragdata.kg import k4_route
from ragdata.kg.k4_route import LiveProbe
from ragdata.stages.errors import StageError

SCHEMA = "ragdata.route_live.v1"
LIVE = "live.json"
REGENERATE = ("regenerate it with `ragdata freeze probe --text <text layer> --backend-python "
              "<its venv python> --backend-dir <backend>` from a checkout whose backend "
              "sources are the lexicon's header.frozen_from (docs/rebuild_pipeline.md §1)")


def frozen_from(lexicon: Path) -> dict[str, str]:
    """The backend sources (path -> sha256) the frozen lexicon was taken from."""
    try:
        found = json.loads(Path(lexicon).read_text(encoding="utf-8"))["header"]["frozen_from"]
        return {str(k): str(v) for k, v in found.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StageError(f"{lexicon}: no header.frozen_from in the frozen lexicon "
                         f"({type(exc).__name__}: {exc})") from None


def _stored(root: Path) -> str:
    found = sorted(p.parent.name[:12] for p in Path(root).glob(f"*/{LIVE}"))
    return f"stored: {', '.join(found)}" if found else f"nothing stored under {root}"


def _problems(doc: Any, sha: str, count: int, sources: Mapping[str, str]) -> list[str]:
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    out = [] if doc.get("schema") == SCHEMA else [f"schema {doc.get('schema')!r}, not {SCHEMA}"]
    probes = doc.get("probes")
    recorded = probes.get("sha256") if isinstance(probes, dict) else None
    if recorded != sha:
        out.append(f"records the probe set {recorded}, not {sha}")
    results = doc.get("results")
    if not isinstance(results, list) or len(results) != count:
        out.append(f"{len(results) if isinstance(results, list) else 'no'} results for "
                   f"{count} probe texts")
    if doc.get("frozen_from") != dict(sources):
        out.append("taken from other backend sources than the lexicon's header.frozen_from")
    return out


def read_live(root: Path, texts: Sequence[str], sources: Mapping[str, str]
              ) -> list[dict[str, list[str]]]:
    """The frozen live matches of ``texts``, taken from the backend ``sources``."""
    sha = k4_route.probes_sha(texts)
    directory = Path(root) / sha
    if not (directory / LIVE).is_file():
        raise StageError(f"{directory / LIVE}: no frozen live matches for these {len(texts)} "
                         f"probe texts ({_stored(root)}); {REGENERATE}")
    try:
        reference.verified(directory, (LIVE,))
        doc = json.loads((directory / LIVE).read_text(encoding="utf-8"))
    except (reference.ReferenceError, ValueError) as exc:
        raise StageError(f"{exc}; {REGENERATE}") from None
    wrong = _problems(doc, sha, len(texts), sources)
    if wrong:
        raise StageError(f"{directory / LIVE}: {'; '.join(wrong)}; {REGENERATE}")
    return doc["results"]


def stored_probe(root: Path, lexicon: Path) -> LiveProbe:
    """The live matcher of K4's build and G-ROUTE: the matches frozen under ``root`` for the
    backend sources ``lexicon`` was frozen from."""
    def probe(texts: Sequence[str]) -> list[dict[str, list[str]]]:
        return read_live(root, texts, frozen_from(lexicon))
    return probe


# ------------------------------------------------------------------ ragdata freeze probe


def encode_live(probes: Mapping[str, Sequence[str]], sources: Mapping[str, str],
                results: Sequence[Mapping[str, Any]]) -> bytes:
    doc = {"schema": SCHEMA, "probes": k4_route.probe_summary(probes),
           "frozen_from": dict(sources), "results": list(results)}
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def write_live(root: Path, sha: str, data: bytes) -> Path:
    """Publish ``live.json`` and its SHA256SUMS as the new directory ``root/sha``; an existing
    one is never rewritten (the same bytes again are a no-op)."""
    target = Path(root) / sha
    if target.exists():
        if (target / LIVE).is_file() and (target / LIVE).read_bytes() == data:
            return target / LIVE
        raise StageError(f"{target} exists with other contents; a reference is never rewritten")
    Path(root).mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".route_live_", dir=root))
    try:
        (tmp / LIVE).write_bytes(data)
        (tmp / reference.SUMS).write_bytes(
            reference.encode_sums({LIVE: reference.sha256_file(tmp / LIVE)}))
        for name in (LIVE, reference.SUMS):
            os.chmod(tmp / name, 0o444)
        os.chmod(tmp, 0o755)
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target / LIVE


def _check_sources(imported: Any, sources: Mapping[str, str]) -> None:
    """Stop unless the backend imported exactly the source files the lexicon was frozen from."""
    have = imported if isinstance(imported, dict) else {}
    differ = sorted(s for s in {*sources, *have} if have.get(s) != sources.get(s))
    if differ:
        raise StageError(f"the backend imported {', '.join(differ)} with other contents than "
                         "the lexicon's header.frozen_from; probe the backend the lexicon was "
                         "frozen from")


def store_live(probes: Mapping[str, Sequence[str]], live: Mapping[str, Any],
               sources: Mapping[str, str], root: Path) -> dict[str, Any]:
    """Store the old backend's matches on ``probes`` (``live``: a ``route_live probe``
    output); the files it imported must be ``sources``, the lexicon's frozen_from."""
    _check_sources(live.get("sources"), sources)
    summary = k4_route.probe_summary(probes)
    path = write_live(root, summary["sha256"], encode_live(probes, sources, live["results"]))
    return {"written": str(path), "probes": summary, "frozen_from": dict(sources)}


def freeze_live(snapshot: Snapshot, backend_python: Path, backend_dir: Path, lexicon: Path,
                ground_truth: Path, root: Path) -> dict[str, Any]:
    """Run the old backend on the probe texts of a text layer (``snapshot``) and store its
    matches (``store_live``)."""
    sources = frozen_from(lexicon)
    probes = k4_route.probe_texts(snapshot, ground_truth)
    live = k4_route.subprocess_probe(backend_python, backend_dir, k4_route.flatten(probes))
    return store_live(probes, live, sources, root)
