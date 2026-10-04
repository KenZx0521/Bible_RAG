"""The five pericope titles in an entity's embedding text must not follow store order.

collect(DISTINCT title)[0..5] with no ORDER BY took whichever titles the
store visited first, so two equivalent stores embedded different text: prod
bible_entities and the staging rebuild bible_entities_v2 had identical
descriptions for all 9,124 entities, yet 4,377 different title lists and 2,894
vectors with cosine < 0.99 (docs/records/2026-10-05_kg_batch1_w0_results.md).
Titles are taken in code-point order, as desc_generator.titles_cypher does.
"""

import re

import backfill_head_events
import embed_entities


def test_rows_are_ordered_before_the_titles_are_collected():
    cypher = embed_entities.fetch_entities_cypher()
    assert re.search(
        r"AS pid\s+ORDER BY title, pid\s+WITH e,\s+\[t IN collect\(DISTINCT title\)", cypher
    ), cypher
    assert cypher.rstrip().endswith("ORDER BY e.entity_id")


def test_full_embed_and_head_event_reembed_build_the_same_text():
    full = embed_entities.fetch_entities_cypher()
    some = embed_entities.fetch_entities_cypher("e.entity_id IN $ids")
    assert full.replace("WHERE true", "WHERE e.entity_id IN $ids") == some
    assert embed_entities._FETCH_ENTITIES_CYPHER == full


def test_head_event_reembed_has_no_title_query_of_its_own():
    source = open(backfill_head_events.__file__, encoding="utf-8").read()
    assert "collect(DISTINCT title)" not in source
    assert 'fetch_entities_cypher("e.entity_id IN $ids")' in source
