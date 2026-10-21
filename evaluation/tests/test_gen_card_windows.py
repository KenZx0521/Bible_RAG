"""The GEN card integration's files share no 8-character window with scripture, a real question or a real card
(plan docs/records/2026-10-21_gen_card_integration_plan.md §2.3: repo 不放任何經節字串、真實題目與卡片).

Scanned (globs, so a file another branch adds is covered once merged): the backend wrapper and its tests, the ragdata
GEN builders and their tests, the A4 folder, these evaluation tests and the plan's records. A .py file's text and its
string constants (ast: implicit concatenation and escapes resolved), a .md file's text, each as written and NFKC.
Against: the text layer's verses, GT v1/v2, A's frozen confirm questions, stage-0's items, the GEN confirm set's
frozen questions, the qset P1/P2 items, and the confirm and stage-0 cards' g_block / t_block. A window counts when it
holds a CJK character (test_gen_confirm_ho_edges' scan, whose frozen file is not edited). Store-backed: skips when
the store is not mounted. A failure names file, line and the window's sha256, never the text.
"""
from __future__ import annotations

import ast
import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STORE = Path("/mnt/ollama-data/bible_rag_store")
REPORTS = STORE / "reports"
VERSES = STORE / "layers/text/text@247eafe44b02/verse_units.jsonl"
WINDOW = 8
SCANNED = ("backend/utils/gen_card.py", "backend/tests/test_gen*.py", "ragdata/src/ragdata/**/gen*.py",
           "ragdata/tests/*gen*.py", "evaluation/experiments/2026-10-21_gen_card/**/*.py",
           "evaluation/tests/test_gen_card*.py", "docs/records/2026-10-21_gen_card*.md")
# sha256 of a shared window that is allowed: stage-0's GEN question template opens with this clause (its book named),
# a synthetic question may open the same way
ALLOWED = {"8bebbc80b51baab0e6ce75bab0139fc98eff1db773ca6d279ab4a951c046c16f": "stage-0 GEN template's opening clause"}

needs_store = pytest.mark.skipif(not VERSES.is_file(), reason="store not mounted")


def cjk(w: str) -> bool:
    return any("㐀" <= ch <= "鿿" for ch in w)


def windows(s: str) -> set[str]:
    return {s[i:i + WINDOW] for i in range(len(s) - WINDOW + 1) if cjk(s[i:i + WINDOW])}


def both(s: str) -> set[str]:
    return windows(s) | windows(unicodedata.normalize("NFKC", s))


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def scanned_files() -> list[Path]:
    return sorted({p for g in SCANNED for p in REPO.glob(g) if p.is_file()})


def file_windows(p: Path) -> dict[str, int]:
    """{window: the first line holding it} of one scanned file."""
    text, out = p.read_text(encoding="utf-8"), {}

    def add(ws: set[str], line: int) -> None:
        for w in ws:
            out.setdefault(w, line)
    for n, line in enumerate(text.splitlines(), 1):
        add(both(line), n)
    line = 1
    for i in range(len(text) - WINDOW + 1):        # windows across a line break, as written
        line += i > 0 and text[i - 1] == "\n"
        if cjk(text[i:i + WINDOW]):
            out.setdefault(text[i:i + WINDOW], line)
    if p.suffix == ".py":
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                add(both(node.value), node.lineno)
    return out


def real_texts() -> dict[str, list[str]]:
    gc, s0 = REPORTS / "gen_confirm_20261020", REPORTS / "arith_stage0_20261020"
    out = {"verses": [json.loads(x)["text"] for x in VERSES.read_text(encoding="utf-8").splitlines() if x.strip()]}
    for f in ("ground_truth.json", "ground_truth.v2.json"):
        out[f] = [q["question"] for q in read_json(REPO / f)["questions"]]
    a_confirm = REPORTS / "kg_cards_20261018/A_confirm/questions_frozen.json"
    out["A_confirm"] = [q["question"] for q in read_json(a_confirm)["questions"]]
    out["stage0_items"] = [it["question"] for it in read_json(s0 / "items.json")["items"]]
    out["gen_confirm"] = [q["question"] for q in read_json(gc / "questions_frozen.json")["questions"]]
    for s in ("p1", "p2"):
        out[f"qset_{s}"] = [it["question"] for it in read_json(gc / f"qset/{s}/items.json")["items"]]
    cards = [c for v in read_json(gc / "run/cards.json")["cards"].values() for c in (v["g"], v["gref"]) if c]
    cards += list(read_json(s0 / "cards.json")["cards"].values())
    out["cards"] = [c[k] for c in cards for k in ("g_block", "t_block") if c.get(k)]
    return out


def test_the_scan_covers_this_file_the_a4_folder_and_the_plan():
    files = {p.relative_to(REPO).as_posix() for p in scanned_files()}
    assert {"evaluation/tests/test_gen_card_windows.py", "evaluation/tests/test_gen_card_a4.py",
            "evaluation/experiments/2026-10-21_gen_card/a4_g.py", "evaluation/experiments/2026-10-21_gen_card/a4_score.py",
            "docs/records/2026-10-21_gen_card_integration_plan.md"} <= files


def test_windows_hold_a_cjk_character_and_see_through_nfkc():
    assert windows("abcdefgh") == set() and len(windows("甲乙丙丁戊己庚辛")) == 1
    assert both("ＡＢＣＤ甲乙丙丁") == {"ＡＢＣＤ甲乙丙丁", "ABCD甲乙丙丁"}


@needs_store
def test_gen_card_files_share_no_window_with_a_verse_a_real_question_or_a_real_card():
    texts = real_texts()
    real = set().union(*(both(t) for v in texts.values() for t in v))
    hits = sorted((p.relative_to(REPO).as_posix(), line, sha(w)) for p in scanned_files()
                  for w, line in file_windows(p).items() if w in real and sha(w) not in ALLOWED)
    sizes = {k: len(v) for k, v in texts.items()}
    assert sizes["verses"] > 31000 and min(sizes.values()) > 0, sizes
    assert sizes["gen_confirm"] == 58 and sizes["cards"] > 100, sizes
    assert hits == [], f"{len(hits)} shared 8-character windows (file, line, sha256): {hits[:20]}"
