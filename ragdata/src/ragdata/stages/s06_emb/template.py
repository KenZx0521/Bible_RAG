"""Embedding text templates (design §6, decision D-11(a)).

v1c keeps the old format strings word for word — passage and chunk as
bible_chunking/hierarchical_chunker.py wrote them, verse as
scripts/process_bible.py did — and fixes only the values filled in (``RULES``).
Records are rendered from the declared strings themselves, so the declaration
the layer stores is the template that made its texts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

UNTITLED_GAP = " {標題}"


@dataclass(frozen=True)
class Template:
    template_id: str
    passage: str                 # also the chunk format
    verse: str
    rules: tuple[str, ...]

    def declaration(self) -> dict[str, Any]:
        """What the layer stores to declare its template (emb_report.json)."""
        return {"template_id": self.template_id,
                "formats": {"passage": self.passage, "chunk": self.passage, "verse": self.verse},
                "untitled": f"a pericope without a heading leaves {UNTITLED_GAP!r} out",
                "rules": list(self.rules)}

    def render_passage(self, book_name: str, chapter: int, title: str | None,
                       verse_range: str, bodies: Iterable[str]) -> str:
        return _format(self.passage, title, 書名=book_name, 章=chapter,
                       verse_range=verse_range, content=" ".join(bodies))

    def render_verse(self, book_name: str, chapter: int, title: str | None, label: str,
                     verse_text: str) -> str:
        return _format(self.verse, title, 書名=book_name, 章=chapter, n=label, 經文=verse_text)


def _format(fmt: str, title: str | None, **values: Any) -> str:
    if title:
        return fmt.format(標題=title, **values)
    return fmt.replace(UNTITLED_GAP, "", 1).format(**values)


V1C = Template(
    template_id="v1c",
    passage="{書名} 第{章}章 {標題} ({verse_range}節)：{content}",
    verse="{書名} 第{章}章 {標題} 第{n}節：{經文}",
    rules=(
        "書名: the book's PDF title line (尼希米記)",
        "標題: the passage title; a continued passage inherits it, a － sub-heading carries "
        "its parent; a verse takes the title of the passage owning it (a unit cut by a "
        "mid-verse heading: the earlier passage)",
        "content: the block texts joined by one space: the superscription (in the passage "
        "opening its chapter), speaker labels, verse texts with their printed poetry lines",
        "經文: the unit's service text with its printed poetry lines, no speaker label; "
        "a merged unit once, n = its label (2-3)",
    ),
)
TEMPLATES = {V1C.template_id: V1C}
