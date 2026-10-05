"""The 「但」 geography rule and the generic-Event stoplist have one definition.

Step 10.2 (cleanup_noise_entities) deletes the MENTIONS edges whose 「但」 is
a conjunction or part of another name, and the generic-noun Event nodes. The
offline Step 6.05 has to see the graph as it stands after 10.2, so both rules
moved, unchanged, into entity_extraction.geo_rules and
entity_extraction.stoplists; cleanup re-exports them, so the scripts that
import them from cleanup (test_registry_rebuild_sim.py, the archived
docs/records simulators) still get the same objects.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

import cleanup_noise_entities
from entity_extraction import geo_rules, stoplists

ROOT = Path(__file__).resolve().parents[2]
MENTIONS = ROOT / "output" / "entity_mentions.jsonl"

# sha256 of the 26 keep sources, sorted and joined by "\n", as computed by
# cleanup_noise_entities before the move (output/ of 2026-04-18).
KEEP_SOURCES_SHA256 = "fc20f3f54846080585acc71f38d5a56b2ce161da2500e644704ea5aa43ac65dd"


@pytest.mark.parametrize(("context", "is_geo"), [
    ("從但到別是巴", True),
    ("但我", False),
    ("撒但", False),
    ("、但、", True),
    ("叫但。", True),
])
def test_geo_context_cases(context, is_geo):
    assert geo_rules.is_geo_context(context) is is_geo


def test_keeps_dan_mention_filters_place_dan_only():
    keep = {"gen:14:1"}
    assert geo_rules.DAN_ID == "place:dan"
    assert geo_rules.keeps_dan_mention("place:dan", "gen:14:1", keep)
    assert not geo_rules.keeps_dan_mention("place:dan", "gen:2:1", keep)
    assert geo_rules.keeps_dan_mention("person:dan", "gen:2:1", keep)
    assert geo_rules.keeps_dan_mention("place:dan", "gen:14:1", frozenset(keep))


def test_cleanup_reexports_the_shared_rules():
    assert cleanup_noise_entities.compute_dan_keep_sources is geo_rules.compute_dan_keep_sources
    assert cleanup_noise_entities._is_geo_context is geo_rules.is_geo_context
    assert cleanup_noise_entities.GENERIC_EVENT_STOPLIST is stoplists.GENERIC_EVENT_STOPLIST
    stoplist = stoplists.GENERIC_EVENT_STOPLIST
    assert len(stoplist) == len(set(stoplist)) == 24
    assert {"日子", "長子", "話", "明天"} <= set(stoplist)
    assert not {"饑荒", "瘟疫", "洪水"} & set(stoplist)  # real events stay


@pytest.mark.parametrize("module", [geo_rules, stoplists])
def test_shared_modules_use_the_standard_library_only(module):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    # 6.05 runs as `-m scripts.relation_extraction…` and imports the package name.
    by_package = importlib.import_module(f"scripts.entity_extraction.{module.__name__.split('.')[-1]}")
    assert Path(by_package.__file__) == Path(module.__file__)


@pytest.mark.skipif(not MENTIONS.exists(), reason="output/entity_mentions.jsonl is not present")
def test_dan_keep_sources_on_real_output():
    keep = geo_rules.compute_dan_keep_sources(MENTIONS)
    assert len(keep) == 26
    assert hashlib.sha256("\n".join(sorted(keep)).encode()).hexdigest() == KEEP_SOURCES_SHA256

    with MENTIONS.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if f'"{geo_rules.DAN_ID}"' in line]
    rows = [row for row in rows if row["entity_id"] == geo_rules.DAN_ID]
    # import_neo4j anchors a verse row on its pericope; 10.2 compares that s.id.
    edges = {row["source_id"].split(":v:")[0] for row in rows}
    kept = {key for key in edges if geo_rules.keeps_dan_mention(geo_rules.DAN_ID, key, keep)}
    assert (len(rows), len(edges), len(kept), len(edges - kept)) == (1882, 759, 26, 733)
    assert kept == keep
