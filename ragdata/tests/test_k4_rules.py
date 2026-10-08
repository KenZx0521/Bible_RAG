"""K4's mechanical rules, the query-alias registry, the union's edge cases (rt.dotless,
rt.divine_person, the "PDF plus curated only" variant) and the G-ROUTE rules that do not
recompile, on hand-made records."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace as NS

import pytest

import mini_release
import mini_route
from ragcommon import ids, routing
from ragcommon.tests import lexicon_doc
from ragdata import paths
from ragdata.contract import parse_record
from ragdata.gates.base import snapshot
from ragdata.gates.route import check_route
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.kg import k4_aliases, k4_build, k4_route, k4_rules
from ragdata.kg.layers import encode_json
from ragdata.stages.errors import StageError


def test_book_forms_are_the_66_names_and_18_forms_in_router_order():
    forms = [f.surface for f in k4_rules.book_forms()]
    assert len(forms) == len(set(forms)) == 84
    assert forms[:2] == ["帖撒羅尼迦前書", "帖撒羅尼迦後書"]
    assert forms.index("尼希米記") + 1 == forms.index("尼西米記")
    assert forms[-20:] == ["詩篇", "箴言", "雅歌", *k4_rules.EXTRA_BOOK_FORMS[:-1]]


def test_route_types_of_names_and_divine_surfaces():
    assert k4_rules.name_route_types([]) == ["Place"]
    assert k4_rules.name_route_types(["Place", "Person"]) == ["Person", "Place"]
    assert k4_rules.name_route_types(["Group"]) == []
    assert k4_rules.divine_route_types("人子") == ["Person"]
    assert k4_rules.divine_route_types("聖靈") == []
    with pytest.raises(StageError, match="凱撒 is in neither"):
        k4_rules.divine_route_types("凱撒")


def _verses(*units):
    """``units``: (unit_key, text, [(start, end) underlined])."""
    return k4_rules.verses([NS(unit_key=k, text_pdf=t) for k, t, _ in units],
                           [NS(region="body", container_id=k, start=a, end=b)
                            for k, _, spans in units for a, b in spans])


def test_a_name_the_pdf_prints_mostly_as_a_word_is_common():
    text = _verses(("gen.1.1", "自古以來以來以來", []), ("gen.1.2", "以來", [(0, 2)]),
                   ("gen.1.3", "西面西面", [(0, 2), (2, 4)]), ("gen.1.4", "西面", []))
    assert k4_rules.occurrences("以來", text) == (4, 1)
    assert k4_rules.common_words(["以來", "西面", "但"], text) == {
        "以來": {"raw": 4, "inside": 1, "outside": 3}}
    assert k4_rules.unroutable_rule("但", "divine", {}) == "rt.min_len"
    assert k4_rules.unroutable_rule("以來", "name", {"以來": {}}) == "rt.common_word"
    assert k4_rules.unroutable_rule("以來", "alias", {"以來": {}}) is None


# ------------------------------------------------------------ query_aliases.yaml


def test_the_committed_registry_holds_the_approved_aliases_and_exclusions():
    found = k4_aliases.load_query_aliases(paths.REGISTRIES)
    assert [a.alias_id for a in found.aliases] == [f"qa.{n:03d}" for n in range(1, 19) if n != 5]
    assert {("何提", "如何提"), ("何把", "如何把")} <= {(e.surface, e.context)
                                                    for e in found.exclusions}
    assert len(k4_aliases.lexicon_exclusions(paths.REGISTRIES)) == 9


QUESTION_NAMES = ("何提", "何把", "何利", "何坦", "他施", "中門", "以別", "以法", "以結", "本都",
                  "利未", "保羅", "耶穌")


@pytest.mark.parametrize("question, names", [
    ("為何把律法比作訓蒙的師傅？", []), ("任何提到恩典的經文有哪些？", []),
    ("保羅為何提到信心的重要？", ["保羅"]), ("保羅如何提醒提摩太？", ["保羅"]),
    ("耶穌如何為他施洗？", ["耶穌"]), ("耶穌為他施行了什麼神蹟？", ["耶穌"]),
    ("其中門徒們有何反應？", []), ("為何要以別人為重？", []),
    ("保羅為何以法律為訓蒙的師傅？", ["保羅"]), ("四福音基本都記載了這件事嗎？", []),
    ("這段經文如何以結論收尾？", []), ("為何利未人沒有地業？", ["利未"]),
    ("約拿為何往他施去？", ["他施"]), ("保羅在本都傳道嗎？", ["保羅", "本都"]),
    ("何提是誰的兒子？", ["何提"]),
])
def test_the_question_exclusions_veto_common_words_not_names(question, names):
    """The committed question_exclusions on the router's matcher (names made up as kg0's)."""
    rows = k4_aliases.load_query_aliases(paths.REGISTRIES).exclusions
    lex = routing.parse_lexicon(lexicon_doc.document(
        names=[lexicon_doc.name(s, ids.name_id(s)) for s in QUESTION_NAMES],
        exclusions=[lexicon_doc.exclusion(r.surface, r.context) for r in rows]))
    assert [h.surface for h in lex.match(question)] == names


@pytest.mark.parametrize("change, match", [
    ({"provenance_class": "external_query"}, "keys"),
    ({"aliases": [{"id": "qa.001", "surface": "死海", "target": "鹽海", "source": "x"}]},
     "keys"),
    ({"question_exclusions": [{"surface": "何提", "context": "如何把", "why": "x"}]},
     "does not contain"),
    ({"aliases": {}}, "expected a list"),
])
def test_a_malformed_registry_is_refused(tmp_path, change, match):
    mini_route.write_query_aliases(tmp_path, mini_route.query_aliases(**change))
    with pytest.raises(k4_aliases.RegistryError, match=match):
        k4_aliases.load_query_aliases(tmp_path)


# ------------------------------------------------------------ the union on hand-made records


@pytest.fixture(scope="module")
def mini_inputs(tmp_path_factory):
    mini = mini_release.build(tmp_path_factory.mktemp("k4_rules"))
    layers = k4_build.load_layers({n: mini.layers[n].path for n in ("text", "kg0", "events")})
    _, snap = check_schema(merge_files(list(layers.values())), list(layers))
    return k4_route.route_inputs(snap, {n: d.version for n, d in layers.items()},
                                 mini.root / "registries")


def _name(norm_key, start=0):
    return NS(name_id=ids.name_id(norm_key), norm_key=norm_key, type_candidates=(),
              norm_rule_ids=(), evidence_span_id=f"ns:act.9.1@{start}",
              provenance_class="pdf_deterministic")


def _with(inputs, **records):
    return dataclasses.replace(inputs, snapshot=snapshot({**inputs.snapshot.records, **records}))


def test_dotless_spellings_join_names_and_yield_to_existing_terms(mini_inputs):
    names = [_name("西門‧彼得"), _name("西‧門彼得", 3), _name("伯‧亞拉巴", 5), _name("伯亞拉巴", 9)]
    compiled = k4_route.compile_route(
        _with(mini_inputs, names=[*mini_inputs.snapshot.of("names"), *names]))
    by = {t["surface"]: t for t in compiled.records}
    simon = by["西門彼得"]
    assert simon["kind"] == "dotless" and simon["rule_id"] == "rt.dotless"
    assert [t["label"] for t in simon["targets"]] == sorted(
        ["西門‧彼得", "西‧門彼得"], key=ids.name_id)
    assert by["伯亞拉巴"]["kind"] == "name"
    assert compiled.report["dotless_skipped"] == [
        {"surface": "伯亞拉巴", "of": ["伯‧亞拉巴"], "already": "name"}]


def _gate(inputs, compiled):
    terms = [parse_record("routing_terms", r) for r in compiled.records]
    return check_route(inputs, terms, routing.render_lexicon(compiled.lexicon),
                       encode_json(compiled.query_aliases))


TITLES = ("救主", "基督", "人子", "主耶穌", "法老")


def _with_titles(inputs):
    """The mini (耶穌 is dr.span.001) with more printed divine patterns."""
    patterns = [*inputs.divine.patterns, *((f"dr.span.{9 + i:03d}", s)
                                           for i, s in enumerate(TITLES))]
    spans = [NS(source="divine_rule", surface=s, span_id=ids.name_span_id("mat.1.1", 2 * i))
             for i, s in enumerate(TITLES)]
    return dataclasses.replace(
        _with(inputs, extra_spans=[*inputs.snapshot.of("extra_spans"), *spans]),
        divine=dataclasses.replace(inputs.divine, patterns=tuple(patterns)))


def test_the_titles_of_jesus_are_one_target_with_their_own_rule_and_coordinate(mini_inputs):
    inputs = _with_titles(mini_inputs)
    compiled = k4_route.compile_route(inputs)
    by = {t["surface"]: t for t in compiled.lexicon["divine"]}
    jesus = by["耶穌"]["targets"]
    assert [(t["ref"], t["label"], t["route_types"]) for t in jesus] == [
        ("dr.span.001", "耶穌", ["Person"])]
    assert all(by[s]["targets"] == jesus for s in ("救主", "基督", "人子", "主耶穌"))
    assert by["法老"]["targets"][0]["ref"] == "dr.span.013" != jesus[0]["ref"]
    assert (by["救主"]["rule_id"], by["救主"]["evidence_span_id"]) == (
        "dr.span.009", ids.name_span_id("mat.1.1", 0))
    assert _gate(inputs, compiled).passed
    hits = routing.parse_lexicon(compiled.lexicon).match("救主耶穌被釘十字架時，基督徒在哪？")
    # longest first reads 救 + 主耶穌 (not 救主 + 耶穌); every title is the one target
    assert [h.surface for h in hits] == ["主耶穌", "基督"]
    assert {t.ref for h in hits for t in h.targets if "Person" in t.route_types} == {
        "dr.span.001"}


def test_a_title_naming_a_person_without_a_pattern_stops_the_union(mini_inputs):
    inputs = _with_titles(mini_inputs)
    divine = dataclasses.replace(inputs.divine, patterns=tuple(
        p for p in inputs.divine.patterns if p[1] != "耶穌"))
    with pytest.raises(StageError, match="救主 names 耶穌, which is no divine_refs pattern"):
        k4_route.compile_route(dataclasses.replace(inputs, divine=divine))


def test_the_pdf_and_curated_only_variant_is_a_legal_lexicon(mini_inputs):
    """No query alias, no external event alias, an event without triggers: G-ROUTE passes
    and the backend parses the lexicon."""
    events = [NS(event_id=e.event_id, name=e.name, pdf_terms=e.pdf_terms, external_aliases=())
              for e in mini_inputs.snapshot.of("events")]
    aliases = dataclasses.replace(mini_inputs.aliases, aliases=())
    inputs = dataclasses.replace(_with(mini_inputs, events=events), aliases=aliases)
    compiled = k4_route.compile_route(inputs)
    assert compiled.lexicon["aliases"] == [] and compiled.query_aliases["aliases"] == []
    assert {t["surface"] for t in compiled.lexicon["events"]} == {"渴慕", "切慕", "天上的光"}
    gate = _gate(inputs, compiled)
    assert gate.passed, gate.details
    routing.parse_lexicon(compiled.lexicon)


def _tampered(compiled, records=None, aliases=None):
    """``compiled`` with its records (the lexicon joined again) or alias contract changed."""
    rows, doc = json.loads(json.dumps(compiled.records)), json.loads(json.dumps(
        compiled.query_aliases))
    for change, target in ((records, rows), (aliases, doc)):
        if change:
            change(target)
    rest = {k: v for k, v in compiled.lexicon.items() if k not in k4_route.ROUTE_CATEGORIES}
    return k4_route.Compiled(k4_route.join_lexicon(rest, rows), rows, doc, compiled.report)


def _row(rows, kind, **where):
    return next(r for r in rows if r["kind"] == kind and all(r[k] == v for k, v in where.items()))


AGREED_MISTAKES = {
    "a name is pdf_rule though no normalization rule applied": (
        dict(records=lambda rs: _row(rs, "name").update(provenance_class="pdf_rule")),
        "a name is pdf_rule iff a normalization rule applied"),
    "a dotless term without its rule": (
        dict(records=lambda rs: _row(rs, "dotless").update(rule_id=None)),
        "a dotless term needs rule_id"),
    "a pdf event term without its coordinate": (
        dict(records=lambda rs: _row(rs, "event", provenance_class="curated_human").update(
            at=None)), "term needs at"),
    "an event target that is no event id": (
        dict(records=lambda rs: _row(rs, "event")["targets"][0].update(ref="event:tianguo")),
        "the backend refuses routing_lexicon.json: events"),
    "an alias row the backend refuses": (
        dict(aliases=lambda d: d["aliases"][0].update(note="")),
        "the backend refuses query_aliases.json: aliases[0].note"),
}


@pytest.mark.parametrize("case", sorted(AGREED_MISTAKES))
def test_g_route_catches_what_k4_and_the_records_agree_on(mini_inputs, monkeypatch, case):
    """Rules 2 to 6 do not recompile: a mistake K4 itself made still turns G-ROUTE red."""
    changes, reason = AGREED_MISTAKES[case]
    inputs = _with(mini_inputs, names=[*mini_inputs.snapshot.of("names"), _name("西門‧彼得")])
    tampered = _tampered(k4_route.compile_route(inputs), **changes)
    monkeypatch.setattr(k4_route, "compile_route", lambda _: tampered)
    gate = _gate(inputs, tampered)
    assert not gate.passed and any(reason in d for d in gate.details), gate.details


def test_two_events_sharing_a_trigger_stop_the_union(mini_inputs):
    first, *rest = mini_inputs.snapshot.of("events")
    twin = NS(event_id="ev0009", name="雙生", pdf_terms=(), external_aliases=(
        NS(text=first.triggers[0], source="x", note="y", provenance_class="external_event_alias"),))
    with pytest.raises(StageError, match=rf"{first.triggers[0]} appears twice \(event, event\)"):
        k4_route.compile_route(_with(mini_inputs, events=[first, *rest, twin]))


def test_a_registry_directory_without_query_aliases_is_refused(tmp_path):
    with pytest.raises(k4_aliases.RegistryError, match="query_aliases.yaml: unreadable"):
        k4_aliases.load_query_aliases(tmp_path)
