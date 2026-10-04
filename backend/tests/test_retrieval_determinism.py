"""The default retrieval path must not depend on PYTHONHASHSEED.

_extract_book_chapters collected (book_id, chapter) pairs in a set and
_sql_supplement takes the first three: which chapters got supplemented changed
with every process. Measured 2026-10-04: the same question on the production
backend and on backend-staging (same image, same data on that path) returned
different top-5s (gal:1:2 vs act:26:3, both sql_supplement).
"""

import os
import subprocess
import sys
from pathlib import Path

from utils.retrieval import router

BACKEND = Path(__file__).resolve().parents[1]


def _cand(cid: str, book: str, chapter: int) -> dict:
    return {"id": cid, "book_name": book, "chapter_num": chapter}


def test_chapters_follow_first_appearance_in_the_ranked_pool():
    pool = [
        _cand("act:26:1", "使徒行傳", 26), _cand("gal:1:0", "加拉太書", 1),
        _cand("act:26:0", "使徒行傳", 26), _cand("act:22:1", "使徒行傳", 22),
        _cand("act:9:0", "使徒行傳", 9),
    ]

    assert router._extract_book_chapters(pool) == [("act", 26), ("gal", 1), ("act", 22), ("act", 9)]


def test_chapter_order_is_identical_across_hash_seeds():
    code = (
        "from utils.retrieval import router\n"
        "pool = [{'id': f'b{i % 7}:{i}:0', 'book_name': 'x', 'chapter_num': i} for i in range(40)]\n"
        "print(router._extract_book_chapters(pool))\n"
    )
    outputs = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(BACKEND)}
        outputs.add(subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert len(outputs) == 1


def test_detected_signals_are_identical_across_hash_seeds():
    """detected_events/places/persons feed the opt-in graph strategies' query
    order; collected through sets they changed with every process."""
    code = (
        "from utils.signal_detector import detect_signals\n"
        "s = detect_signals('摩西和亞倫在耶路撒冷與伯利恆經歷出埃及、過紅海與逾越節', [], 'event',\n"
        "                   ['摩西', '亞倫', '約書亞'], ['十誡', '五旬節', '受難週'])\n"
        "print(s.detected_events, s.detected_places, s.detected_persons)\n"
    )
    outputs = set()
    for seed in ("1", "2", "3", "4"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(BACKEND)}
        outputs.add(subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert len(outputs) == 1, outputs


def test_chapter_pins_follow_verse_ref_order_across_hash_seeds():
    """Two chapter-only references (GENERAL_BIBLE_QUESTION_004: 約翰福音1章 /
    創世記1章): pins are prepended per target, so iterating the targets as a set
    put either chapter first depending on PYTHONHASHSEED."""
    code = (
        "from utils.retrieval import router\n"
        "from utils.verse_parser import VerseRef\n"
        "refs = [VerseRef('jhn', '約翰福音', 1), VerseRef('gen', '創世記', 1)]\n"
        "ranked = [{'id': f'rom:{i}:0', 'chapter_num': i, 'rerank_score': 0.5} for i in range(1, 6)]\n"
        "pool = ranked + [{'id': f'{b}:1:{j}', 'chapter_num': 1, 'weight': 0.9}\n"
        "                 for b in ('gen', 'jhn') for j in range(3)]\n"
        "print([c['id'] for c in router._pin_chapter_candidates(ranked, pool, refs, top_k=5)])\n"
    )
    outputs = set()
    for seed in ("1", "2", "3", "4", "5", "6"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(BACKEND)}
        outputs.add(subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                                   capture_output=True, text=True, check=True).stdout)
    assert len(outputs) == 1, outputs
    # verse_refs order: 約翰福音 is named first, so its pins are prepended first
    # and the later 創世記 pins end up in front.
    assert outputs.pop().startswith("['gen:1:0', 'gen:1:1', 'jhn:1:0', 'jhn:1:1'")
