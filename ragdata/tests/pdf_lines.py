"""Synthetic S1 rows for parser unit tests: lines of styled glyphs on a page.

A run is ``(style, text, x0)``; glyphs advance by the font size (half for ASCII),
so a test can place a verse number, body text or a footnote the way the real
PDFs set them without opening a PDF.
"""

from __future__ import annotations

NAVY, BLACK, BLUE = "#000080", "#000000", "#0000ff"
VNUM = ("NotoSerif-Regular", 8.97, NAVY)
BODY = ("NotoSansCJKjp-Regular", 11.96, BLACK)
BODY2 = ("BitstreamCyberbit-Roman", 11.96, BLACK)
HEAD = ("NotoSansCJKjp-Regular", 11.96, NAVY)
HEAD2 = ("BitstreamCyberbit-Roman", 11.96, NAVY)
ITALIC = ("NotoSerif-Italic", 11.96, NAVY)
NOTE = ("NotoSansCJKjp-Regular", 8.97, NAVY)
NOTE_REF = ("NotoSerif-ExtraBold", 8.97, NAVY)
CHAPTER = ("NotoSerif-ExtraBold", 17.93, BLACK)
TITLE = ("NotoSansCJKjp-Black", 17.93, BLACK)
DIVISION = ("NotoSansCJKjp-Black", 15.94, NAVY)
HEADER = ("NotoSansCJKjp-Regular", 7.97, BLUE)
COLOPHON = ("NotoSansCJKjp-Black", 11.96, NAVY)
SMALL = ("NotoSerif-Regular", 7.97, NAVY)
ODD = ("NotoSerif-Italic", 10.0, BLACK)

PAGE_BOUNDS = [0, 0, 419.53, 595.28]


def glyphs(style, text: str, x0: float, y: float) -> list[list]:
    font, size, color = style
    out, x = [], x0
    for c in text:
        adv = size if ord(c) > 127 else size / 2
        out.append([c, round(x, 2), round(x + adv, 2), y, font, size, color])
        x += adv
    return out


def line(page: int, y: float, *runs) -> dict:
    chars = [g for style, text, x0 in runs for g in glyphs(style, text, x0, y)]
    return {"k": "line", "p": page, "chars": chars}


def s1_lines(rows) -> list:
    """S1 lines of ``line`` rows, glyphs numbered in order as ``s01_extract`` numbers them."""
    from ragdata.stages import layout
    lines, seq = [], 0
    for r in rows:
        if r["k"] == "line":
            lines.append(layout.to_line(r["p"], r["chars"], seq))
            seq += len(r["chars"])
    return lines


def page(p: int) -> dict:
    return {"k": "page", "p": p, "bounds": list(PAGE_BOUNDS)}


def stroke(p: int, x0: float, x1: float, y: float) -> dict:
    return {"k": "stroke", "p": p, "lw": 0.3985, "path": [["m", x0, y], ["l", x1, y]]}


def verse(p: int, y: float, number: str, text: str, x: float = 82.8) -> dict:
    return line(p, y, (VNUM, number, x), (BODY, " " + text, x + 8))


def body(p: int, y: float, text: str, x: float = 70.87) -> dict:
    return line(p, y, (BODY, text, x))


def colophon_page(p: int) -> list[dict]:
    return [page(p), line(p, 82.83, (HEADER, "viii", 203.6)),
            line(p, 106.7, (COLOPHON, "新標點和合本", 173.9)),
            line(p, 128.4, (SMALL, "Public Domain", 70.87)),
            line(p, 212.6, (SMALL, "c03bb35c-f042-59c2-88d7-1111d9a01842", 70.87))]
