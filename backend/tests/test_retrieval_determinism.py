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
