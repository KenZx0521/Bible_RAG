"""K4, R1: the routing contract is the legacy lexicon, frozen (design §5.2, D-12(a)).

The frozen file ``config/registries/routing_lexicon.legacy.json`` (written by
``ragdata freeze route`` from the old backend's venv) is split into one ``routing_terms``
record per word — each ``external_legacy``, retired by R2 — and joined back into the
layer's ``routing_lexicon.json``; G-ROUTE requires the join to reproduce the frozen
file bit for bit, and the matcher rebuilt from it (``ragcommon.routing``) to give,
text for text, what the old ``entity_dicts`` gives on the probe texts: the 500 GT
questions, every verse and every heading. Those live matches are frozen too
(``k4_live``); ``subprocess_probe`` runs the old backend only for the DAG-external
``ragdata freeze`` commands.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import ragcommon
import ragdata
from ragcommon import routing
from ragdata.gates.base import Snapshot
from ragdata.stages.errors import StageError

LiveProbe = Callable[[Sequence[str]], list[dict[str, list[str]]]]
NAMED = ("persons", "places")
PROVENANCE = ("provenance_class", "source", "note", "retire_by")
PROBE_TIMEOUT_S = 600


def _term_row(category: str, position: int, entry: Mapping[str, Any]) -> dict[str, Any]:
    term = entry.get("canonical") or entry.get("term") or entry.get("name")
    return {"term_key": f"{category}/{position:04d}", "category": category, "position": position,
            "term": term, "aliases": list(entry.get("aliases", [])),
            "book_id": entry.get("book_id"), "full_name": entry.get("full_name"),
            **{k: entry[k] for k in PROVENANCE}}


def split_lexicon(doc: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(the document without its words, one record per word in file order)."""
    routing.parse_lexicon(doc)
    rest = {k: v for k, v in doc.items() if k not in routing.CATEGORIES}
    rows = [_term_row(c, i, e) for c in routing.CATEGORIES for i, e in enumerate(doc[c])]
    return rest, rows


def _entry(row: Mapping[str, Any]) -> dict[str, Any]:
    category, prov = row["category"], {k: row[k] for k in PROVENANCE}
    if category in NAMED:
        return {"canonical": row["term"], "aliases": list(row["aliases"]), **prov}
    if category == "events":
        return {"term": row["term"], **prov}
    return {"name": row["term"], "book_id": row["book_id"], "full_name": row["full_name"], **prov}


def join_lexicon(rest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda r: (routing.CATEGORIES.index(r["category"]), r["position"]))
    return {**rest, **{c: [_entry(r) for r in ordered if r["category"] == c]
                       for c in routing.CATEGORIES}}


# ------------------------------------------------------------------ probes


def probe_texts(snapshot: Snapshot, ground_truth: Path) -> dict[str, list[str]]:
    """The texts G-ROUTE matches: GT questions, every verse, every heading (serving text)."""
    try:
        questions = [q["question"] for q in json.loads(
            Path(ground_truth).read_text(encoding="utf-8"))["questions"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StageError(f"{ground_truth}: cannot read the GT questions: {exc}") from None
    return {"ground_truth": questions,
            "verses": [u.text for u in snapshot.of("verse_units")],
            "headings": [h.text for h in snapshot.of("headings")]}


def flatten(probes: Mapping[str, Sequence[str]]) -> list[str]:
    return [text for group in ("ground_truth", "verses", "headings") for text in probes[group]]


def probes_sha(texts: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(texts), ensure_ascii=False).encode("utf-8")).hexdigest()


def probe_summary(probes: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Texts per group, their total and the sha256 that names the set (``probes_sha``)."""
    texts = flatten(probes)
    return {**{k: len(v) for k, v in probes.items()}, "total": len(texts),
            "sha256": probes_sha(texts)}


def _pythonpath() -> str:
    roots = (Path(ragdata.__file__).resolve().parents[1],
             Path(ragcommon.__file__).resolve().parents[1])
    return os.pathsep.join(str(p) for p in roots)


def run_live(backend_python: Path, argv: Sequence[str]) -> None:
    """``python -m ragdata.legacy.route_live ARGV`` in the backend venv; StageError if it fails."""
    env = {**os.environ, "PYTHONPATH": _pythonpath(), "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1"}
    try:
        done = subprocess.run([str(backend_python), "-m", "ragdata.legacy.route_live", *argv],
                              env=env, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageError(f"cannot run the backend venv {backend_python}: {exc}") from None
    if done.returncode != 0:
        raise StageError(f"route_live {argv[0]} failed: {done.stderr.strip()[-500:]}")


def subprocess_probe(backend_python: Path, backend_dir: Path, texts: Sequence[str]
                     ) -> dict[str, Any]:
    """The live matches of ``texts`` (``results``) and the sha256 of the source files the
    backend imported (``sources``): ``ragdata.legacy.route_live probe`` in its venv."""
    with tempfile.TemporaryDirectory(prefix="route_live_") as tmp:
        given, out = Path(tmp) / "texts.json", Path(tmp) / "live.json"
        given.write_text(json.dumps(list(texts), ensure_ascii=False), encoding="utf-8")
        run_live(backend_python, ["probe", "--backend-dir", str(backend_dir),
                                  "--texts", str(given), "--out", str(out)])
        return json.loads(out.read_text(encoding="utf-8"))


def rebuilt_matches(lexicon: routing.RoutingLexicon, texts: Sequence[str]
                    ) -> list[dict[str, list[str]]]:
    return [{"persons": lexicon.match_persons(t), "places": lexicon.match_places(t),
             "events": lexicon.match_events(t), "books": lexicon.match_books(t)} for t in texts]


def zero_in_verses(rows: Sequence[Mapping[str, Any]], snapshot: Snapshot) -> dict[str, list[str]]:
    """Words of the lexicon that the PDF verse text never prints (design §9.1: 22 forms)."""
    corpus = "\n".join(u.text_pdf for u in snapshot.of("verse_units"))
    found: dict[str, list[str]] = {}
    for category in ("persons", "places", "events"):
        words = [w for r in rows if r["category"] == category
                 for w in (r["aliases"] or [r["term"]])]
        found[category] = sorted({w for w in words if w not in corpus})
    return found
