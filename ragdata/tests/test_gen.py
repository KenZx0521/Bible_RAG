"""The GEN card's files in the relations layer (plan 2026-10-21 §2.1, A6): the port rebuilds the
audited pair byte for byte, G-GEN pins it, and a relations layer from before GEN still passes.

Tests that read real data read the store's text and route layers and skip without them; their
assertions compare sha256s and counts only, so a failure prints no scripture or names.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

import fake_encoder
import mini_build
import mini_pipeline
from ragdata import cli
from ragdata.contract.registry import (
    GEN_LAYER, GEN_NAMES, REGNAL_LAYER, REGNAL_REPORT, ROUTING_LEXICON,
)
from ragdata.gates.base import GateInputError
from ragdata.gates.gen import EXPECT_SCHEMA, check_gen, load_gen_expect
from ragdata.gates.runner import GateInputs, gate_deps, gate_layer
from ragdata.kg import gen_layer, gen_names
from ragdata.kg.regnal_build import build_regnal, gen_files, regnal_files
from ragdata.release import assemble as rel
from ragdata.release.gating import ReleaseChecks, default_checks, red_gates
from ragdata.stages.errors import StageError
from ragdata.store import DEPENDS_ON, layer_digest, read_layer, write_layer

REPO = Path(__file__).resolve().parents[2]
STORE = Path("/mnt/ollama-data/bible_rag_store")
TEXT = STORE / "layers/text/text@247eafe44b02"
ROUTE = STORE / "layers/route/route@c31c88e4681e"
R1_ROUTE = STORE / "layers/route/route@5c397e2df007"        # R1's lexicon, on the same text
SERVING = STORE / "layers/relations/relations@ee8e78c043d2"   # b20261019_a86f2b06
OLD = STORE / "layers/relations/relations@a04b67a301dc"       # b20261019_18aa84ad
A86 = STORE / "releases/b20261019_a86f2b06.json"
STAGE0 = REPO / "evaluation/experiments/2026-10-20_arith_stage0/gen_layer.py"
NAMES_G = REPO / "evaluation/experiments/2026-10-20_gen_confirm/names_g.py"
CARDS_COMMON = REPO / "evaluation/experiments/2026-10-18_kg_cards/cards_common.py"
needs_layers = pytest.mark.skipif(not (TEXT.is_dir() and ROUTE.is_dir()),
                                  reason=f"{TEXT.name} or {ROUTE.name} not in the store")
needs_old = pytest.mark.skipif(not (TEXT.is_dir() and ROUTE.is_dir() and SERVING.is_dir() and OLD.is_dir()),
                               reason="the relations layers from before GEN are not in the store")
needs_a86 = pytest.mark.skipif(not A86.is_file(), reason=f"{A86.name} not in the store")
NO_ENCODER = ReleaseChecks(inputs=GateInputs(encoder=fake_encoder.make()))   # relations reads none


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- the port

def _assigned(path: Path, names: set[str]) -> list[str]:
    """ast dumps of the module-level defs and assignments of ``names`` in ``path``."""
    out = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            out.append(ast.dump(node))
        elif isinstance(node, ast.Assign):
            targets = [t for target in node.targets
                       for t in (target.elts if isinstance(target, ast.Tuple) else [target])]
            if any(getattr(t, "id", None) in names for t in targets):
                out.append(ast.dump(node))
    return out


@pytest.mark.parametrize("source, port, names", [
    (CARDS_COMMON, gen_layer, {"_CN", "cn2int"}),
    (STAGE0, gen_layer, {"SCHEMA", "CHAPTERS", "FLOOD_CHAPTER", "EXPECT", "NUM", "NAME", "BEGET", "REMAIN",
                         "TOTAL", "NAMED", "FLOOD_AGE", "ANCHOR", "ONE_SON"}),
    (NAMES_G, gen_names, {"SCHEMA", "CAIN_CHAPTER", "ABRAM_CHAPTER", "EXTRA_CHAPTERS", "CAIN_REQUIRED",
                          "ABRAM_REQUIRED", "OTHER_BOOK_IDS", "BOOK_WORDS", "BLOCKER_EXTRA", "DOT", "_KEY"}),
], ids=["cn2int", "gen_layer", "names_g"])
def test_the_port_keeps_the_frozen_scripts_numerals_patterns_and_lists(source, port, names):
    want, got = _assigned(source, names), _assigned(Path(port.__file__), names)
    assert len(want) == len(got) > 0
    assert [i for i, (a, b) in enumerate(zip(want, got)) if a != b] == []


@pytest.mark.parametrize("numeral, value", [
    ("三", 3), ("十二", 12), ("四十一", 41), ("一百零五", 105), ("一九", 19), ("〇", 0), ("百", 100),
    ("九百九十九", 999), ("", None), ("甲", None), ("12", None),
])
def test_cn2int_reads_the_numerals_experiment_a_reads(numeral, value):
    assert gen_layer.cn2int(numeral) == value


def test_a_text_without_genesis_gets_no_gen_file(tmp_path):
    text, _ = mini_build.write_layers(tmp_path)
    data = read_layer(text.path)
    assert not gen_layer.has_chains(data.rows["verse_units.jsonl"])
    assert gen_files(data, None) == {}


@pytest.fixture(scope="module")
def text():
    return read_layer(TEXT)


@pytest.fixture(scope="module")
def route():
    return read_layer(ROUTE)


@pytest.fixture(scope="module")
def files(text, route):
    return {**regnal_files(text), **gen_files(text, route)}


@pytest.fixture(scope="module")
def expect():
    return load_gen_expect()


@needs_layers
def test_the_build_on_the_served_layers_is_the_audited_pair_byte_for_byte(files, expect):
    assert _sha(files[GEN_LAYER]) == expect["gen_layer_sha256"]
    assert _sha(files[GEN_NAMES]) == expect["gen_names_sha256"]
    assert (len(files[GEN_LAYER]), len(files[GEN_NAMES])) == (8252, 4463)


@needs_layers
def test_the_audited_pair_passes_k0_2_and_names_the_bytes_it_was_built_from(files, text, route):
    doc, names = json.loads(files[GEN_LAYER]), json.loads(files[GEN_NAMES])
    problems, chain = len(gen_layer.check(doc)), len(names["chain"])
    assert problems == 0 and chain == 19
    assert names["gen_layer_sha256"] == _sha(files[GEN_LAYER])
    assert names["text_digest"] == doc["text_digest"] == layer_digest(text.file_shas)
    assert list(names["sources"]) == list(gen_names.SOURCES)
    read = [_sha(files[GEN_LAYER]), text.file_shas["name_spans.jsonl"], text.file_shas["books.jsonl"],
            _sha((TEXT / "layer_manifest.json").read_bytes()), route.file_shas[ROUTING_LEXICON]]
    assert list(names["sources"].values()) == read


@needs_layers
def test_a_text_with_genesis_needs_the_route_layer(text):
    with pytest.raises(StageError, match="--route"):
        gen_files(text, None)


# ---------------------------------------------------------------- G-GEN

DIGEST, LEXICON, OLD_REGNAL = "a" * 64, "1" * 64, "b" * 64
DEPENDS = {"text": "text@" + "a" * 12, "route": "route@" + "c" * 12}


def _pair(digest: str = DIGEST, lexicon: str = LEXICON) -> tuple[bytes, bytes]:
    return (gen_layer.encode({"schema": gen_layer.SCHEMA, "text_digest": digest}),
            gen_layer.encode({"schema": gen_names.SCHEMA, "sources": {gen_names.SOURCE_LEXICON: lexicon}}))


def _expect(layer: bytes, names: bytes) -> dict:
    return {"schema": EXPECT_SCHEMA, "gen_layer_sha256": _sha(layer), "gen_names_sha256": _sha(names),
            "absent_ok_regnal": [OLD_REGNAL]}


def test_g_gen_passes_the_pinned_pair_built_on_its_text_and_route():
    layer, names = _pair()
    gate = check_gen(layer, names, "f" * 64, DEPENDS, LEXICON, _expect(layer, names))
    assert gate.passed, gate.details


@pytest.mark.parametrize("change, needle", [
    (dict(names=None), "both or neither"),
    (dict(layer=None), "both or neither"),
    (dict(depends_on={"text": DEPENDS["text"]}), "does not depend on the route layer"),
    (dict(lexicon_sha="2" * 64), "names lexicon"),
    (dict(lexicon_sha=None), "not given"),
    (dict(depends_on={**DEPENDS, "text": "text@" + "d" * 12}), "was read from"),
    (dict(layer=_pair(digest="e" * 64)[0]), "is not the audited"),
    (dict(names=_pair(lexicon="2" * 64)[1], lexicon_sha="2" * 64), "is not the audited"),
], ids=["no-names", "no-layer", "no-route", "lexicon", "no-lexicon", "text", "layer-pin", "names-pin"])
def test_g_gen_turns_red_on_any_departure_from_the_pinned_pair(change, needle):
    layer, names = _pair()
    args = {"layer": layer, "names": names, "regnal_sha": "f" * 64, "depends_on": DEPENDS,
            "lexicon_sha": LEXICON, **change}
    gate = check_gen(expect=_expect(layer, names), **args)
    assert not gate.passed and any(needle in d for d in gate.details), gate.details


@pytest.mark.parametrize("depends_on, regnal_sha, passed", [
    ({"text": DEPENDS["text"]}, OLD_REGNAL, True),
    (DEPENDS, OLD_REGNAL, False),                      # built on route: the files must be there
    ({"text": DEPENDS["text"]}, "f" * 64, False),      # not a layer from before GEN
    ({"text": DEPENDS["text"]}, None, False),
])
def test_g_gen_lets_only_a_layer_from_before_gen_go_without_the_files(depends_on, regnal_sha, passed):
    gate = check_gen(None, None, regnal_sha, depends_on, None, _expect(*_pair()))
    assert gate.passed is passed, gate.details


def test_the_expectation_file_must_name_its_pins(tmp_path):
    path = tmp_path / "gen_expect.yaml"
    path.write_text(f"schema: {EXPECT_SCHEMA}\ngen_layer_sha256: x\n", encoding="utf-8")
    with pytest.raises(GateInputError):
        load_gen_expect(path)


@needs_old
def test_the_repository_lets_through_the_two_relations_layers_from_before_gen(expect):
    regnal = {read_layer(d).file_shas[REGNAL_LAYER] for d in (SERVING, OLD)}
    assert set(expect["absent_ok_regnal"]) == regnal


# ---------------------------------------------------------------- stored layers and dependencies

@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    if not (TEXT.is_dir() and ROUTE.is_dir()):
        pytest.skip(f"{TEXT.name} or {ROUTE.name} not in the store")
    root = tmp_path_factory.mktemp("gen_store")
    result = build_regnal(TEXT, root, route_dir=ROUTE)
    assert result.passed, [g.to_json() for g in result.gates]
    return result.layers["relations"]


def test_the_built_layer_depends_on_text_and_route_and_holds_the_four_files(stored):
    data = read_layer(stored.path)
    assert data.depends_on == {"text": TEXT.name, "route": ROUTE.name}
    assert set(data.file_shas) == {DEPENDS_ON, REGNAL_LAYER, REGNAL_REPORT, GEN_LAYER, GEN_NAMES}
    report = gate_layer(stored.path, "relations", [TEXT, ROUTE])
    assert report.passed, [g.name for g in report.gates if not g.passed]
    with pytest.raises(GateInputError, match="given"):
        gate_layer(stored.path, "relations", [TEXT])


def _variant(root: Path, files: dict, keep: tuple, deps: dict) -> Path:
    return write_layer(root, "relations", {k: files[k] for k in keep}, depends_on=deps).path


@needs_layers
@pytest.mark.parametrize("keep, built_on, needle", [
    ((REGNAL_LAYER, REGNAL_REPORT), ROUTE, "a layer built on route carries both"),
    ((REGNAL_LAYER, REGNAL_REPORT, GEN_LAYER), ROUTE, "both or neither"),
    ((REGNAL_LAYER, REGNAL_REPORT, GEN_NAMES), ROUTE, "both or neither"),
    ((REGNAL_LAYER, REGNAL_REPORT, GEN_LAYER, GEN_NAMES), None, "does not depend on the route layer"),
    ((REGNAL_LAYER, REGNAL_REPORT, GEN_LAYER, GEN_NAMES), R1_ROUTE, "names lexicon"),
], ids=["regnal-only-on-route", "only-gen-layer", "only-gen-names", "gen-on-text-only", "other-lexicon"])
def test_g_gen_turns_a_stored_layer_of_the_wrong_shape_red(tmp_path, files, keep, built_on, needle):
    if built_on is not None and not built_on.is_dir():
        pytest.skip(f"{built_on.name} not in the store")
    deps = {"text": TEXT.name, **({"route": built_on.name} if built_on else {})}
    dirs = [TEXT, *([built_on] if built_on else [])]
    report = gate_layer(_variant(tmp_path, files, keep, deps), "relations", dirs)
    gen = {g.name: g for g in report.gates}["G-GEN"]
    assert [g.name for g in report.gates if not g.passed] == ["G-GEN"]
    assert any(needle in d for d in gen.details), gen.details


@needs_old
@pytest.mark.parametrize("layer_dir", [SERVING, OLD], ids=["ee8e78c043d2", "a04b67a301dc"])
def test_a_relations_layer_from_before_gen_passes_g_gen_and_takes_no_route(layer_dir):
    (gate,) = gate_layer(layer_dir, "relations", [TEXT], gates=["G-GEN"]).gates
    assert gate.passed, gate.details
    with pytest.raises(GateInputError, match="given"):
        gate_layer(layer_dir, "relations", [TEXT, ROUTE], gates=["G-GEN"])


@needs_old
def test_the_release_gates_take_the_dependencies_each_relations_layer_declares(stored, text, route):
    for relations in (read_layer(SERVING), read_layer(stored.path)):
        assert red_gates({"text": text, "route": route, "relations": relations}, ["relations"],
                         NO_ENCODER) == []
    red = red_gates({"text": text, "route": route, "relations": read_layer(OLD)}, ["relations"], NO_ENCODER)
    regnal, gen = sum(" G-REGNAL: " in r for r in red), sum(" G-GEN: " in r for r in red)
    assert (len(red), regnal, gen) == (1, 1, 0)      # the old layer is red on its regnal pins only


def test_gate_deps_are_the_declared_ones_of_the_required_and_optional():
    assert gate_deps("relations", {"text": "t"}) == ("text",)
    assert gate_deps("relations", {"route": "r", "text": "t"}) == ("text", "route")
    assert gate_deps("relations", {"text": "t", "kg0": "k"}) == ("text",)
    assert gate_deps("emb", {"text": "t", "struct": "s"}) == ("struct", "text")


def _mini_relations(root: Path, declared: tuple) -> tuple[Path, dict]:
    text, struct = mini_build.write_layers(root)
    versions = {"text": text.version, "struct": struct.version}
    dirs = {"text": text.path, "struct": struct.path}
    layer = write_layer(root, "relations", regnal_files(read_layer(text.path)),
                        depends_on={d: versions[d] for d in declared})
    return layer.path, dirs


@pytest.mark.parametrize("declared, given", [
    (("text", "struct"), ("text", "struct")),   # struct is no dependency of relations
    ((), ()),                                   # text is required
    (("text",), ("text", "struct")),            # more given than declared
], ids=["undeclarable", "missing-required", "undeclared-given"])
def test_a_relations_layer_is_gated_with_exactly_what_it_may_declare(tmp_path, declared, given):
    layer, dirs = _mini_relations(tmp_path, declared)
    with pytest.raises(GateInputError, match="needs dependencies"):
        gate_layer(layer, "relations", [dirs[d] for d in given], gates=["G-GEN"])


def test_a_regnal_only_layer_of_an_unaudited_regnal_file_is_red(tmp_path):
    layer, dirs = _mini_relations(tmp_path, ("text",))
    (gate,) = gate_layer(layer, "relations", [dirs["text"]], gates=["G-GEN"]).gates
    assert not gate.passed and any("not a layer from before GEN" in d for d in gate.details)


# ---------------------------------------------------------------- command line and release

def test_build_relations_on_a_text_without_genesis_needs_no_route(tmp_path, capsys):
    mini = mini_pipeline.make(tmp_path)
    text = tmp_path / "scratch" / "text" / mini.text_version
    expects = ["--regnal-expect", str(mini.sources.gate.regnal_expect),
               "--gen-expect", str(mini.sources.gate.gen_expect)]
    assert cli.main(["build", "relations", "--text", str(text), "--store", str(tmp_path / "out"),
                     *expects]) == 0
    layer = Path(json.loads(capsys.readouterr().out)["layers"]["relations"]["path"])
    assert read_layer(layer).depends_on == {"text": mini.text_version}
    assert cli.main(["gate", "relations", str(layer), "--dep", str(text), *expects]) == 0
    capsys.readouterr()
    assert cli.main(["build", "relations", "--text", str(text), "--route", str(tmp_path / "none"),
                     "--store", str(tmp_path / "out"), *expects]) == 2


@needs_a86
def test_the_serving_release_assembles_again_byte_for_byte():
    again = rel.read_release(A86, STORE / "layers", default_checks())
    assert again.build_id == "b20261019_a86f2b06" and again.doc["contract_version"] == "1.2.0"
    assert not {GEN_LAYER, GEN_NAMES} & set(again.doc["contracts"])
