"""R2/R5 chapter scope (B-lite): a named chapter served whole, as one block.

「書 a-b 章」 used to read only chapter a (utils.verse_parser), and a named chapter
kept only the chapter pin's two passages. On R2 and R5, a chapter-only reference
spanning at most ``MAX_CHAPTERS`` chapters is now served as one block per chapter,
pinned ahead of the ranked passages and never reranked, when either holds:

- the reference is a chapter range (two or three chapters);
- a chapter it names has a passage the finished top-k lacks.

Otherwise the top-k stays exactly what it was. When it fires, every chapter of
those references becomes a block (at most k); the remaining slots are ranked and
pinned again over the pool without the blocked chapters, and the blocks count as
present books for the book-anchor gate.

- A longer range keeps the old behaviour (its first chapter, pinned): the point of
  「出 7-12、士 13-16」 often sits late, so its first three chapters would not do.
- A chapter over ``MAX_CHARS`` characters is no block: its passages compete as
  sql_chapter at weight 1.0 (what the chapter lookup's candidates carry; a dense
  copy already in the pool is raised to it) and the chapter pin keeps two of them,
  also when no chapter of the reference fits a block.
- Chapters past k get nothing (two 3-chapter ranges at k=5: the sixth); no
  question in GT v2 names more than k.
- No block spans chapters: the generator's header names one chapter, and every
  passage is one chapter (design §2.23).

A block's id is its chapter key (``rom.8``, ragcommon.ids kind chapter), its kind
``chapter``, and ``member_ids`` lists its passages in canonical order. A ``vr:`` id
could not name it, since a chapter may end on a half-verse key (``1co.12.31b``).
Its text is each passage under its 【title】; the header carries no title, only the
chapter and the verse span its passages cover.

R1 (which reads chapter-only references through verse_retriever too) and
semantic_only never get here (router).
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ragcommon import ids
from utils.verse_parser import VerseRef

KIND = "chapter"
SOURCE = "chapter_block"
MAX_CHAPTERS = 3
MAX_CHARS = 4000
FALLBACK_WEIGHT = 1.0     # sql_chapter's effective weight (verse_retriever gives 1.0)

Chapter = tuple[str, int]


def _last_chapter(ref: VerseRef) -> int:
    return ref.chapter if ref.chapter_end is None else ref.chapter_end


def scoped_refs(verse_refs: Iterable[VerseRef]) -> list[VerseRef]:
    """Chapter-only references spanning at most MAX_CHAPTERS chapters."""
    return [r for r in verse_refs
            if r.verse_start is None and _last_chapter(r) - r.chapter < MAX_CHAPTERS]


def scoped_chapters(verse_refs: Iterable[VerseRef], k: int) -> list[Chapter]:
    """Every chapter of the scoped references, in the order written, at most ``k``."""
    chapters = ((r.book_id, ch) for r in scoped_refs(verse_refs)
                for ch in range(r.chapter, _last_chapter(r) + 1))
    return list(dict.fromkeys(chapters))[:max(k, 0)]


def triggered(verse_refs: Iterable[VerseRef], ranked: list[dict],
              passages: Mapping[Chapter, list[dict]]) -> bool:
    """A scoped chapter range, or a scoped single chapter with a passage ``ranked`` lacks."""
    present = {c["id"] for c in ranked}
    for ref in scoped_refs(verse_refs):
        if ref.chapter_end is not None:
            return True
        if any(p["id"] not in present for p in passages.get((ref.book_id, ref.chapter), ())):
            return True
    return False


def _text(p: dict) -> str:
    return f"【{p['title']}】\n{p['content']}" if p.get("title") else p["content"]


def block(passages: list[dict]) -> dict:
    """One chapter's passages (canonical order, at least one) as one candidate."""
    first, last = passages[0], passages[-1]
    v_first = ids.validate(first["start_key"], "key").verse
    v_last = ids.validate(last["end_key"], "key").verse
    return {"id": ids.chapter_key(first["book_id"], first["chapter_num"]), "kind": KIND,
            "content": "\n\n".join(_text(p) for p in passages), "title": "",
            "book_id": first["book_id"], "book_name": first["book_name"],
            "chapter_num": first["chapter_num"],
            "verse_range": str(v_first) if v_first == v_last else f"{v_first}-{v_last}",
            "start_key": first["start_key"], "end_key": last["end_key"], "passage_id": None,
            "split_passage_ids": [], "member_ids": [p["id"] for p in passages],
            "source_strategy": SOURCE, "weight": 1.0, "found_by": [SOURCE]}


def plan(passages: Mapping[Chapter, list[dict]]) -> tuple[list[dict], list[Chapter]]:
    """The blocks, in ``passages`` order, and the chapters too long for one."""
    blocks, too_long = [], []
    for chapter, found in passages.items():
        if not found:
            continue
        b = block(found)
        if len(b["content"]) <= MAX_CHARS:
            blocks.append(b)
        else:
            too_long.append(chapter)
    return blocks, too_long


def with_fallbacks(pool: list[dict], too_long: Iterable[Chapter],
                   passages: Mapping[Chapter, list[dict]]) -> list[dict]:
    """``pool`` with every passage of the chapters too long for a block as sql_chapter at
    FALLBACK_WEIGHT, so the chapter pin can pick it: a copy already in the pool (dense,
    weight below the pin floor) is raised in place, found_by kept; the rest are appended."""
    have = {c["id"]: c for c in pool}
    raised: dict[str, dict] = {}
    for chapter in too_long:
        for p in passages[chapter]:
            old = have.get(p["id"], p)
            found = [*(old.get("found_by") or []), "sql_chapter"] if p["id"] in have \
                else ["sql_chapter"]
            raised[p["id"]] = {**old, "source_strategy": "sql_chapter",
                               "weight": max(old.get("weight") or 0.0, FALLBACK_WEIGHT),
                               "found_by": list(dict.fromkeys(found))}
    kept = [raised.pop(c["id"], c) for c in pool]
    return kept + list(raised.values())


def pin_targets(verse_refs: Iterable[VerseRef], blocked: set[Chapter],
                too_long: Iterable[Chapter]) -> list[Chapter]:
    """Chapters the chapter pin still serves once blocks are in, in the order written.

    Each chapter-only reference's first chapter (what the pin served before), and
    each chapter too long for a block; never a blocked chapter.
    """
    long = set(too_long)
    out: list[Chapter] = []
    for ref in verse_refs:
        if ref.verse_start is None:
            later = ((ref.book_id, c) for c in range(ref.chapter + 1, _last_chapter(ref) + 1))
            out += [(ref.book_id, ref.chapter), *(ch for ch in later if ch in long)]
    return [ch for ch in dict.fromkeys(out) if ch not in blocked]


def present_books(blocks: Iterable[dict]) -> list[str]:
    return list(dict.fromkeys(b["book_id"] for b in blocks))
