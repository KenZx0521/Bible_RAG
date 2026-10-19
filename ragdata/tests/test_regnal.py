"""The relations layer, which holds only the regnal formulas (Kay's P5 exception, 2026-10-19):
its build is the fixed layer (rules R1a-R12 of 2026-10-19, audited by K0-R, K0-1' and Kay's
check), G-REGNAL pins it, and a release may carry it as an optional layer without changing the
bytes of a release that does not.

The fixed layer is held to experiment A's reference layer with Solomon taken off the Judah chain
(store reports/regnal_fix_20261019/ref_layer_v2.json, derived from ref_layer.json 79d57efe by
evaluation/experiments/2026-10-19_regnal_fix/ref_v2.py)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ragcommon import regnal
from ragdata.gates.regnal import (
    check_regnal, expectation_doc, load_regnal_expect, report_doc,
)
from ragdata.gates.runner import GateInputs, gate_layer
from ragdata.kg.regnal_build import build_regnal, encode_layer, regnal_files
from ragdata.kg.regnal_core import Layer
from ragdata.release import assemble as rel
from ragdata.release.gating import default_checks, release_gates
from ragdata.store import read_layer

STORE = Path("/mnt/ollama-data/bible_rag_store")
TEXT = STORE / "layers/text/text@247eafe44b02"
R2 = STORE / "releases/b20261008_e05d3e55.json"
SERVED = STORE / "layers/relations/relations@a04b67a301dc"   # experiment A's layer, in b20261019_18aa84ad
AUDITED = STORE / "reports/regnal_fix_20261019/candidate/regnal_layer.json"
REF_V2 = STORE / "reports/regnal_fix_20261019/ref_layer_v2.json"
needs_text = pytest.mark.skipif(not TEXT.is_dir(), reason=f"{TEXT.name} not in the store")
needs_r2 = pytest.mark.skipif(not R2.is_file(), reason=f"{R2.name} not in the store")
needs_served = pytest.mark.skipif(not (TEXT.is_dir() and SERVED.is_dir()),
                                  reason=f"{TEXT.name} or {SERVED.name} not in the store")
needs_ref_v2 = pytest.mark.skipif(not (TEXT.is_dir() and REF_V2.is_file()),
                                  reason=f"{TEXT.name} or {REF_V2.name} not in the store")


@pytest.fixture(scope="module")
def text():
    return read_layer(TEXT)


@pytest.fixture(scope="module")
def files(text):
    return regnal_files(text)


@pytest.fixture(scope="module")
def expect():
    return load_regnal_expect()


@pytest.fixture(scope="module")
def doc(files):
    return json.loads(files["regnal_layer.json"])


@pytest.fixture(scope="module")
def view(doc):
    return regnal.load(doc)


def _gate(data: bytes, expect, text_version="text@247eafe44b02", report=None):
    doc = json.loads(data)
    report = report if report is not None else report_doc(doc, text_version, hashlib.sha256(data).hexdigest())
    return check_regnal(data, report, {"text": text_version}, expect)


def _node(doc, name, kingdom=None):
    hits = [n for n in doc["nodes"] if n["name"] == name and kingdom in (None, n["kingdom"])]
    assert len(hits) == 1, (name, kingdom, [n["id"] for n in hits])
    return hits[0]


@needs_text
def test_the_build_on_the_served_text_is_the_audited_layer_byte_for_byte(files, expect):
    data = files["regnal_layer.json"]
    assert hashlib.sha256(data).hexdigest() == expect["layer_sha256"]
    if AUDITED.is_file():
        assert data == AUDITED.read_bytes()


@needs_text
def test_the_chains_are_the_divided_kingdoms_from_jeroboam_and_rehoboam(view, expect):
    chains = view.chain_names()
    assert chains == expect["chains"]
    assert chains["I"][0] == "耶羅波安" and chains["I"][-1] == "何細亞" and len(chains["I"]) == 19
    assert chains["J"][0] == "羅波安" and chains["J"][-1] == "西底家" and len(chains["J"]) == 20
    i = chains["J"].index("亞哈謝")
    assert chains["J"][i:i + 3] == ["亞哈謝", "亞她利雅", "約阿施"]
    assert "亞他利雅" not in chains["J"] + chains["I"]   # another name: the men of 1ch.8.26, ezr.8.7


@needs_text
def test_solomon_is_a_king_of_all_israel_on_no_chain(doc, view):
    """R8: 1ki.11.42 makes him king of all Israel with no accession formula; 2ch.9.31 repeats
    his succession, and Judah no longer flows back to him through that edge."""
    solomon = _node(doc, "所羅門")
    assert solomon["kingdom"] == "U" and solomon["fields"]["reign"][:2] == [40, "1ki.11.42"]
    assert solomon["id"] in view.nodes
    assert all(solomon["id"] not in view.chain[kd] for kd in regnal.KINGDOMS)
    assert not [e for e in doc["edges"] + doc["fallback_edges"] if solomon["id"] in e[:2]]
    assert _node(doc, "羅波安")["fields"]["father"][:2] == ["所羅門", "1ki.11.43"]


@needs_text
def test_athaliah_has_her_accession_and_her_six_years(doc):
    """R1a: the usurpation is her accession evidence; R1b: the span before it is her reign."""
    athaliah = _node(doc, "亞她利雅", "J")
    assert athaliah["has_acc"] and not athaliah["pending"]
    assert athaliah["fields"]["reign"][:2] == [6, "2ki.11.3"]


@needs_text
def test_a_usurpation_is_the_victims_death_only_where_the_verse_says_he_was_killed(doc):
    """R14: 2ki.9.14 is only the revolt against Joram, 2ki.11.3 Athaliah's reign, not her son's
    death; the rebellion that names the killing (1ki.15.27) is Nadab's."""
    assert "death" not in _node(doc, "約蘭", "I")["fields"]
    assert "death" not in _node(doc, "亞哈謝", "J")["fields"]
    assert _node(doc, "拿答")["fields"]["death"] == ["killed", "1ki.15.27", "usurp"]
    assert _node(doc, "以拉")["fields"]["death"] == ["killed", "1ki.16.10", "usurp"]


@needs_text
@pytest.mark.parametrize("kd, pred, succ, typ, verse", [
    ("I", "耶羅波安", "拿答", "son", "1ki.14.20"),           # R2: the death formula with a pronoun subject
    ("I", "心利", "暗利", "people", "1ki.16.16"),             # R3: the people make him king
    ("I", "約蘭", "耶戶", "usurp", "2ki.9.14"),               # R4: X rebels against Y
    ("I", "約阿施", "耶羅波安", "son", "2ki.14.16"),          # R6: a typed edge replaces the seat edge
    ("J", "亞哈謝", "亞她利雅", "queen_usurp", "2ki.11.3"),   # R1c: the king's mother seizes the throne
    ("J", "亞她利雅", "約阿施", "restored", "2ki.11.12"),     # R5: the line is restored
    ("J", "約哈斯", "約雅敬", "installed", "2ki.23.34"),      # R7: installed over the reigning king
])
def test_the_fixed_succession_edges_are_typed_at_their_verse(doc, view, kd, pred, succ, typ, verse):
    ch = view.chain[kd]
    pairs = [(a, b) for a, b in zip(ch, ch[1:])
             if view.nodes[a]["name"] == pred and view.nodes[b]["name"] == succ]
    assert len(pairs) == 1, (pred, succ)
    assert [e[2:] for e in doc["edges"] if tuple(e[:2]) == pairs[0]] == [[typ, verse]]


@needs_text
def test_no_fallback_edge_and_no_ghost_node_in_a_kingdom(doc):
    """Every chain step has a typed edge, and no node of Israel or Judah lacks both an accession
    and a reign length (R9: a foreign king's succession, 2ki.19.37, is not Judah's)."""
    assert doc["fallback_edges"] == []
    assert [n["id"] for n in doc["nodes"] if n["kingdom"] in regnal.KINGDOMS
            and not (n["has_acc"] or "reign" in n["fields"])] == []
    assert {n["kingdom"] for n in doc["nodes"]} <= {"I", "J", "U"}
    assert not [n for n in doc["nodes"] if n["name"] == "以撒哈頓"]
    assert ["skip_unanchored_succ", "2ki.19.37", "以撒哈頓"] in doc["log"]


@needs_text
def test_the_three_conflicts_are_the_kings_chronicles_disagreements(doc):
    """R10 drops the two dated events read as reign lengths, R11 the two names of one father,
    R12 the mother description inside the other; three real Kings/Chronicles readings stay."""
    got = sorted((c[1], c[2], c[3][1], c[4][1]) for c in doc["conflicts"])
    assert got == [("亞哈謝", "age", "2ki.8.26", "2ch.22.2"), ("希西家", "mother", "2ki.18.2", "2ch.29.1"),
                   ("約雅斤", "age", "2ki.24.8", "2ch.36.9")]
    assert [e[1] for e in doc["log"] if e[0] == "reign_date_skipped"] == ["2ch.16.12", "2ch.35.19"]
    assert _node(doc, "亞撒")["fields"]["reign"][:2] == [41, "1ki.15.10"]
    assert _node(doc, "約西亞")["fields"]["reign"][:2] == [31, "2ki.22.1"]


@needs_text
def test_the_synchronisms_are_31_of_which_28_accession(doc):
    assert len(doc["syncs"]) == 31 and sum(s[4] == "acc" for s in doc["syncs"]) == 28


def _ref_chain(rows, kd):
    return [r for r in rows if r["kingdom"] == kd]   # the file is in succession order


def _keyed(names):
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append((n, seen[n]))
    return out


def _succ_rows(names):
    ks = _keyed(names)
    return {(x, k): ks[i + k] for i, x in enumerate(ks) for k in (-3, -2, -1, 1, 2, 3) if 0 <= i + k < len(ks)}


@pytest.fixture(scope="module")
def ref_v2():
    return json.loads(REF_V2.read_text(encoding="utf-8"))


@needs_ref_v2
@pytest.mark.parametrize("kd, rows", [("J", 108), ("I", 102)])
def test_the_succession_rows_are_the_reference_layers(view, ref_v2, kd, rows):
    auto = _succ_rows(view.chain_names()[kd])
    ref = _succ_rows([r["name"] for r in _ref_chain(ref_v2, kd)])
    assert len(auto) == len(ref) == rows
    assert [key for key in auto if ref.get(key) != auto[key]] == []


@needs_ref_v2
@pytest.mark.parametrize("kd", regnal.KINGDOMS)
def test_the_chain_edge_types_are_the_reference_layers(view, ref_v2, kd):
    ch, ref = view.chain[kd], _ref_chain(ref_v2, kd)
    assert [view.nodes[x]["name"] for x in ch] == [r["name"] for r in ref]
    assert ref[0]["pred"][:2] == [None, "founder"]
    want = [b["pred"][1] if b["pred"] and b["pred"][0] == a["id"] else None for a, b in zip(ref, ref[1:])]
    assert [view.edge_type.get(p) for p in zip(ch, ch[1:])] == want


@needs_ref_v2
def test_the_synchronisms_are_the_reference_layers(view, ref_v2):
    ids = {x: r["id"] for kd in regnal.KINGDOMS for x, r in zip(view.chain[kd], _ref_chain(ref_v2, kd))}
    auto = sorted((ids[n], ids[o], y, v, p) for (n, o, y, v, p) in view.syncs)
    ref = sorted((r["id"], o, y, v, kind == "primary") for r in ref_v2 for (o, y, v, kind) in r["sync"])
    assert len(auto) == 31 and auto == ref


@needs_text
def test_g_regnal_passes_the_audited_layer(files, expect):
    gate = check_regnal(files["regnal_layer.json"], json.loads(files["regnal_report.json"]),
                        {"text": "text@247eafe44b02"}, expect)
    assert gate.passed, gate.details
    assert gate.observed["chains"] == {"I": 19, "J": 20} and gate.observed["conflicts"] == 3


@needs_text
def test_g_regnal_refuses_another_text_layer(files, expect):
    gate = _gate(files["regnal_layer.json"], expect, text_version="text@0123456789ab")
    assert not gate.passed and "audit the layer of this text again" in gate.details[0]


def _mutated(files, change) -> bytes:
    doc = json.loads(files["regnal_layer.json"])
    change(doc)
    return encode_layer(doc)


@needs_text
@pytest.mark.parametrize("change, needle", [
    (lambda d: d["nodes"][3].update(name="某王"), "sha256"),
    (lambda d: d.update(union_classes=[["A01", "A02"]]), "union_classes"),
    (lambda d: d["edges"].append(["A01", "Z99", "son", None]), "names no node"),
    (lambda d: d["conflicts"].pop(), "field conflicts"),
    (lambda d: d["nodes"][0].update(kingdom="X"), "kingdom 'X'"),
])
def test_g_regnal_turns_red_on_any_change_to_the_layer(files, expect, change, needle):
    gate = _gate(_mutated(files, change), expect)
    assert not gate.passed and any(needle in d for d in gate.details), gate.details


@needs_text
def test_g_regnal_wants_the_chains_and_report_it_was_given(files, expect):
    wrong = copy.deepcopy(dict(expect))
    wrong["chains"] = {**wrong["chains"], "J": wrong["chains"]["J"][1:]}
    assert not check_regnal(files["regnal_layer.json"], json.loads(files["regnal_report.json"]),
                            {"text": "text@247eafe44b02"}, wrong).passed
    gate = check_regnal(files["regnal_layer.json"], None, {"text": "text@247eafe44b02"}, expect)
    assert not gate.passed and any("regnal_report.json" in d for d in gate.details)
    assert not check_regnal(None, None, {"text": "text@247eafe44b02"}, expect).passed


@needs_text
@pytest.mark.parametrize("data", [b"[]", b"{}", b'{"policy": "occ"}'])
def test_g_regnal_turns_red_on_a_document_that_is_no_layer(expect, data):
    gate = check_regnal(data, None, {"text": "text@247eafe44b02"}, expect)
    assert not gate.passed and any("not a regnal layer" in d for d in gate.details), gate.details


@needs_text
def test_g_regnal_turns_red_on_malformed_fields(files, expect):
    gate = _gate(_mutated(files, lambda d: d["nodes"][1].update(fields=[])), expect, report={})
    assert not gate.passed


def test_the_expectation_of_a_text_without_regnal_formulas_is_empty_chains():
    doc = {"policy": "occ", "fn_rule": "slot", "nodes": [], "edges": [], "fallback_edges": [],
           "syncs": [], "conflicts": [], "log": [], "occ_alias": [], "union_classes": None}
    data = encode_layer(doc)
    want = expectation_doc(doc, "text@0123456789ab", hashlib.sha256(data).hexdigest())
    assert want["chains"] == {"I": [], "J": []}
    assert _gate(data, want, text_version="text@0123456789ab").passed


def _one_king_doc(kingdom):
    node = {"id": "A00", "kingdom": kingdom, "name": "甲", "aliases": [], "fields": {"reign": [3, "1ki.1.1", "ki"]},
            "evidence": ["1ki.1.1"], "pending": False, "order": 0, "created_by": "reign_named", "has_acc": False}
    return {"policy": "occ", "fn_rule": "slot", "nodes": [node], "edges": [], "fallback_edges": [],
            "syncs": [], "conflicts": [], "log": [], "occ_alias": [], "union_classes": None}


@pytest.mark.parametrize("kingdom, passed", [("U", True), ("J", True), ("X", False), (None, False)])
def test_g_regnal_takes_israel_judah_or_all_israel_for_a_king(kingdom, passed):
    doc = _one_king_doc(kingdom)
    data = encode_layer(doc)
    want = expectation_doc(doc, "text@0123456789ab", hashlib.sha256(data).hexdigest())
    assert _gate(data, want, text_version="text@0123456789ab").passed is passed


def _layer(*nodes):
    A = Layer()
    for kd, name, aliases in nodes:
        A.new(kd, name, "1ki.1.1")["aliases"].extend(aliases)
    return A


def test_two_names_of_one_king_or_a_description_inside_the_other_are_no_conflict():
    """R11, R12; any other second value is still a conflict, and the first value is kept."""
    A = _layer(("J", "甲", []), ("J", "乙", ["丙"]))
    son = A.nodes[0]
    A.setf(son, "father", "乙", "1ki.1.1", "ki")
    A.setf(son, "father", "丙", "1ki.1.2", "ki")
    A.setf(son, "mother_desc", "某地某人的女兒", "1ki.1.1", "ki")
    A.setf(son, "mother_desc", "某人的女兒", "1ki.1.2", "ch")
    assert A.conflicts == []
    A.setf(son, "father", "丁", "1ki.1.3", "ki")
    A.setf(son, "mother_desc", "別人的女兒", "1ki.1.3", "ch")
    assert [(c[2], c[4][0]) for c in A.conflicts] == [("father", "丁"), ("mother_desc", "別人的女兒")]
    assert son["fields"]["father"][0] == "乙"


def test_a_typed_edge_replaces_a_seat_edge_and_the_united_kingdom_flows_nowhere():
    """R6: a seat edge says only who sat next; R8: an edge never copies 'U' to a node."""
    A = _layer(("I", "甲", []), (None, "乙", []), ("U", "丙", []), (None, "丁", []))
    a, b, c, d = A.nodes
    A.add_edge(a, b, "seat", "2ki.1.1")
    A.add_edge(a, b, "son", "2ki.1.2")
    A.add_edge(a, b, "seat", "2ki.1.3")
    assert A.edges == [(a["id"], b["id"], "son", "2ki.1.2")] and b["kingdom"] == "I"
    A.add_edge(c, d, "son", "2ki.1.4")
    A.add_edge(d, c, "son", "2ki.1.5")
    assert d["kingdom"] is None and c["kingdom"] == "U"


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    if not TEXT.is_dir():
        pytest.skip(f"{TEXT.name} not in the store")
    root = tmp_path_factory.mktemp("regnal_store")
    (root / "text").mkdir()
    (root / "text" / TEXT.name).symlink_to(TEXT)
    result = build_regnal(TEXT, root)
    assert result.passed, [g.to_json() for g in result.gates]
    return root, result.layers["relations"]


def test_build_stores_the_layer_and_the_stored_layer_passes_its_gates(stored):
    root, layer = stored
    data = read_layer(layer.path)
    assert data.depends_on == {"text": "text@247eafe44b02"}
    assert set(data.file_shas) >= {"regnal_layer.json", "regnal_report.json"}
    report = gate_layer(layer.path, "relations", [TEXT], inputs=GateInputs())
    assert report.passed, report.to_json()
    again = build_regnal(TEXT, root)
    assert again.layers["relations"].version == layer.version


@needs_served
def test_the_served_layer_is_red_under_the_fixed_expectation_and_green_under_its_own(tmp_path):
    """Moving the expectation off 932d2242 means release, load and verify of b20261019_18aa84ad
    (which carries relations@a04b67a301dc) refuse it: the release gates run G-REGNAL again with
    this expectation (``release.gating``). It fails on the three pins alone (sha, chain J,
    conflicts), so an expectation of its own keeps the old layer verifiable."""
    report = gate_layer(SERVED, "relations", [TEXT], gates=release_gates("relations"), inputs=GateInputs())
    (gate,) = [g for g in report.gates if g.name == "G-REGNAL"]
    assert not gate.passed and len(gate.details) == 3, gate.details
    assert gate.details[0].startswith("regnal_layer.json sha256 932d2242dc3f is not the audited")
    assert gate.details[1].startswith("chain J is ['所羅門', '羅波安'")
    assert gate.details[2] == "7 field conflicts, the expectation 3"
    data = (SERVED / "regnal_layer.json").read_bytes()
    own = expectation_doc(json.loads(data), TEXT.name, hashlib.sha256(data).hexdigest())
    path = tmp_path / "regnal_expect_a04b67a301dc.yaml"
    path.write_text(yaml.safe_dump(own, allow_unicode=True, sort_keys=False), encoding="utf-8")
    again = gate_layer(SERVED, "relations", [TEXT], gates=release_gates("relations"),
                       inputs=GateInputs(regnal_expect=path))
    assert again.passed, again.to_json()
    assert own["conflicts"] == 7 and own["chains"]["J"][0] == "所羅門"


@needs_r2
def test_a_release_without_the_optional_layer_keeps_its_bytes():
    again = rel.read_release(R2, STORE / "layers", default_checks())
    assert again.build_id == "b20261008_e05d3e55"
    assert again.doc["layers"]["relations"] is None and again.doc["contract_version"] == "1.1.0"


@needs_r2
def test_a_release_with_the_regnal_layer_carries_its_contract_file(stored, tmp_path):
    root, layer = stored
    r2 = json.loads(R2.read_text(encoding="utf-8"))
    for name, version in r2["layers"].items():
        if version and name != "text":
            (root / name).mkdir(exist_ok=True)
            link = root / name / version
            if not link.exists():
                link.symlink_to(STORE / "layers" / name / version)
    vectors = STORE / "layers/emb" / f"{r2['layers']['emb']}.vectors"
    if vectors.exists() and not (root / "emb" / vectors.name).exists():
        (root / "emb" / vectors.name).symlink_to(vectors)
    versions = [v for k, v in r2["layers"].items() if v and k != "src"] + [layer.version]
    release = rel.assemble(root, versions, r2["build_date"], default_checks())
    assert release.doc["contract_version"] == "1.2.0"
    assert release.doc["layers"]["relations"] == layer.version
    assert release.doc["contracts"]["regnal_layer.json"] == load_regnal_expect()["layer_sha256"]
    assert {k: v for k, v in release.doc["contracts"].items() if k != "regnal_layer.json"} \
        == r2["contracts"]
    assert {k: v for k, v in release.doc["layer_digests"].items() if k != "relations"} \
        == r2["layer_digests"]
    assert release.build_id != r2["build_id"]
