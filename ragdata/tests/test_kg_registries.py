"""K0 registries: name_normalization, divine_refs, underline_fixes (design §2.17, §5.2)."""

from __future__ import annotations

import pytest

import mini_kg
from ragdata.kg import registries
from ragdata.kg.registries import RegistryError


def test_mini_registries_load_with_their_versions(tmp_path):
    versions = mini_kg.write_registries(tmp_path)
    loaded = registries.load_k0(tmp_path)
    assert loaded.versions() == versions
    norm = loaded.normalization
    assert norm.generic_nouns == ("海", "門") and norm.generic_exceptions == {"西門"}
    assert norm.merges == ("鹽海",) and norm.interpunct == "‧"
    assert norm.lexicon.regions == ("superscription", "heading", "footnote")
    assert norm.lexicon.book_citation.match("上十六章")
    assert loaded.divine.patterns[0] == ("dr.span.001", "耶穌")
    assert loaded.divine.exclusions["主"] == ("主人",)
    assert loaded.fixes.not_entity == {}


def test_registry_version_is_name_and_sha12():
    assert registries.registry_version("divine_refs", b"x") == mini_kg.version("divine_refs", b"x")


def _broken(changes):
    def patch(doc, path, value):
        *head, last = path
        for key in head:
            doc = doc[key]
        doc[last] = value
    docs = {name: make() for name, make in mini_kg.REGISTRY_FILES.items()}
    for (name, *path), value in changes.items():
        patch(docs[name], path, value)
    return docs


BROKEN = {
    "wrong schema": ({("divine_refs", "schema"): "x"}, "schema"),
    "pattern twice": ({("divine_refs", "span_patterns"): [
        {"id": "dr.span.001", "surface": "主", "what": "a"},
        {"id": "dr.span.002", "surface": "主", "what": "b"}]}, "twice"),
    "exclusion without the char": ({("divine_refs", "exclusions"): {
        "主": [{"word": "神蹟", "why": "x"}]}}, "does not contain"),
    "exclusion for a non-pattern": ({("divine_refs", "exclusions"): {
        "王": [{"word": "王子", "why": "x"}]}}, "not a single-character pattern"),
    "exclusion without why": ({("divine_refs", "exclusions"): {"主": [{"word": "主人"}]}},
                              "why"),
    "unknown normalization rule": ({("name_normalization", "rules", "extra"): {"id": "x"}},
                                   "rules"),
    "noun not one character": ({("name_normalization", "rules", "generic_inside", "nouns"):
                                ["海口"]}, "one character"),
    "bad lexicon region": ({("name_normalization", "lexicon", "regions"): ["body"]}, "regions"),
    "bad book citation pattern": ({("name_normalization", "lexicon", "book_citation",
                                    "pattern"): "("}, "pattern"),
    "not_entity without decider": ({("underline_fixes", "not_entity"): [
        {"id": "uf-001", "span_id": "ns:act.10.1@11", "surface": "哥尼流", "why": "x"}]},
        "decided_by"),
    "bad span id": ({("underline_fixes", "not_entity"): [
        {"id": "uf-001", "span_id": "act.10.1", "surface": "哥尼流", "decided_by": "kay",
         "why": "x"}]}, "span"),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_malformed_registries_are_refused(tmp_path, case):
    changes, message = BROKEN[case]
    mini_kg.write_registries(tmp_path, **_broken(changes))
    with pytest.raises(RegistryError, match=message):
        registries.load_k0(tmp_path)


def test_missing_registry_file_is_refused(tmp_path):
    with pytest.raises(RegistryError, match="unreadable"):
        registries.load_k0(tmp_path)


def test_curated_underlines_are_read(tmp_path):
    fixes = mini_kg.underline_fixes()
    fixes["curated_underline"] = [{"id": "uf-002", "container_id": "act.9.1", "start": 0,
                                   "surface": "掃羅", "decided_by": "kay", "why": "漏畫"}]
    fixes["not_entity"] = [{"id": "uf-001", "span_id": "ns:act.10.1@11", "surface": "哥尼流",
                            "decided_by": "kay", "why": "錯畫"}]
    mini_kg.write_registries(tmp_path, underline_fixes=fixes)
    loaded = registries.load_k0(tmp_path).fixes
    assert loaded.curated[0].container_id == "act.9.1"
    assert loaded.not_entity["ns:act.10.1@11"].surface == "哥尼流"
