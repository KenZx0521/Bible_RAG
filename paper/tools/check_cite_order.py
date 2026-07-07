#!/usr/bin/env python3
"""Verify that refs.tex \bibitem order == first-citation order in the paper.

Reads main.tex to get the \input order, scans each section file for \cite
keys in document order, then compares with the \bibitem order in refs.tex.
Exits non-zero (and prints a corrected ordering) on mismatch, so it can be
used as a check in a verification loop.
"""
import re
import sys
from pathlib import Path

LATEX_DIR = Path(__file__).resolve().parent.parent / "latex"


def input_order(main_path: Path) -> list[Path]:
    order = []
    for line in main_path.read_text().splitlines():
        line = line.split("%")[0]
        for m in re.finditer(r"\\input\{([^}]+)\}", line):
            name = m.group(1)
            if not name.endswith(".tex"):
                name += ".tex"
            order.append(LATEX_DIR / name)
    return order


def strip_comments(tex: str) -> str:
    # remove LaTeX comments (unescaped %) line by line
    out = []
    for line in tex.splitlines():
        s = re.sub(r"(?<!\\)%.*", "", line)
        out.append(s)
    return "\n".join(out)


def cites_in_order(files: list[Path]) -> list[str]:
    seen: list[str] = []
    for f in files:
        if f.name == "refs.tex":
            continue
        text = strip_comments(f.read_text())
        for m in re.finditer(r"\\cite\{([^}]+)\}", text):
            for key in m.group(1).split(","):
                key = key.strip()
                if key and key not in seen:
                    seen.append(key)
    return seen


def bibitems(refs_path: Path) -> list[str]:
    text = strip_comments(refs_path.read_text())
    return re.findall(r"\\bibitem\{([^}]+)\}", text)


def main() -> int:
    files = input_order(LATEX_DIR / "main.tex")
    cite_order = cites_in_order(files)
    bib_order = bibitems(LATEX_DIR / "refs.tex")

    ok = True
    missing = [k for k in cite_order if k not in bib_order]
    unused = [k for k in bib_order if k not in cite_order]
    if missing:
        ok = False
        print("CITED BUT NOT IN refs.tex:", missing)
    if unused:
        ok = False
        print("IN refs.tex BUT NEVER CITED:", unused)

    common_bib = [k for k in bib_order if k in cite_order]
    if common_bib != cite_order:
        ok = False
        print("ORDER MISMATCH.")
        print("first-citation order:")
        for i, k in enumerate(cite_order, 1):
            mark = "" if i - 1 < len(common_bib) and common_bib[i - 1] == k else "   <-- differs"
            print(f"  [{i:2d}] {k}{mark}")
    else:
        print(f"Order OK: {len(cite_order)} cited keys match bibliography order.")
    print(f"(cited: {len(cite_order)}, bibitems: {len(bib_order)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
