#!/usr/bin/env python3
"""將 bible_pdf/ 中的 66 個聖經書卷 PDF 轉換為 Markdown 格式。"""

import os
import re
import fitz  # PyMuPDF

INPUT_DIR = "/home/kenzx0521/project/Senior/bible_pdf"
OUTPUT_DIR = "/home/kenzx0521/project/Senior/bible_md"

# Thresholds
HEADER_FOOTER_SIZE = 8.5  # size <= this is header/footer
TITLE_SIZE = 16.0         # size >= this is book title or chapter number
SECTION_HEADER_X = 85.0   # x >= this for section headers (size=12)
VERSE_NUM_SIZE = 9.5      # size <= this and is digit = verse number
PROSE_VERSE_X = 75.0      # verse number x > this = prose
POETRY_RIGHT_EDGE = 300.0 # poetry lines end before this x position
FOOTNOTE_PATTERN = re.compile(r'^\d+:\d+:?$')
VERSE_NUM_PATTERN = re.compile(r'^(\d+)(?:\s*[-–]\s*\d+)?$')  # matches "1", "29-30", "10–11"


def _get_line_right_edge(spans):
    """計算行文字的右邊界位置。"""
    if not spans:
        return 0
    last = spans[-1]
    x = last['origin'][0]
    text = last['text']
    size = last['size']
    width = 0
    for ch in text:
        if ord(ch) > 0x2000:  # CJK characters
            width += size
        else:
            width += size * 0.5
    return x + width


def is_version_page(page):
    """檢查是否為版本資訊頁（最後一頁）。"""
    blocks = page.get_text('dict')['blocks']
    for b in blocks:
        if 'lines' in b:
            for line in b['lines']:
                for span in line['spans']:
                    if '新標點和合本' in span['text'] or 'Chinese Union Version' in span['text']:
                        return True
    return False


def extract_page_data(page):
    """從頁面提取結構化資料，合併同一行的 spans，返回 line 列表。"""
    blocks = page.get_text('dict')['blocks']
    raw_lines = []
    for b in blocks:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            spans = line['spans']
            if not spans:
                continue
            raw_lines.append(spans)

    # Merge lines at similar y-positions (within 4pt tolerance)
    if not raw_lines:
        return []

    merged = []
    current_spans = list(raw_lines[0])
    current_y = raw_lines[0][0]['origin'][1]

    for spans in raw_lines[1:]:
        y = spans[0]['origin'][1]
        if abs(y - current_y) < 4.0:
            # Same visual line - merge spans sorted by x position
            current_spans.extend(spans)
        else:
            # Sort current spans by x position and save
            current_spans.sort(key=lambda s: s['origin'][0])
            merged.append(current_spans)
            current_spans = list(spans)
            current_y = y

    if current_spans:
        current_spans.sort(key=lambda s: s['origin'][0])
        merged.append(current_spans)

    return merged


def parse_pdf(filepath):
    """解析 PDF 並返回結構化的書卷資料。"""
    doc = fitz.open(filepath)
    book_name = os.path.splitext(os.path.basename(filepath))[0]

    chapters = {}  # {chapter_num: {'sections': [], 'footnotes': []}}
    current_chapter = 0
    current_section = None
    current_verse_num = None
    current_verse_text = ""
    current_verse_is_poetry = False
    poetry_lines = []
    all_footnotes = {}  # {chapter_num: [footnote_texts]}

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        # Skip version info page
        if is_version_page(page):
            continue

        lines = extract_page_data(page)
        in_footnote = False  # Reset per page - footnotes are always at page bottom

        for line_spans in lines:
            first_span = line_spans[0]
            first_size = first_span['size']
            first_flags = first_span['flags']
            first_text = first_span['text'].strip()
            first_x = first_span['origin'][0]

            # Skip header/footer (size=8.0)
            if first_size <= HEADER_FOOTER_SIZE:
                continue

            # Skip psalm volume headers (size ~15.9, like "詩、篇、卷、一")
            if 14.0 <= first_size <= 16.0 and first_size < TITLE_SIZE:
                continue

            # Book title or chapter number (size ~17.9, flags=20)
            if first_size >= TITLE_SIZE:
                # Save current verse before switching
                _flush_verse(chapters, current_chapter, current_section,
                             current_verse_num, current_verse_text,
                             current_verse_is_poetry, poetry_lines)
                current_verse_num = None
                current_verse_text = ""
                poetry_lines = []

                if first_text.isdigit():
                    # Chapter number
                    current_chapter = int(first_text)
                    if current_chapter not in chapters:
                        chapters[current_chapter] = {'sections': [], 'footnotes': []}
                    current_section = None

                    # Check if there's a section header on the same line after chapter num
                    remaining_text = _join_spans(line_spans[1:])
                    if remaining_text.strip():
                        current_section = remaining_text.strip()
                        chapters[current_chapter]['sections'].append({
                            'title': current_section,
                            'verses': []
                        })
                continue

            # Footnote detection (size=9.0, bold, starts with X:Y:)
            if first_size <= VERSE_NUM_SIZE and first_flags & 16:  # bold
                if FOOTNOTE_PATTERN.match(first_text.rstrip(':')):
                    # This is a footnote line - may contain multiple footnotes
                    _flush_verse(chapters, current_chapter, current_section,
                                 current_verse_num, current_verse_text,
                                 current_verse_is_poetry, poetry_lines)
                    current_verse_num = None
                    current_verse_text = ""
                    poetry_lines = []
                    in_footnote = True

                    # Split spans into individual footnotes by finding bold refs
                    fn_groups = []
                    current_fn_spans = []
                    for s in line_spans:
                        if (s['flags'] & 16 and s['size'] <= VERSE_NUM_SIZE
                                and FOOTNOTE_PATTERN.match(s['text'].strip().rstrip(':'))):
                            if current_fn_spans:
                                fn_groups.append(current_fn_spans)
                            current_fn_spans = [s]
                        else:
                            current_fn_spans.append(s)
                    if current_fn_spans:
                        fn_groups.append(current_fn_spans)

                    for group in fn_groups:
                        footnote_text = ''.join(s['text'] for s in group).strip()
                        fn_ch = int(group[0]['text'].strip().split(':')[0])
                        if fn_ch not in all_footnotes:
                            all_footnotes[fn_ch] = []
                        all_footnotes[fn_ch].append(footnote_text)
                    continue

            # If in footnote area, skip any continuation lines
            if in_footnote:
                if first_size <= VERSE_NUM_SIZE + 1 and first_x < PROSE_VERSE_X:
                    # Footnote continuation (small text at left margin)
                    ft = _join_spans(line_spans)
                    # Append to last footnote of most recent chapter
                    for ch in sorted(all_footnotes.keys(), reverse=True):
                        if all_footnotes[ch]:
                            all_footnotes[ch][-1] += ft
                            break
                    continue
                else:
                    in_footnote = False

            # Section header (size=12, x >= 85, no verse number)
            if first_size > VERSE_NUM_SIZE and first_x >= SECTION_HEADER_X:
                line_text = _join_spans(line_spans)
                # Verify it's not verse text (shouldn't start with space)
                if line_text and not line_text.startswith(' '):
                    _flush_verse(chapters, current_chapter, current_section,
                                 current_verse_num, current_verse_text,
                                 current_verse_is_poetry, poetry_lines)
                    current_verse_num = None
                    current_verse_text = ""
                    poetry_lines = []

                    current_section = line_text.strip()
                    if current_chapter not in chapters:
                        current_chapter = 1
                        chapters[current_chapter] = {'sections': [], 'footnotes': []}
                    chapters[current_chapter]['sections'].append({
                        'title': current_section,
                        'verses': []
                    })
                    continue

            # Verse number detection (size=9.0, digit or range, at start of line)
            verse_match = (VERSE_NUM_PATTERN.match(first_text)
                           if (first_size <= VERSE_NUM_SIZE
                               and first_size > HEADER_FOOTER_SIZE)
                           else None)
            if verse_match:
                # Flush previous verse
                _flush_verse(chapters, current_chapter, current_section,
                             current_verse_num, current_verse_text,
                             current_verse_is_poetry, poetry_lines)

                # If no chapter has been set yet, default to chapter 1
                if current_chapter == 0:
                    current_chapter = 1
                    chapters[current_chapter] = {'sections': [], 'footnotes': []}

                current_verse_num = first_text  # Keep as string for range verses
                # Poetry = verse number at left margin AND line doesn't extend to right margin
                right_edge = _get_line_right_edge(line_spans)
                current_verse_is_poetry = (first_x < PROSE_VERSE_X
                                           and right_edge < POETRY_RIGHT_EDGE)
                current_verse_text = ""
                poetry_lines = []

                # Get the rest of the line as verse text
                rest = _join_spans(line_spans[1:])
                if current_verse_is_poetry:
                    poetry_lines.append(rest.strip())
                else:
                    current_verse_text = rest
                continue

            # Continuation line (size=12, part of current verse)
            if first_size > VERSE_NUM_SIZE:
                line_text = _join_spans(line_spans)
                if current_verse_num is not None:
                    if current_verse_is_poetry:
                        poetry_lines.append(line_text.strip())
                    else:
                        current_verse_text += line_text
                else:
                    # Continuation before any verse in this chapter
                    # Part of previous page's verse
                    if current_verse_is_poetry:
                        poetry_lines.append(line_text.strip())
                    else:
                        current_verse_text += line_text

    # Flush last verse
    _flush_verse(chapters, current_chapter, current_section,
                 current_verse_num, current_verse_text,
                 current_verse_is_poetry, poetry_lines)

    # Assign footnotes to chapters
    for ch_num, fns in all_footnotes.items():
        if ch_num in chapters:
            chapters[ch_num]['footnotes'] = fns
        elif current_chapter > 0:
            # If chapter not found, assign to closest chapter
            if current_chapter in chapters:
                chapters[current_chapter]['footnotes'].extend(fns)

    doc.close()
    return book_name, chapters


def _join_spans(spans):
    """將 spans 合併為文字。"""
    text = ""
    for s in spans:
        text += s['text']
    return text


def _flush_verse(chapters, chapter_num, section_title, verse_num, verse_text,
                 is_poetry, poetry_lines):
    """將當前經文保存到 chapters 結構中。"""
    if verse_num is None:
        return
    if chapter_num not in chapters:
        chapters[chapter_num] = {'sections': [], 'footnotes': []}

    verse_data = {
        'num': verse_num,
        'is_poetry': is_poetry,
    }
    if is_poetry:
        verse_data['lines'] = [l for l in poetry_lines if l]
    else:
        verse_data['text'] = verse_text.strip()

    # Find or create section to add verse to
    ch = chapters[chapter_num]
    if not ch['sections']:
        ch['sections'].append({'title': None, 'verses': []})
    # If section_title matches current last section, add there
    if section_title and ch['sections'][-1]['title'] == section_title:
        ch['sections'][-1]['verses'].append(verse_data)
    elif section_title and not ch['sections'][-1]['verses'] and ch['sections'][-1]['title'] == section_title:
        ch['sections'][-1]['verses'].append(verse_data)
    else:
        # Add to last section
        ch['sections'][-1]['verses'].append(verse_data)


def format_markdown(book_name, chapters):
    """將結構化資料格式化為 Markdown。"""
    lines = []
    lines.append(f"# {book_name}")
    lines.append("")

    for ch_num in sorted(chapters.keys()):
        ch = chapters[ch_num]
        lines.append(f"## 第 {ch_num} 章")
        lines.append("")

        for section in ch['sections']:
            if section['title']:
                lines.append(f"### {section['title']}")
                lines.append("")

            for verse in section['verses']:
                if verse['is_poetry'] and verse.get('lines'):
                    # Poetry: first line with verse number, rest as separate lines
                    first = True
                    for pl in verse['lines']:
                        if first:
                            lines.append(f"**{verse['num']}** {pl}")
                            first = False
                        else:
                            lines.append(pl)
                    lines.append("")
                else:
                    # Prose: single line
                    text = verse.get('text', '')
                    lines.append(f"**{verse['num']}** {text}")
                    lines.append("")

        # Footnotes
        if ch.get('footnotes'):
            lines.append("---")
            lines.append("")
            lines.append("**註腳：**")
            for fn in ch['footnotes']:
                lines.append(f"- {fn}")
            lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pdf_files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.pdf')])
    print(f"找到 {len(pdf_files)} 個 PDF 檔案")

    for i, pdf_file in enumerate(pdf_files, 1):
        filepath = os.path.join(INPUT_DIR, pdf_file)
        print(f"[{i}/{len(pdf_files)}] 處理: {pdf_file}")

        try:
            book_name, chapters = parse_pdf(filepath)
            markdown = format_markdown(book_name, chapters)

            output_path = os.path.join(OUTPUT_DIR, f"{book_name}.md")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown)
            print(f"  -> {output_path} ({len(chapters)} 章)")
        except Exception as e:
            print(f"  錯誤: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n完成！輸出目錄: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
