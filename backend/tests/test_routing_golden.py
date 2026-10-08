"""The R2 routing golden: on its frozen route layer, every GT v2 question routes as frozen.

``fixtures/routing_r2_gt.json`` (fixtures/make_routing_golden.py) names the route
layer it was computed on; the lexicon is read from that layer in the store. The test
skips while the golden is not frozen or the store does not hold its layer.
"""

import hashlib
import json
from pathlib import Path

import pytest

from fixtures.make_routing_golden import OUT, signals_row
from ragcommon import routing

ROUTE_LAYERS = Path("/mnt/ollama-data/bible_rag_store/layers/route")
GOLDEN = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else None
LEXICON = ROUTE_LAYERS / GOLDEN["route"] / "routing_lexicon.json" if GOLDEN else None
KEYS = ("persons", "places", "events", "books", "route")


@pytest.mark.skipif(GOLDEN is None, reason=f"{OUT.name} not frozen yet (make_routing_golden.py)")
@pytest.mark.skipif(LEXICON is not None and not LEXICON.is_file(),
                    reason=f"route layer {GOLDEN and GOLDEN['route']} not in the store")
def test_every_gt_question_routes_as_frozen():
    assert hashlib.sha256(LEXICON.read_bytes()).hexdigest() == GOLDEN["lexicon_sha256"]
    lexicon = routing.load_lexicon(LEXICON)

    for row in GOLDEN["rows"]:
        assert signals_row(lexicon, row["text"]) == {k: row[k] for k in KEYS}, row["question_id"]
