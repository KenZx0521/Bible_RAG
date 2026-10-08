"""``build route`` (K4, R2) and G-ROUTE on the mini text, kg0 and events layers.

The mini release's route layer is the union of mini_route (counts, aliases) over the mini
kg0 and events; G-ROUTE compiles it again and turns red on any stored drift.
"""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

import mini_release
import mini_route
from ragcommon import routing
from ragdata import cli, store
from ragdata.gates import check_det
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg import k4_build, k4_route
from ragdata.stages.errors import StageError

INPUTS = ("text", "kg0", "events")


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("route_mini"))


def _deps(mini):
    return [mini.layers[name].path for name in INPUTS]


def _json(layer, name):
    return json.loads((layer.path / name).read_text(encoding="utf-8"))


def _gate(mini, layer_dir, registries=None):
    inputs = GateInputs(registries=registries or mini.root / "registries")
    return gate_layer(layer_dir, "route", _deps(mini), mini_release.MINI_COUNTS, inputs=inputs)


def test_the_build_stores_the_union_and_its_two_contracts(mini):
    built = store.read_layer(mini.layers["route"].path)
    assert set(built.file_shas) - {store.DEPENDS_ON} == {
        "routing_terms.jsonl", "routing_lexicon.json", "query_aliases.json", "route_report.json"}
    assert built.depends_on == {n: mini.layers[n].version for n in INPUTS}
    terms = built.rows["routing_terms.jsonl"]
    kinds = {k: sum(t["kind"] == k for t in terms) for k in mini_route.COUNTS}
    assert kinds == mini_route.COUNTS
    assert [t["term_key"] for t in terms][:2] == ["names/0000", "names/0001"]
    doc = _json(built, "routing_lexicon.json")
    routing.parse_lexicon(doc)
    assert doc["header"]["inputs"]["kg0"] == mini.layers["kg0"].version
    assert [(e["surface"], e["context"]) for e in doc["exclusions"]] == [("何提", "如何提"),
                                                                        ("掃羅", "掃羅王")]
    report = _json(built, "route_report.json")
    assert report["divine_unprinted"] == ["神"]
    assert report["unroutable"] == {"rt.min_len": ["主"], "rt.common_word": []}


def test_terms_carry_every_target_and_their_provenance(mini):
    doc = _json(store.read_layer(mini.layers["route"].path), "routing_lexicon.json")
    by = {t["surface"]: t for c in k4_route.ROUTE_CATEGORIES for t in doc[c]}
    salt = by["鹽海"]["targets"][0]
    assert (salt["route_types"], by["掃羅"]["targets"][0]["route_types"]) == (["Place"], ["Place"])
    assert by["死海"]["targets"] == [salt] and by["死海"]["provenance_class"] == "external_query"
    assert by["耶穌"]["targets"][0]["route_types"] == ["Person"]
    assert by["上帝"]["targets"][0]["route_types"] == [] and not by["主"]["routable"]
    assert by["天上的光"]["provenance_class"] == "curated_human"
    assert by["天上的光"]["at"] == "hd:act.9.3b#1"
    assert by["保羅歸主"]["targets"][0]["ref"] == "ev0003"
    assert by["尼希米記"]["book_id"] == "neh" and by["尼希米記"]["targets"] == []


def test_the_alias_contract_is_the_compiled_registry(mini):
    doc = _json(store.read_layer(mini.layers["route"].path), "query_aliases.json")
    assert doc["schema"] == routing.QUERY_ALIASES_SCHEMA
    assert [(a["alias_id"], a["surface"], a["target"]) for a in doc["aliases"]] == [
        ("qa.001", "死海", "鹽海"), ("qa.002", "該撒利亞", "凱撒利亞")]
    assert routing.parse_query_aliases(doc)


def test_the_stored_layer_passes_its_gates_again_and_rebuilds_the_same(mini, tmp_path):
    report = _gate(mini, mini.layers["route"].path)
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    again = k4_build.build_route(*_deps(mini), tmp_path / "store", mini.root / "registries",
                                 mini_release.MINI_COUNTS)
    assert again.layers["route"].version == mini.layers["route"].version
    assert check_det(mini.layers["route"].path, again.layers["route"].path).passed


def test_the_gate_fails_closed_without_the_registries(mini, tmp_path):
    report = _gate(mini, mini.layers["route"].path, tmp_path / "none")
    route = next(g for g in report.gates if g.name == "G-ROUTE")
    assert not route.passed and route.observed == "missing input"


# ------------------------------------------------------------ stored drift


def _copy(mini, tmp_path, rows=None, lexicon=None, aliases=None):
    """The mini route layer with its records, lexicon or alias contract changed (the
    lexicon joined again from changed records unless it is changed itself)."""
    built = store.read_layer(mini.layers["route"].path)
    records = [json.loads(json.dumps(r)) for r in built.rows["routing_terms.jsonl"]]
    doc, alias_doc = _json(built, "routing_lexicon.json"), _json(built, "query_aliases.json")
    if rows:
        rows(records)
        doc = k4_route.join_lexicon({k: v for k, v in doc.items()
                                     if k not in k4_route.ROUTE_CATEGORIES}, records)
    for change, target in ((lexicon, doc), (aliases, alias_doc)):
        if change:
            change(target)
    files = {"routing_terms.jsonl": store.encode_jsonl(records),
             "routing_lexicon.json": routing.render_lexicon(doc),
             "query_aliases.json": json.dumps(alias_doc, ensure_ascii=False).encode("utf-8"),
             "route_report.json": (built.path / "route_report.json").read_bytes()}
    return store.write_layer(tmp_path / "store", "route", files,
                             depends_on=built.depends_on).path


def _term(records, surface):
    return next(r for r in records if r["surface"] == surface)


DRIFT = {
    "a term the rules hide is made routable": (
        dict(rows=lambda rs: _term(rs, "主").update(routable=True, unroutable_rule=None)),
        "divine/0001 主: differs from the union"),
    "a term carries legacy provenance": (
        dict(lexicon=lambda d: d["names"][0].update(provenance_class="external_legacy")),
        "legacy provenance at $.names[0].provenance_class"),
    "a trigger points at another event": (
        dict(rows=lambda rs: _term(rs, "天國")["targets"][0].update(ref="ev0001")),
        "event term 天國 -> ev0001 is no trigger of that event"),
    "an alias stands for a name that does not exist": (
        dict(rows=lambda rs: _term(rs, "死海")["targets"][0].update(ref="nm:000000000000")),
        "target nm:000000000000 is no kg0 name or divine pattern"),
    "a book form leaves the lexicon": (
        dict(rows=lambda rs: rs.remove(_term(rs, "尼希米記"))), "books/0018 尼希米記: missing"),
    "the alias contract is edited": (
        dict(aliases=lambda d: d["aliases"][0].update(note="改了")),
        "query_aliases.json is not the compile of query_aliases.yaml"),
}


@pytest.mark.parametrize("case", sorted(DRIFT))
def test_stored_drift_turns_g_route_red(mini, tmp_path, case):
    changes, reason = DRIFT[case]
    report = _gate(mini, _copy(mini, tmp_path, **changes))
    route = next(g for g in report.gates if g.name == "G-ROUTE")
    assert not route.passed and any(reason in d for d in route.details), route.details


# ------------------------------------------------------------ registries


def _registries(mini, tmp_path, **changes):
    directory = tmp_path / "registries"
    shutil.copytree(mini.root / "registries", directory)
    mini_route.write_query_aliases(directory, mini_route.query_aliases(**changes))
    return directory


def _alias(**row):
    return [{"id": "qa.001", "surface": "死海", "target": "鹽海", "source": "x", "note": "y",
             **row}]


@pytest.mark.parametrize("aliases, match", [
    (_alias(target="不存在"), "target 不存在 is not a kg0 name"),
    (_alias(target="神"), "target 神 is not a kg0 name or a divine surface the PDF prints"),
    (_alias(surface="掃羅"), r"掃羅 is already a term \(name\)"),
    (_alias(surface="天國"), r"天國 is already a term \(event\)"),
    (_alias(surface="Salt Sea"), "latin letters"),
    (_alias(id="qa.1"), "is not qa.NNN"),
    ([*_alias(), *_alias(id="qa.002")], "listed twice"),
])
def test_an_alias_that_clashes_with_the_layers_stops_the_build(mini, tmp_path, aliases, match):
    registries = _registries(mini, tmp_path, aliases=aliases)
    with pytest.raises(StageError, match=match):
        k4_build.build_route(*_deps(mini), tmp_path / "store", registries,
                             mini_release.MINI_COUNTS)


def test_registries_kg0_was_not_built_with_stop_the_build(mini, tmp_path):
    registries = _registries(mini, tmp_path)
    divine = yaml.safe_load((registries / "divine_refs.yaml").read_text(encoding="utf-8"))
    divine["what"] = "改了"
    (registries / "divine_refs.yaml").write_text(yaml.safe_dump(divine, allow_unicode=True),
                                                 encoding="utf-8")
    with pytest.raises(StageError, match="kg0 was built with"):
        k4_build.build_route(*_deps(mini), tmp_path / "store", registries,
                             mini_release.MINI_COUNTS)
    route = next(g for g in _gate(mini, mini.layers["route"].path, registries).gates
                 if g.name == "G-ROUTE")
    assert not route.passed and "kg0 was built with" in route.expected


# ------------------------------------------------------------ cli


def _cli(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    return code, capsys.readouterr()


def test_cli_build_and_gate_route(mini, tmp_path, capsys):
    text, kg0, events = _deps(mini)
    common = ("--registries", mini.root / "registries", "--counts", mini_release.MINI_COUNTS)
    code, captured = _cli(capsys, "build", "route", "--text", text, "--kg0", kg0,
                          "--events", events, "--store", tmp_path, *common)
    assert code == 0, captured.out
    layer = json.loads(captured.out)["layers"]["route"]["path"]
    code, captured = _cli(capsys, "gate", "route", layer, "--dep", text, "--dep", kg0,
                          "--dep", events, *common)
    assert code == 0 and json.loads(captured.out)["pass"] is True
    code, captured = _cli(capsys, "build", "route", "--text", text, "--store", tmp_path)
    assert code == 2 and "--kg0" in captured.err
