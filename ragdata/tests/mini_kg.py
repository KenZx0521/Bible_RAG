"""Mini KG registries and the kg0/events/route rows they must produce from the mini
snapshot (mini_build.py), written by hand as the oracle the K stages reproduce.

Registries: ``normalization()``, ``divine_refs()``, ``underline_fixes()`` (YAML docs),
``legacy_registry()`` (the backend's event_registry.json shape) and ``lexicon()``
(a frozen routing lexicon). ``write_registries(dir)`` writes the YAML ones and
returns their versions; the oracle rows cite those versions.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ragcommon import ids

GT_QUESTIONS = ("掃羅在大馬士革遇見誰？", "保羅歸主的經過", "以弗所書提到兒女和父母")


def normalization() -> dict:
    return {
        "schema": "ragdata.name_normalization.v1",
        "rules": {
            "suffix_outside": {"id": "nn.suffix_outside", "what": "後綴在線外", "suffixes": ["人", "的"]},
            "generic_inside": {"id": "nn.generic_inside", "what": "通名在線內", "nouns": ["海", "門"],
                               "exceptions": ["西門"], "exception_why": "音譯尾字",
                               "type_candidate": "Place"},
            "merge": {"id": "nn.merge", "what": "拆段合併", "groups": ["鹽海"]},
            "interpunct": {"id": "nn.interpunct", "what": "不拆", "char": "‧"},
            "truncation": {"id": "nn.truncation", "what": "以底線為準",
                           "examples": [{"truncated": "哥尼", "full": "哥尼流"}]},
        },
        "lexicon": {"id": "lx.longest", "what": "非正文區詞表比對",
                    "regions": ["superscription", "heading", "footnote"], "min_len": 2,
                    "min_len_why": "單字名太常見",
                    "book_citation": {"id": "lx.book_citation", "what": "書卷引用",
                                      "pattern": "[上下]?[一二三四五六七八九十]+章",
                                      "book_titles": True},
                    "exclude_contexts": [{"surface": "掃羅", "context": "掃羅王", "why": "測試"}]},
    }


def divine_refs() -> dict:
    return {
        "schema": "ragdata.divine_refs.v1", "what": "不畫線的神名", "region": "body",
        "span_patterns": [{"id": "dr.span.001", "surface": "耶穌", "what": "人名"},
                          {"id": "dr.span.002", "surface": "上帝", "what": "神名"},
                          {"id": "dr.span.003", "surface": "主", "what": "稱謂"},
                          {"id": "dr.span.004", "surface": "神", "what": "神"}],
        "exclusions": {"主": [{"word": "主人", "why": "主僕"}],
                       "神": [{"word": "神蹟", "why": "奇事"}]},
    }


def underline_fixes() -> dict:
    return {"schema": "ragdata.underline_fixes.v1", "not_entity": [], "curated_underline": []}


REGISTRY_FILES = {"name_normalization": normalization, "divine_refs": divine_refs,
                  "underline_fixes": underline_fixes}


def dump(doc: dict) -> bytes:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False).encode("utf-8")


def version(name: str, data: bytes) -> str:
    return f"{name}@{hashlib.sha256(data).hexdigest()[:12]}"


def write_registries(directory: Path, **docs: dict) -> dict[str, str]:
    """Write the mini registries (``docs`` replaces some); return their versions."""
    directory.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name, make in REGISTRY_FILES.items():
        data = dump(docs.get(name, make()))
        (directory / f"{name}.yaml").write_bytes(data)
        versions[name] = version(name, data)
    return versions


# ------------------------------------------------------------------ kg0 oracle


def _name(norm_key, surfaces, occurrences, sources, evidence, rules=(), types=()):
    return {"name_id": ids.name_id(norm_key), "norm_key": norm_key, "surfaces": surfaces,
            "body_occurrences": occurrences, "span_sources": sources,
            "type_candidates": [{"type": t, "rule": "nn.generic_inside"} for t in types],
            "norm_rule_ids": list(rules), "evidence_span_id": evidence,
            "provenance_class": "pdf_rule" if rules else "pdf_deterministic"}


def names() -> list[dict]:
    return [
        _name("掃羅", ["掃羅"], 2, ["lexicon", "pdf_underline"], "ns:act.9.1@0"),
        _name("大馬士革", ["大馬士革"], 2, ["pdf_underline"], "ns:act.9.2@4"),
        _name("鹽海", ["鹽海"], 1, ["pdf_underline"], "ns:act.9.2@15",
              rules=("nn.generic_inside", "nn.merge"), types=("Place",)),
        _name("凱撒利亞", ["凱撒利亞"], 1, ["pdf_underline"], "ns:act.10.1@1"),
        _name("哥尼流", ["哥尼流"], 1, ["pdf_underline"], "ns:act.10.1@11"),
    ]


def _extra(container, region, start, surface, source, rule, registry):
    return {"span_id": ids.name_span_id(container, start), "container_id": container,
            "region": region, "start": start, "end": start + len(surface), "surface": surface,
            "source": source, "rule_id": rule, "registry_version": registry,
            "decision_ref": None, "decided_by": None, "provenance_class": "pdf_rule"}


def extra_spans(versions: dict[str, str]) -> list[dict]:
    divine, lex = versions["divine_refs"], versions["name_normalization"]
    rows = [("psa.42.1", 0, "上帝", "dr.span.002"), ("psa.42.2", 5, "上帝", "dr.span.002"),
            ("psa.42.2", 12, "上帝", "dr.span.002"), ("mat.18.1", 10, "耶穌", "dr.span.001"),
            ("mat.18.2", 0, "耶穌", "dr.span.001"), ("act.9.1", 5, "主", "dr.span.003"),
            ("eph.6.1", 9, "主", "dr.span.003")]
    return [*(_extra(c, "body", s, w, "divine_rule", r, divine) for c, s, w, r in rows),
            _extra("hd:act.9.1#1", "heading", 0, "掃羅", "lexicon", "lx.longest", lex)]


def parallel_links() -> list[dict]:
    def link(pr_id, to, start, end):
        return {"link_key": f"{pr_id}|{to}", "pr_id": pr_id, "from_pericope": "pc:mat.18.1",
                "to_pericope": to, "target_start_slot": start, "target_end_slot": end,
                "provenance_class": "pdf_deterministic"}
    return [link("pr:hd:mat.18.1#1#1", "pc:act.9.1", "act.9.1", "act.9.2"),
            link("pr:hd:mat.18.1#1#2", "pc:eph.6.1", "eph.6.1", "eph.6.4")]


def kg0_layer(versions: dict[str, str]) -> dict[str, list[dict]]:
    return {"names": names(), "extra_spans": extra_spans(versions),
            "parallel_links": parallel_links()}


def kg0_counts(versions: dict[str, str], text: str, struct: str) -> dict:
    return {
        "schema": "ragdata.kg0_counts.v1", "registries": dict(sorted(versions.items())),
        "inputs": {"struct": struct, "text": text}, "names": 5, "parallel_links": 2,
        "extra_spans": {
            "divine_rule": {"total": 7, "by_region": {"body": 7},
                            "by_surface": {"上帝": 3, "主": 2, "耶穌": 2}},
            "lexicon": {"total": 1, "by_region": {"heading": 1}, "by_surface": {"掃羅": 1}},
            "curated_underline": {"total": 0, "by_region": {}, "by_surface": {}},
        },
    }


# ------------------------------------------------------------------ events


def legacy_registry() -> dict:
    """The backend's event_registry.json shape over the mini legacy pericopes."""
    return {
        "version": 1, "generated_at": "2026-10-03T20:21:29", "generator": "test",
        "trigger_rule": "exact keyword", "anchor_order": "canonical",
        "events": [
            {"id": "event:kemu", "name": "渴慕上帝", "provenance": "alias_injection",
             "triggers": ["渴慕"], "anchors": ["psa:42:0"]},
            {"id": "event:tianguo", "name": "天國裏誰是最大的", "provenance": "head_event_backfill",
             "triggers": ["天國", "最大的"], "anchors": ["mat:18:0"]},
            {"id": "event:saoluo", "name": "掃羅歸主", "provenance": "manual_edges",
             "triggers": ["保羅歸主"], "anchors": ["act:9:0", "act:9:1"]},
        ],
        "dropped": [{"id": "event:none", "name": "無", "reason": "test"}],
    }
