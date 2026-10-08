"""Freeze the R2 routing golden: the query-only signals of every GT v2 question on one route layer.

The golden (``routing_r2_gt.json``) names the route layer whose ``routing_lexicon.json``
it was computed on, and holds per question the persons, places, events and books the
detector found and the route they select with the parsed verse references but no
LLM output (intent "", no entities, no keywords). test_routing_golden.py replays it.
Regenerate it when a new route layer is meant to change routing, and review the diff.

Run it with the backend environment, from the repository root, on the route layer
directory (in the store, or a scratch store whose layer will be promoted unchanged):

    backend/.venv/bin/python backend/tests/fixtures/make_routing_golden.py \\
        /mnt/ollama-data/bible_rag_store/layers/route/route@<version>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "backend"), str(REPO / "packages")]

from ragcommon import routing  # noqa: E402
from utils.signal_detector import detect_signals  # noqa: E402
from utils.verse_parser import parse_verse_references  # noqa: E402

GT = REPO / "ground_truth.v2.json"
OUT = Path(__file__).resolve().parent / "routing_r2_gt.json"


def signals_row(lexicon: routing.RoutingLexicon, question: str) -> dict:
    book_ids = {b.full_name: b.book_id for b in lexicon.books}
    s = detect_signals(question, parse_verse_references(question), "", [], lexicon, book_ids)
    return {"persons": list(s.detected_persons), "places": list(s.detected_places),
            "events": list(s.detected_events), "books": list(s.detected_book_names),
            "route": s.route}


def golden(layer_dir: Path) -> dict:
    path = layer_dir / "routing_lexicon.json"
    lexicon = routing.load_lexicon(path)
    gt = GT.read_bytes()
    rows = [{"question_id": q["question_id"], "text": q["question"],
             **signals_row(lexicon, q["question"])} for q in json.loads(gt)["questions"]]
    return {"route": layer_dir.name,
            "lexicon_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "gt_sha256": hashlib.sha256(gt).hexdigest(), "rows": rows}


if __name__ == "__main__":
    doc = golden(Path(sys.argv[1]))
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(doc['rows'])} rows on {doc['route']}")
