"""
Parse bible_md/*.md files into structured pericope data.

Each markdown follows:
  # BookName
  ## 第 N 章
  ### Pericope Title
  **verse_num** verse text ...
"""

import re
import sys
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Ensure project root is on sys.path so we can import bible_chunking.config
# when this module is invoked directly (e.g. from scripts/extract_entities.py).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bible_chunking.config import BOOK_CONFIG

logger = logging.getLogger(__name__)

# Book name (Traditional Chinese) → book_id (three-letter abbrev used by Neo4j)
_BOOK_NAME_TO_ID: dict[str, str] = {
    name: meta["id"] for name, meta in BOOK_CONFIG.items()
}

# Authoritative pericope lookup loaded lazily from output/pericopes.jsonl
# (produced by scripts/process_bible.py). Maps (book_id, chapter, title)
# to the Neo4j-compatible pericope id. We delegate to this map rather than
# re-implementing bible_chunking.markdown_parser's pericope numbering rules
# (Selah / cross-ref skip, implicit "(無標題)" at chapter head, etc.) which
# are non-trivial to keep in sync.
_PERICOPE_LOOKUP: dict[tuple[str, int, str], list[str]] | None = None
_PERICOPE_LOOKUP_PATH = _PROJECT_ROOT / "output" / "pericopes.jsonl"


def _load_pericope_lookup() -> dict[tuple[str, int, str], list[str]]:
    """Load pericopes.jsonl and build (book_id, chapter, title) → [pericope_id, ...] map.

    Values are lists to preserve duplicate titles in the same chapter
    (e.g., psa:119 has a few repeated section titles). Callers should
    pop the first remaining id to preserve source order.
    """
    global _PERICOPE_LOOKUP
    if _PERICOPE_LOOKUP is not None:
        return _PERICOPE_LOOKUP
    lookup: dict[tuple[str, int, str], list[str]] = {}
    if not _PERICOPE_LOOKUP_PATH.exists():
        logger.warning(
            f"Authoritative pericope file not found: {_PERICOPE_LOOKUP_PATH}. "
            f"source_id will fall back to legacy book:chapter:title format. "
            f"Run scripts/process_bible.py first to regenerate it."
        )
        _PERICOPE_LOOKUP = lookup
        return lookup
    with open(_PERICOPE_LOOKUP_PATH, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            meta = d.get("metadata", {})
            key = (meta.get("book_id", ""), meta.get("chapter_num", 0), d.get("title", ""))
            lookup.setdefault(key, []).append(d["id"])
    _PERICOPE_LOOKUP = lookup
    logger.info(f"Loaded {sum(len(v) for v in lookup.values())} authoritative pericope ids")
    return lookup

# Regex patterns
RE_BOOK = re.compile(r"^# (.+)$")
RE_CHAPTER = re.compile(r"^## 第 (\d+) 章$")
RE_PERICOPE = re.compile(r"^### (.+)$")
RE_VERSE = re.compile(r"^\*\*(\d+)\*\* (.+)$")
# Selah marker: 詩篇/哈巴谷書的音樂停頓記號,不是 pericope title
# 對齊 bible_chunking/markdown_parser.py:89 SELAH_PATTERN
RE_SELAH = re.compile(r"^（細拉）$")
# Closed parenthesised title — cross-reference / parallel-passage label.
# 對齊 bible_chunking/markdown_parser.py:88 CROSS_REF_PATTERN (「^（.+）$」)
# Note: unclosed cross-refs (e.g. "（可14‧12－21；路22‧...；約") are *not*
# matched here — they get promoted to real pericopes with the truncated
# string as title, same as markdown_parser does. These titles appear
# verbatim in output/pericopes.jsonl so the authoritative lookup resolves.
RE_CROSS_REF_TITLE = re.compile(r"^（.+）$")
RE_FOOTNOTE_SEP = re.compile(r"^---$")


@dataclass
class PericopeData:
    """Structured pericope parsed from bible_md."""
    book: str
    chapter: int
    title: str
    book_id: str = ""
    verses: List[str] = field(default_factory=list)
    verse_numbers: List[int] = field(default_factory=list)
    source_id: str = ""

    @property
    def full_text(self) -> str:
        return " ".join(self.verses)


def _finalize(
    current: PericopeData | None,
    pericopes: List[PericopeData],
    local_lookup: dict[tuple[str, int, str], list[str]],
    book: str,
    book_id: str,
) -> None:
    """Append `current` to `pericopes` iff it has verses, resolving its source_id
    from the authoritative lookup at this point (so no-verse rejected pericopes
    never consume a lookup slot nor emit a warning)."""
    if not (current and current.verses):
        return
    key = (book_id, current.chapter, current.title)
    ids = local_lookup.get(key)
    if ids:
        current.source_id = ids.pop(0)
    else:
        if book_id:
            logger.warning(
                f"Pericope not found in authoritative table: "
                f"book_id={book_id}, chapter={current.chapter}, title={current.title!r} — "
                f"using legacy format for source_id"
            )
        current.source_id = f"{book if not book_id else book_id}:{current.chapter}:{current.title}"
    pericopes.append(current)


def parse_bible_md(md_path: Path) -> List[PericopeData]:
    """Parse a single bible_md markdown file into PericopeData list.

    The emitted source_id follows Neo4j Pericope id scheme (e.g. "gen:2:1").
    Resolution strategy:
      1. Look up (book_id, chapter, title) in the authoritative pericope
         table (loaded from output/pericopes.jsonl) at *finalize time* — i.e.
         only for pericopes that collected at least one verse.
      2. If an entry exists, take the first remaining id (duplicates in the
         same chapter are resolved in source order).
      3. If no entry, fall back to the legacy "{book}:{chapter}:{title}"
         format and log a warning.

    Cross-reference lines (parenthesised, e.g. `（太26‧17－25；...）`),
    Selah markers, and unclosed cross-ref tails are skipped to stay aligned
    with bible_chunking/markdown_parser.py's behavior.
    """
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    lookup = _load_pericope_lookup()
    # Per-call copy of the lookup so we can pop ids as we consume them;
    # this preserves ordering for duplicate titles within a chapter.
    local_lookup: dict[tuple[str, int, str], list[str]] = {
        k: list(v) for k, v in lookup.items()
    }

    pericopes: List[PericopeData] = []
    book = ""
    book_id = ""
    chapter = 0
    current: PericopeData | None = None
    in_footnote = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Footnote separator: skip everything until next heading
        if RE_FOOTNOTE_SEP.match(stripped):
            in_footnote = True
            continue

        # Book title
        m = RE_BOOK.match(stripped)
        if m:
            book = m.group(1)
            book_id = _BOOK_NAME_TO_ID.get(book, "")
            if not book_id:
                logger.warning(
                    f"Unknown book name '{book}' — BOOK_CONFIG missing entry; "
                    f"source_id will fall back to legacy format"
                )
            in_footnote = False
            continue

        # Chapter heading
        m = RE_CHAPTER.match(stripped)
        if m:
            # Finalize any open pericope before the chapter boundary.
            _finalize(current, pericopes, local_lookup, book, book_id)
            current = None
            chapter = int(m.group(1))
            in_footnote = False
            continue

        # Pericope heading
        m = RE_PERICOPE.match(stripped)
        if m:
            in_footnote = False
            title = m.group(1).strip()
            # Skip musical markers and closed parenthesised cross-references.
            # Unclosed cross-refs are *kept* and promoted to real pericopes
            # (matches markdown_parser.py output, so pericopes.jsonl resolves).
            if RE_SELAH.match(title) or RE_CROSS_REF_TITLE.match(title):
                continue
            # Finalize previous pericope (will only be appended if it had verses).
            _finalize(current, pericopes, local_lookup, book, book_id)
            current = PericopeData(
                book=book,
                book_id=book_id,
                chapter=chapter,
                title=title,
                source_id="",  # resolved lazily in _finalize
            )
            continue

        if in_footnote:
            continue

        # Verse
        m = RE_VERSE.match(stripped)
        if m and current is not None:
            vnum = int(m.group(1))
            vtext = m.group(2)
            current.verse_numbers.append(vnum)
            current.verses.append(vtext)

    # Don't forget last pericope
    _finalize(current, pericopes, local_lookup, book, book_id)

    return pericopes


def parse_all_bible_md(bible_md_dir: Path) -> List[PericopeData]:
    """Parse all 66 bible_md markdown files."""
    all_pericopes: List[PericopeData] = []
    md_files = sorted(bible_md_dir.glob("*.md"))

    if not md_files:
        logger.warning(f"No .md files found in {bible_md_dir}")
        return all_pericopes

    for md_file in md_files:
        pericopes = parse_bible_md(md_file)
        all_pericopes.extend(pericopes)
        logger.debug(f"Parsed {md_file.name}: {len(pericopes)} pericopes")

    logger.info(f"Parsed {len(md_files)} books, {len(all_pericopes)} total pericopes")
    return all_pericopes
