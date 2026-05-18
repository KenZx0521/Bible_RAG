#!/usr/bin/env python3
"""Apply the Fig. 1 redraw + token-count fix to biblerag.docx.

Two surgical edits, pure stdlib (python-docx is not installed):
  A. word/media/image1.png  <-  figures/fig1_architecture.png  (new TikZ figure)
  B. word/document.xml      "512-1024" -> "512-768"  (chunk-token range fix)

The drawing's <wp:extent> is left byte-for-byte unchanged, so the figure keeps
the exact same display box and the document stays 2 pages. Idempotent / re-runnable.

Usage:  python3 figures/apply_docx_changes.py
Rollback:  git checkout -- biblerag.docx   (or restore biblerag.docx.bak)
"""
import os
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCX = os.path.join(ROOT, "biblerag.docx")
BACKUP = DOCX + ".bak"
NEW_PNG = os.path.join(ROOT, "figures", "fig1_architecture.png")

IMG_ENTRY = "word/media/image1.png"
XML_ENTRY = "word/document.xml"

OLD_TEXT = "512–1024"      # "512-1024", U+2013 en-dash
NEW_TEXT = "512–768"       # "512-768"
GUARD = "(1024-dim)"            # same <w:t> run holds this -- must NOT be touched
EXTENT_KEY = 'cx="3234690"'     # figure extent EMU -- count must stay unchanged


def fail(msg):
    sys.exit("ERROR: " + msg)


def png_size(data):
    """Return (width, height) parsed from a PNG IHDR chunk."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail("new figure is not a valid PNG")
    return struct.unpack(">II", data[16:24])


def main():
    if not os.path.isfile(DOCX):
        fail(f"{DOCX} not found")
    if not os.path.isfile(NEW_PNG):
        fail(f"{NEW_PNG} not found -- compile fig1_architecture.tex first")

    # --- aspect-ratio guard: a mismatched aspect would distort the figure,
    #     because <wp:extent> (the display box) is intentionally left fixed ---
    with open(NEW_PNG, "rb") as fh:
        new_png = fh.read()
    nw, nh = png_size(new_png)
    aspect, target = nw / nh, 3234690 / 2125980
    if abs(aspect - target) > 0.01:
        fail(f"figure aspect {aspect:.5f} != docx box {target:.5f} "
             "-- would be distorted; fix the .tex canvas size")

    # --- backup (keep the first, pristine copy across re-runs) ---
    if os.path.exists(BACKUP):
        print(f"backup    : {BACKUP} already exists -- kept")
    else:
        shutil.copy2(DOCX, BACKUP)
        print(f"backup    : {os.path.basename(DOCX)} -> {os.path.basename(BACKUP)}")

    # --- read every entry, preserving order + per-entry ZipInfo metadata ---
    with zipfile.ZipFile(DOCX, "r") as zin:
        infos = zin.infolist()
        data = {zi.filename: zin.read(zi.filename) for zi in infos}
    names = [zi.filename for zi in infos]
    for need in (IMG_ENTRY, XML_ENTRY):
        if need not in data:
            fail(f"{need} not present in docx")

    extent_before = data[XML_ENTRY].decode("utf-8").count(EXTENT_KEY)

    # --- edit A: swap the figure image (same entry name -> rId5 stays valid) ---
    data[IMG_ENTRY] = new_png
    print(f"image     : {IMG_ENTRY} <- fig1_architecture.png "
          f"({len(new_png)} bytes, {nw}x{nh})")

    # --- edit B: fix the chunk-token range; replace the full 8-char key only,
    #     never bare '1024' -- the same run also holds the correct '(1024-dim)' ---
    doc = data[XML_ENTRY].decode("utf-8")
    n = doc.count(OLD_TEXT)
    if n == 1:
        if GUARD not in doc:
            fail(f"guard text {GUARD!r} missing -- aborting to avoid damage")
        data[XML_ENTRY] = doc.replace(OLD_TEXT, NEW_TEXT).encode("utf-8")
        print(f"text      : {OLD_TEXT!r} -> {NEW_TEXT!r}")
    elif n == 0 and NEW_TEXT in doc:
        print(f"text      : already {NEW_TEXT!r} -- skipped (idempotent)")
    else:
        fail(f"expected exactly one {OLD_TEXT!r}, found {n}")

    # --- rewrite the zip in the original entry order ---
    with zipfile.ZipFile(DOCX, "w") as zout:
        for zi in infos:
            zout.writestr(zi, data[zi.filename])
    print(f"rewrote   : {os.path.basename(DOCX)} ({len(infos)} entries)")

    # --- verification ---
    with zipfile.ZipFile(DOCX, "r") as z:
        broken = z.testzip()
        if broken is not None:
            fail(f"corrupt entry after rewrite: {broken}")
        if z.namelist() != names:
            fail("entry set or order changed")
        xml_bytes = z.read(XML_ENTRY)
        img_bytes = z.read(IMG_ENTRY)
    try:
        ET.fromstring(xml_bytes)            # bytes input handles the <?xml?> decl
    except ET.ParseError as exc:
        fail(f"document.xml malformed after edit: {exc}")
    doc2 = xml_bytes.decode("utf-8")
    checks = {
        "new text '512-768' present": NEW_TEXT in doc2,
        "old text '512-1024' gone": OLD_TEXT not in doc2,
        "'(1024-dim)' still intact": GUARD in doc2,
        "figure extent unchanged": doc2.count(EXTENT_KEY) == extent_before,
        "image swapped": png_size(img_bytes) == (nw, nh),
    }
    for label, ok in checks.items():
        print(f"  check   : {'OK  ' if ok else 'FAIL'}- {label}")
    if not all(checks.values()):
        fail("verification failed")

    print("\nDONE -- biblerag.docx updated (Fig. 1 + token-count text).")
    print("Page count stays 2 by construction: <wp:extent> unchanged and the")
    print("text edit is 1 char shorter. Confirm visually by opening it in Word.")


if __name__ == "__main__":
    main()
