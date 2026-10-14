"""The §7 Kay 抽查 review page: annotated questions injected into page_template.html.

Copy of E7/newq/build_page.py with the template read from this directory (not /tmp). The
page is only written as a file here; publishing it is a separate decision. Every question
must already carry annotate.py's keys (hops with verse text, n_hops, books, ...).

    build_page.py QUESTIONS.json OUT.html     QUESTIONS: {"questions": [...]} (annotated)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import PAGE_TEMPLATE, HoToolError  # first: sets sys.path

import annotate  # noqa: E402

__all__ = ["KEEP", "DATA_SLOT", "page_html", "write_page", "main"]

DATA_SLOT = "/*__DATA__*/null"
KEEP = ("id", "category", "subtype", "core", "question", "answer", "key_points", "hops", "n_hops",
        "books", "cross_book", "needs_identity_resolution", "status", "change_log", "reject_reason",
        "why_multihop", "bridge", "shortcut_search", "notes", "auto_warnings", "dedup_drop", "flags",
        "audit")


def page_html(questions: Sequence[Mapping[str, Any]], template: Path = PAGE_TEMPLATE,
              sample_note: str = "") -> str:
    """The template with the questions as its DATA (`</` escaped for the inline script)."""
    missing = [q.get("id") for q in questions if any(k not in q for k in annotate.ANNOTATED_KEYS)]
    if missing:
        raise HoToolError(f"questions not annotated: {missing}")
    data = {"questions": [{k: q.get(k) for k in KEEP} for q in questions], "concerns": [],
            "sample_note": sample_note}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    tpl = Path(template).read_text(encoding="utf-8")
    if tpl.count(DATA_SLOT) != 1:
        raise HoToolError(f"{template}: needs exactly one {DATA_SLOT}")
    return tpl.replace(DATA_SLOT, payload)


def write_page(questions: Sequence[Mapping[str, Any]], out: Path, sample_note: str = "") -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(page_html(questions, sample_note=sample_note), encoding="utf-8")
    return Path(out)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("build_page.py: usage: build_page.py QUESTIONS.json OUT.html", file=sys.stderr)
        return 2
    try:
        out = write_page(annotate.load_items(Path(args[0])), Path(args[1]))
    except (HoToolError, OSError, ValueError) as err:
        print(f"build_page.py: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    print(f"build_page.py: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
