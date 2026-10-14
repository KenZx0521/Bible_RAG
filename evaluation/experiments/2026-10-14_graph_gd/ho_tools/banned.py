"""§7 盲化 word checks: banned terms (prompts and transcripts) and project-memory markers.

* BANNED_TERMS (prompts and transcripts) = SPEC_TERMS, the §7 list (檢索、dense、reranker、
  圖譜、PPR、名稱圖) with the task's additions (embedding、向量、RAG、知識圖譜、KG), plus
  LEAK_TERMS, words an agent would only write after seeing this project (rerank、BM25、
  Qdrant、graph、vector、...). None of them occurs in the RCUV text layer, passage titles,
  GT v2 or OLD31 question texts (checked 2026-10-14; tests/test_graph_gd_ho_tools.py
  re-checks with the store), so a transcript hit is the agent's or the prompt's.
* PROMPT_ONLY_TERMS: words a prompt must not use but an agent may write innocently (an
  English Bash description such as "retrieve verses"), occur in Bible text (臂、召回), or are
  purpose words (實驗、對照、盲出、held-out).
* MEMORY_MARKERS: words that only appear in this project's memory, CLAUDE.md and paths
  (Kay、GD、prereg、Bible_RAG、NEW82、...). A transcript must contain none (§7 凍結前機械檢查).

ASCII terms match case-insensitively on word boundaries ("graph" does not match
"paragraph"); CJK terms match as substrings. CLI: `banned.py FILE ...` checks prompt
files against BANNED_TERMS + PROMPT_ONLY_TERMS + MEMORY_MARKERS; exit 1 on a hit, 2 on error.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

__all__ = ["SPEC_TERMS", "LEAK_TERMS", "BANNED_TERMS", "PROMPT_ONLY_TERMS", "MEMORY_MARKERS", "PROMPT_TERMS", "Hit",
           "find_terms", "check_prompt_text", "check_prompt_file", "main"]

SPEC_TERMS = ("檢索", "dense", "reranker", "圖譜", "PPR", "名稱圖", "embedding", "向量", "RAG",
              "知識圖譜", "KG")
LEAK_TERMS = ("rerank", "語意搜尋", "語義搜尋", "語意相似", "graph", "vector", "BM25", "Qdrant",
              "PageRank", "knowledge graph", "cosine")
BANNED_TERMS = SPEC_TERMS + LEAK_TERMS
PROMPT_ONLY_TERMS = ("retrieval", "retrieve", "retriever", "重排", "嵌入", "實驗", "對照", "盲出",
                     "held-out", "heldout", "臂", "召回", "評測", "基準")
MEMORY_MARKERS = (
    "Kay", "GD", "prereg", "Bible_RAG", "Bible-RAG", "bible_rag", "NEW82", "OLD31", "OLD38",
    "graph_gd", "multihop_kg", "MEMORY.md", "CLAUDE.md", "事前登記", "附錄 A", "附錄 B",
    "chainsea", "kenzx0521", "GT v2", "ground_truth", "LEXPRF", "DEGNORM")
PROMPT_TERMS = BANNED_TERMS + PROMPT_ONLY_TERMS + MEMORY_MARKERS


@dataclass(frozen=True)
class Hit:
    term: str
    where: str          # caller's label (file, event path)
    excerpt: str        # up to 20 characters either side


def _pattern(term: str) -> re.Pattern[str]:
    if term.isascii():
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)
    return re.compile(re.escape(term))


_COMPILED: dict[str, re.Pattern[str]] = {}


def find_terms(text: str, terms: Iterable[str], where: str = "") -> list[Hit]:
    """Every occurrence of every term in `text`, in term order then position."""
    hits = []
    for term in terms:
        pat = _COMPILED.setdefault(term, _pattern(term))
        for m in pat.finditer(text):
            lo, hi = max(m.start() - 20, 0), min(m.end() + 20, len(text))
            hits.append(Hit(term, where, text[lo:hi].replace("\n", " ")))
    return hits


def check_prompt_text(text: str, where: str = "prompt") -> list[Hit]:
    """Prompt check: banned, purpose and memory words (§7: the prompt must name none)."""
    return find_terms(text, PROMPT_TERMS, where)


def check_prompt_file(path: Path | str) -> list[Hit]:
    return check_prompt_text(Path(path).read_text(encoding="utf-8"), str(path))


def main(argv: Sequence[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print("banned.py: usage: banned.py FILE ...", file=sys.stderr)
        return 2
    try:
        hits = [h for p in paths for h in check_prompt_file(p)]
    except OSError as err:
        print(f"banned.py: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    for h in hits:
        print(f"{h.where}: {h.term!r} in …{h.excerpt}…")
    print(f"banned.py: {len(hits)} hit(s) in {len(paths)} file(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
