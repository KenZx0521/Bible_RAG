"""A hand-built, internally consistent mini snapshot (text + struct layers).

Five books, six chapters; it exercises every special case of design §2.23 that
the contracts cover: a merged unit, an omitted slot with its variant footnote, a
mid-verse heading, a stacked section heading with a section_range, a
superscription and a book division, selah, a speaker, errata in a unit and in a
footnote, underline spans in body and footnote (one merge group), a ref alias,
a cross-chapter pericope, an untitled book opening and a chunked passage.

``build()`` returns fresh dicts every call, so tests may mutate the result.
The expected counts live in ``mini_counts.yaml`` and were tallied by hand.
"""

from __future__ import annotations

import hashlib

from ragcommon import ids

SELAH = "（細拉）"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pdf_sha(book_id: str) -> str:
    return sha("pdf:" + book_id)


def _unit(book, ch, vs, text_pdf, ve=None, text=None, errata=(), poetry=False, breaks=()):
    text = text_pdf if text is None else text
    markers = []
    if SELAH in text_pdf:
        start = text_pdf.index(SELAH)
        markers.append({"type": "selah", "start": start, "end": start + len(SELAH)})
    return {
        "unit_key": ids.unit_key(book, ch, vs, ve), "book_id": book, "chapter": ch,
        "label": str(vs) if ve is None else f"{vs}-{ve}", "v_start": vs, "v_end": ve or vs,
        "ord": 0, "text_pdf": text_pdf, "text": text, "text_sha256": sha(text),
        "errata_ids": list(errata), "line_breaks": [{"offset": o, "kind": "soft"} for o in breaks],
        "markers": markers, "is_poetry": poetry, "pages": [1],
        "prov": {"pdf_sha256": _pdf_sha(book), "first_glyph": [90.0, 102.0, 180.5]},
        "provenance_class": "pdf_deterministic",
    }


ACT_9_3_PDF = "掃羅將到大馬士革，詵過小河，忽然有光四面照着他。"
ACT_9_3 = ACT_9_3_PDF.replace("詵", "蹚")
ACT_MID = ACT_9_3.index("忽然")
FN_ORIGINAL_PDF = "原文是詴問"


def _units() -> list[dict]:
    return [
        _unit("psa", 42, 1, "上帝啊，我的心切慕你，如鹿切慕溪水。", poetry=True, breaks=(5,)),
        _unit("psa", 42, 2, "我的心渴想上帝，就是永生上帝。" + SELAH, poetry=True),
        _unit("psa", 42, 3, "我晝夜以眼淚當飲食。", poetry=True),
        _unit("sng", 1, 1, "願他用口與我親嘴。", poetry=True),
        _unit("mat", 18, 1, "當時，門徒進前來，問耶穌說：「天國裏誰是最大的？」"),
        _unit("mat", 18, 2, "耶穌就叫一個小孩子來，使他站在他們當中。"),
        _unit("mat", 18, 4, "所以，凡自己謙卑像這小孩子的，他在天國裏就是最大的。"),
        _unit("act", 9, 1, "掃羅仍然向主的門徒口吐威嚇兇殺的話。"),
        _unit("act", 9, 2, "求文書給大馬士革的各會堂，經過鹽海。"),
        _unit("act", 9, 3, ACT_9_3_PDF, text=ACT_9_3, errata=["er:0001"]),
        _unit("act", 10, 1, "在凱撒利亞有一個人名叫哥尼流。"),
        _unit("eph", 6, 1, "你們作兒女的，要在主裏聽從父母，這是理所當然的。"),
        _unit("eph", 6, 2, "「要孝敬父母，使你得福，在世長壽。」這是第一條帶應許的誡命。",
              ve=3, breaks=(18,)),
        _unit("eph", 6, 4, "你們作父親的，不要惹兒女的氣。"),
    ]


def _slots() -> list[dict]:
    rows = []
    for key, unit, status in (
        ("psa.42.1", "psa.42.1", "present"), ("psa.42.2", "psa.42.2", "present"),
        ("psa.42.3", "psa.42.3", "present"), ("sng.1.1", "sng.1.1", "present"),
        ("mat.18.1", "mat.18.1", "present"), ("mat.18.2", "mat.18.2", "present"),
        ("mat.18.3", None, "omitted_variant"), ("mat.18.4", "mat.18.4", "present"),
        ("act.9.1", "act.9.1", "present"), ("act.9.2", "act.9.2", "present"),
        ("act.9.3", "act.9.3", "present"), ("act.10.1", "act.10.1", "present"),
        ("eph.6.1", "eph.6.1", "present"), ("eph.6.2", "eph.6.2-3", "merged"),
        ("eph.6.3", "eph.6.2-3", "merged"), ("eph.6.4", "eph.6.4", "present"),
    ):
        rows.append({"slot_key": key, "unit_key": unit, "status": status,
                     "variant_footnote_id": "fn:mat.18.2#1" if unit is None else None,
                     "provenance_class": "pdf_deterministic"})
    return rows


BOOK_META = {
    "psa": (19, "詩篇", "Psalms", "OT", "wisdom", ["詩"]),
    "sng": (22, "雅歌", "Song of Solomon", "OT", "wisdom", []),
    "mat": (40, "馬太福音", "Matthew", "NT", "gospels", ["太"]),
    "act": (44, "使徒行傳", "Acts", "NT", "acts", ["徒"]),
    "eph": (49, "以弗所書", "Ephesians", "NT", "pauline", ["弗"]),
}
# (book, chapter) -> unit_count, present_slot_count, max_verse, omitted, sp, dv
CHAPTERS = {
    ("psa", 42): (3, 3, 3, [], True, "dv:psa.42"),
    ("sng", 1): (1, 1, 1, [], False, None),
    ("mat", 18): (3, 3, 4, ["mat.18.3"], False, None),
    ("act", 9): (3, 3, 3, [], False, None),
    ("act", 10): (1, 1, 1, [], False, None),
    ("eph", 6): (3, 4, 4, [], False, None),
}


def _chapters() -> list[dict]:
    rows = []
    for (book, ch), (units, present, max_v, omitted, sp, dv) in CHAPTERS.items():
        rows.append({
            "chapter_key": f"{book}.{ch}", "book_id": book, "chapter": ch, "unit_count": units,
            "present_slot_count": present, "slot_rows": present + len(omitted),
            "max_verse": max_v, "omitted_slots": list(omitted), "has_superscription": sp,
            "book_division_id": dv, "provenance_class": "pdf_deterministic",
        })
    return rows


def _books() -> list[dict]:
    rows = []
    for book, (ord_, name, name_en, testament, category, short) in BOOK_META.items():
        chapters = [v for (b, _), v in CHAPTERS.items() if b == book]
        present = sum(v[1] for v in chapters)
        omitted = sum(len(v[3]) for v in chapters)
        rows.append({
            "book_id": book, "ord": ord_, "name": name, "name_source": "pdf_title_line",
            "file_name": name, "file_name_mismatch": False, "short_names": short,
            "name_en": name_en, "testament": testament, "category": category,
            "chapter_count": len(chapters), "unit_count": sum(v[0] for v in chapters),
            "present_slot_count": present, "slot_rows": present + omitted,
            "omitted_count": omitted, "pdf_sha256": _pdf_sha(book),
            "provenance_class": "pdf_deterministic", "meta_provenance": "curated_metadata",
        })
    return rows


def _chapter_texts() -> list[dict]:
    sp_text = "可拉後裔的訓誨詩，交給聖詠團長。"
    return [
        {"id": "sp:psa.42", "kind": "superscription", "chapter_key": "psa.42",
         "text_pdf": sp_text, "text": sp_text, "order": "after_heading", "pages": [40],
         "provenance_class": "pdf_deterministic"},
        {"id": "dv:psa.42", "kind": "book_division", "chapter_key": "psa.42",
         "text_pdf": "卷二", "text": "卷二", "order": None, "pages": [40],
         "provenance_class": "pdf_deterministic"},
    ]


def _heading(hid, anchor, title, level=2, offset=0, parent=None, display=None):
    return {
        "heading_id": hid, "book_id": anchor.split(".")[0], "anchor_unit_key": anchor,
        "anchor_offset": offset, "pos": "mid" if offset else "before", "level": level,
        "parent_heading_id": parent, "text_pdf": title, "text": title,
        "display_title": display or title, "ord": 0,
        "prov": {"style_class": f"navy_h{level}", "glyph_range": [100, 100 + len(title) - 1]},
        "provenance_class": "pdf_deterministic",
    }


def _headings() -> list[dict]:
    return [
        _heading("hd:psa.42.1#1", "psa.42.1", "渴慕上帝"),
        _heading("hd:mat.18.1#1", "mat.18.1", "天國裏誰是最大的"),
        _heading("hd:act.9.1#1", "act.9.1", "掃羅歸主", level=1),
        _heading("hd:act.9.1#2", "act.9.1", "－在路上", parent="hd:act.9.1#1",
                 display="掃羅歸主－在路上"),
        _heading("hd:act.9.3b#1", "act.9.3", "天上的光", offset=ACT_MID),
        _heading("hd:eph.6.1#1", "eph.6.1", "兒女和父母"),
    ]


def _target(book, start, end):
    return {"book_id": book, "start_slot": start, "end_slot": end}


def _parallel_refs() -> list[dict]:
    mat_raw = "（徒9‧1－2；弗6‧1－4）"
    rows = [
        ("pr:hd:mat.18.1#1#1", "hd:mat.18.1#1", mat_raw, 0, "parallel",
         [_target("act", "act.9.1", "act.9.2")], "abbr+ch‧v－v"),
        ("pr:hd:mat.18.1#1#2", "hd:mat.18.1#1", mat_raw, 1, "parallel",
         [_target("eph", "eph.6.1", "eph.6.4")], "abbr+ch‧v－v"),
        ("pr:hd:act.9.1#1#1", "hd:act.9.1#1", "（9‧1－10‧1）", 0, "section_range",
         [_target("act", "act.9.1", "act.10.1")], "ch‧v－ch‧v"),
    ]
    keys = ("pr_id", "heading_id", "raw", "seg_idx", "kind", "targets", "parse_rule")
    return [dict(zip(keys, row), provenance_class="pdf_deterministic") for row in rows]


def _footnote(fid, unit, n, kind, text_pdf, text=None, variant=None, anchor=None, errata=()):
    return {
        "fn_id": fid, "unit_key": unit, "n": n, "kind": kind, "anchor": anchor,
        "text_pdf": text_pdf, "text": text_pdf if text is None else text,
        "variant_slot_key": variant, "refs": [], "errata_ids": list(errata),
        "provenance_class": "pdf_deterministic",
    }


def _footnotes() -> list[dict]:
    return [
        _footnote("fn:mat.18.1#1", "mat.18.1", 1, "original", FN_ORIGINAL_PDF,
                  text=FN_ORIGINAL_PDF.replace("詴", "試"), errata=["er:0002"]),
        _footnote("fn:mat.18.2#1", "mat.18.2", 1, "variant", "有古卷加：3人子來，為要拯救失喪的人。",
                  variant="mat.18.3"),
        _footnote("fn:act.9.1#1", "act.9.1", 1, "name_meaning", "掃羅：名字的意思是求問",
                  anchor={"start": 0, "end": 2}),
        _footnote("fn:eph.6.1#1", "eph.6.1", 1, "alt_rendering", "在主裏：或譯在主裏的人"),
    ]


def _speakers() -> list[dict]:
    return [{"sk_id": "sk:sng.1.1#1", "unit_key": "sng.1.1", "offset": 0, "pos": "before",
             "text_pdf": "〔新娘〕", "text": "〔新娘〕", "provenance_class": "pdf_deterministic"}]


def _span(container, start, surface, region="body", merge_group=None):
    return {
        "span_id": ids.name_span_id(container, start), "container_id": container,
        "region": region, "start": start, "end": start + len(surface), "surface": surface,
        "source": "pdf_underline", "norm_key": surface, "norm_rule_ids": [],
        "merge_group": merge_group, "provenance_class": "pdf_deterministic",
    }


def _name_spans() -> list[dict]:
    salt_sea = ids.merge_group_id("鹽海", 1)
    return [
        _span("act.9.1", 0, "掃羅"),
        _span("act.9.2", 4, "大馬士革"),
        _span("act.9.2", 15, "鹽", merge_group=salt_sea),
        _span("act.9.2", 16, "海", merge_group=salt_sea),
        _span("act.9.3", 0, "掃羅"),
        _span("act.9.3", 4, "大馬士革"),
        _span("act.10.1", 1, "凱撒利亞"),
        _span("act.10.1", 11, "哥尼流"),
        _span("fn:act.9.1#1", 0, "掃羅", region="footnote"),
    ]


def _errata() -> list[dict]:
    def row(eid, container, kind, offset, pdf_char, corrected):
        return {"errata_id": eid, "container_id": container, "container_kind": kind,
                "offset": offset, "pdf_char": pdf_char, "corrected_char": corrected,
                "class": "big5_e04x_misglyph", "evidence": {"corrected_occurrences_in_pdf_text": 0},
                "decided_by": "kay", "provenance_class": "curated_human"}
    return [
        row("er:0001", "act.9.3", "unit", ACT_9_3_PDF.index("詵"), "詵", "蹚"),
        row("er:0002", "fn:mat.18.1#1", "footnote", FN_ORIGINAL_PDF.index("詴"), "詴", "試"),
    ]


def _ref_aliases() -> list[dict]:
    return [{"external_ref": "mat.18.5", "relation": "contained_in", "target": "mat.18.4",
             "note": "測試用：外部節號 18:5 併入 18:4", "provenance_class": "external_reference"}]


def text_layer() -> dict[str, list[dict]]:
    return {
        "books": _books(), "chapters": _chapters(), "verse_units": _units(),
        "verse_slots": _slots(), "chapter_texts": _chapter_texts(), "headings": _headings(),
        "parallel_refs": _parallel_refs(), "footnotes": _footnotes(), "speakers": _speakers(),
        "name_spans": _name_spans(), "errata_applied": _errata(), "ref_aliases": _ref_aliases(),
    }


# ------------------------------------------------------------------ struct layer


def _pos(unit, offset):
    return {"unit_key": unit, "offset": offset}


def _pericope(pid, heading, title, start, end, chapters, passages, **links):
    start_slot = start["unit_key"]
    end_slot = end["unit_key"]
    return {
        "pericope_id": pid, "book_id": pid[3:6], "heading_id": heading,
        "section_heading_id": links.get("section"), "title": title,
        "untitled_reason": None if heading else "book_opening", "start": start, "end": end,
        "start_slot": start_slot, "end_slot": end_slot, "chapters": chapters,
        "passage_ids": passages, "prev_id": links.get("prev"), "next_id": links.get("next"),
        "next_book_id": links.get("next_book"), "provenance_class": "pdf_deterministic",
    }


def _pericopes() -> list[dict]:
    return [
        _pericope("pc:psa.42.1", "hd:psa.42.1#1", "渴慕上帝", _pos("psa.42.1", 0),
                  _pos("psa.42.3", None), [42], ["ps:psa.42.1"], next_book="sng"),
        _pericope("pc:sng.1.1", None, None, _pos("sng.1.1", 0), _pos("sng.1.1", None),
                  [1], ["ps:sng.1.1"], next_book="mat"),
        _pericope("pc:mat.18.1", "hd:mat.18.1#1", "天國裏誰是最大的", _pos("mat.18.1", 0),
                  _pos("mat.18.4", None), [18], ["ps:mat.18.1"], next_book="act"),
        _pericope("pc:act.9.1", "hd:act.9.1#2", "掃羅歸主－在路上", _pos("act.9.1", 0),
                  _pos("act.9.3", ACT_MID), [9], ["ps:act.9.1"],
                  section="hd:act.9.1#1", next="pc:act.9.3b"),
        _pericope("pc:act.9.3b", "hd:act.9.3b#1", "天上的光", _pos("act.9.3", ACT_MID),
                  _pos("act.10.1", None), [9, 10], ["ps:act.9.3b", "ps:act.10.1"],
                  prev="pc:act.9.1", next_book="eph"),
        _pericope("pc:eph.6.1", "hd:eph.6.1#1", "兒女和父母", _pos("eph.6.1", 0),
                  _pos("eph.6.4", None), [6], ["ps:eph.6.1"]),
    ]


def _ref(unit, start=0, end=None):
    return {"unit_key": unit, "from": start, "to": end}


def _passage(pid, pericope, seg, title, verse_range, end_key, refs, **extra):
    start_key = pid[3:]
    content = extra.get("content", "".join(r["unit_key"] for r in refs))
    tokens = extra.get("tokens", 40)
    return {
        "passage_id": pid, "pericope_id": pericope, "chapter_key": start_key.rsplit(".", 1)[0],
        "seg_idx": seg[0], "seg_count": seg[1], "continued": seg[0] > 0, "title": title,
        "start_slot": start_key.rstrip("b"), "end_slot": end_key.rstrip("b"),
        "verse_range": verse_range, "start_key": start_key, "end_key": end_key,
        "start_partial": start_key.endswith("b"), "end_partial": extra.get("end_partial", False),
        "unit_refs": refs, "superscription_id": extra.get("sp"), "content": content,
        "content_sha": sha(content), "token_count": tokens, "requires_chunking": tokens > 768,
        "provenance_class": "pdf_deterministic",
    }


def _passages() -> list[dict]:
    return [
        _passage("ps:psa.42.1", "pc:psa.42.1", (0, 1), "渴慕上帝", "1-3", "psa.42.3",
                 [_ref("psa.42.1"), _ref("psa.42.2"), _ref("psa.42.3")], sp="sp:psa.42"),
        _passage("ps:sng.1.1", "pc:sng.1.1", (0, 1), None, "1", "sng.1.1", [_ref("sng.1.1")]),
        _passage("ps:mat.18.1", "pc:mat.18.1", (0, 1), "天國裏誰是最大的", "1-4", "mat.18.4",
                 [_ref("mat.18.1"), _ref("mat.18.2"), _ref("mat.18.4")]),
        _passage("ps:act.9.1", "pc:act.9.1", (0, 1), "掃羅歸主－在路上", "1-3", "act.9.3",
                 [_ref("act.9.1"), _ref("act.9.2"), _ref("act.9.3", 0, ACT_MID)],
                 end_partial=True, tokens=900),
        _passage("ps:act.9.3b", "pc:act.9.3b", (0, 2), "天上的光", "3", "act.9.3b",
                 [_ref("act.9.3", ACT_MID)]),
        _passage("ps:act.10.1", "pc:act.9.3b", (1, 2), "天上的光", "1", "act.10.1",
                 [_ref("act.10.1")]),
        _passage("ps:eph.6.1", "pc:eph.6.1", (0, 1), "兒女和父母", "1-4", "eph.6.4",
                 [_ref("eph.6.1"), _ref("eph.6.2-3"), _ref("eph.6.4")]),
    ]


def _chunks() -> list[dict]:
    return [
        {"chunk_id": "ck:act.9.1~act.9.2", "passage_id": "ps:act.9.1", "idx": 0,
         "unit_refs": [_ref("act.9.1"), _ref("act.9.2")], "overlap_unit_keys": [],
         "start_key": "act.9.1", "end_key": "act.9.2", "verse_range": "1-2",
         "token_count": 500, "provenance_class": "pdf_deterministic"},
        {"chunk_id": "ck:act.9.2~act.9.3", "passage_id": "ps:act.9.1", "idx": 1,
         "unit_refs": [_ref("act.9.2"), _ref("act.9.3", 0, ACT_MID)],
         "overlap_unit_keys": ["act.9.2"], "start_key": "act.9.2", "end_key": "act.9.3",
         "verse_range": "2-3", "token_count": 450, "provenance_class": "pdf_deterministic"},
    ]


def struct_layer() -> dict[str, list[dict]]:
    return {"pericopes": _pericopes(), "passages": _passages(), "chunks": _chunks()}


def build() -> dict[str, dict[str, list[dict]]]:
    return {"text": text_layer(), "struct": struct_layer()}


def files(*layers: str) -> dict[str, list[dict]]:
    """The mini snapshot as ``{file name: rows}`` for the given layers."""
    built = build()
    return {f"{name}.jsonl": rows for layer in layers for name, rows in built[layer].items()}


def write_layers(root, text: dict | None = None, struct: dict | None = None):
    """Write the (possibly mutated) mini layers to a store; return (text, struct) StoredLayers."""
    from ragdata import store

    def encode(layer: dict) -> dict[str, bytes]:
        return {f"{name}.jsonl": store.encode_jsonl(rows) for name, rows in layer.items()}

    text_layer_ = store.write_layer(root, "text", encode(text_layer() if text is None else text))
    struct_layer_ = store.write_layer(root, "struct",
                                      encode(struct_layer() if struct is None else struct),
                                      depends_on={"text": text_layer_.version})
    return text_layer_, struct_layer_
