"""GEN confirmation set: the names file gen_names.json (names_g.py; prereg §5.1, the shared data contract).

Synthetic tests build the file from a made-up Genesis layer, text layer (name_spans, books, manifest) and
routing lexicon in tmp_path: every name in them is made up, and this file shares no 8-character window
with the store's text layer or any real question (GT v1/v2, A's confirm set, stage-0's items; checked
below). The store tests rebuild the real file, compare it with the stored one and check the contract (keys,
the 19 chain persons in order, every name prereg §5.2 rule 4 lists); they assert counts and booleans only
and skip when the store is not mounted. Nothing calls an LLM.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import g_common as GC  # noqa: E402
import names_g as N  # noqa: E402

needs_store = pytest.mark.skipif(not (GC.GEN_LAYER.is_file() and (N.TEXT_DIR / "name_spans.jsonl").is_file()),
                                 reason=f"store not mounted ({GC.GEN_LAYER})")
WINDOW = 8
KEYS = ["schema", "text_digest", "gen_layer_sha256", "chain", "cain_line", "abram_family", "extra_persons",
        "other_books", "lexicon_blockers", "sources"]

# made-up chains: chapter 5 阿岡 > 巴頓 > 卡洛 > 丹恩, chapter 11 伊安 > 杰德 > 柯特 > 麥斯
CH5, CH11 = ("阿岡", "巴頓", "卡洛", "丹恩"), ("伊安", "杰德", "柯特", "麥斯")
SPANS = [("gen.4.1", "阿岡"), ("gen.4.2", "歐文"), ("gen.4.3", "派克"), ("gen.4.5", "諾維‧勒恩"),
         ("gen.5.3", "巴頓"), ("gen.5.9", "賴瑞"), ("gen.10.2", "凱斯"), ("gen.10.4", "伊安"),
         ("gen.11.12", "杰德"), ("gen.11.26", "麥斯"), ("gen.11.26", "羅素"), ("gen.11.27", "柯特"),
         ("gen.11.29", "溫蒂"), ("gen.11.33", "不收"), ("gen.12.1", "也不收"), ("exo.4.1", "歐文")]
BOOKS = [("gen", "某甲記", ["甲"]), ("luk", "某乙福音", ["乙", "某乙"]), ("1ch", "某丙志上", ["丙上", "某丙上"]),
         ("mat", "某丁福音", ["丁"]), ("heb", "某戊書", []), ("jud", "某己書", []), ("rev", "某庚錄", ["庚"])]
LEXICON = ["卡洛斯", "伊安娜", "麥斯", "無關", "大柯特城", "柯特‧森"]


def gen_doc() -> dict:
    nodes = []
    for ch, names in ((5, CH5), (11, CH11)):
        for i, nm in enumerate(names):
            nodes.append({"id": f"G{ch:02d}.{i:02d}", "name": nm, "chapter": ch, "order": i, "sons": [],
                          "fields": {"beget": [30 + i, f"gen.{ch}.{i}"]}, "flood_offset": None})
    return {"schema": "arith.gen_layer.v1", "text_digest": "fake0digest", "nodes": nodes, "edges": [],
            "conflict_edges": [], "derived": {"total": {}}}


@pytest.fixture
def fake(tmp_path) -> dict:
    text = tmp_path / "text"
    text.mkdir()
    (text / "layer_manifest.json").write_text(json.dumps({"digest": "fake0digest"}), encoding="utf-8")
    with (text / "name_spans.jsonl").open("w", encoding="utf-8") as f:
        for i, (c, s) in enumerate(SPANS):
            f.write(json.dumps({"container_id": c, "surface": s, "span_id": f"ns:{c}@{i}"}, ensure_ascii=False) + "\n")
    with (text / "books.jsonl").open("w", encoding="utf-8") as f:
        for b, nm, short in BOOKS:
            f.write(json.dumps({"book_id": b, "name": nm, "short_names": short}, ensure_ascii=False) + "\n")
    lex = tmp_path / "routing_lexicon.json"
    lex.write_text(json.dumps({"names": [{"surface": s, "kind": "name"} for s in LEXICON]
                               + [{"surface": "柯特斯", "kind": "dotless"}]}, ensure_ascii=False), encoding="utf-8")
    layer = tmp_path / "gen_layer.json"
    layer.write_text(json.dumps(gen_doc(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kw = dict(cain_required=("派克", "新名"), abram_required=("溫蒂", "華特"), book_words=("某乙", "某丙志"),
              blocker_extra=("丹恩堡",))
    return dict(layer=layer, text=text, lexicon=lex, kw=kw)


def build(fake: dict) -> dict:
    return N.build(fake["layer"], fake["text"], fake["lexicon"], **fake["kw"])


# ---------------------------------------------------------------- synthetic
def test_the_file_has_exactly_the_contract_keys(fake):
    doc = build(fake)
    assert list(doc) == KEYS and doc["schema"] == "gen_confirm.gen_names.v1"
    assert doc["text_digest"] == "fake0digest" and doc["gen_layer_sha256"] == GC.sha256_file(fake["layer"])


def test_chain_is_the_layers_in_chain_order(fake):
    assert build(fake)["chain"] == [{"id": f"G{ch:02d}.{i:02d}", "name": nm, "chapter": ch}
                                    for ch, names in ((5, CH5), (11, CH11)) for i, nm in enumerate(names)]


def test_cain_line_is_chapter_4_names_off_the_chain_plus_the_rule_4_list_and_dotless_forms(fake):
    assert build(fake)["cain_line"] == sorted({"歐文", "派克", "諾維‧勒恩", "諾維勒恩", "新名"})


def test_abram_family_is_the_verses_26_to_32_of_chapter_11_off_the_chain_plus_the_list(fake):
    assert build(fake)["abram_family"] == sorted({"羅素", "溫蒂", "華特"})


def test_extra_persons_are_chapters_4_5_10_11_and_the_abram_family_minus_the_chain(fake):
    doc = build(fake)
    assert doc["extra_persons"] == sorted({"歐文", "派克", "諾維‧勒恩", "諾維勒恩", "新名", "賴瑞", "凱斯", "羅素",
                                           "溫蒂", "華特", "不收"})
    assert not set(doc["extra_persons"]) & set(CH5 + CH11)


def test_other_books_are_the_five_books_names_and_their_long_abbreviations(fake):
    assert build(fake)["other_books"] == sorted({"某乙福音", "某乙", "某丙志上", "丙上", "某丙上", "某丙志", "某丁福音",
                                                 "某戊書", "某己書"})


def test_lexicon_blockers_are_names_holding_a_chain_name_and_none_plus_the_extras(fake):
    assert build(fake)["lexicon_blockers"] == sorted({"卡洛斯", "伊安娜", "大柯特城", "柯特‧森", "柯特森", "丹恩堡"})


def test_sources_pin_every_input(fake):
    src = build(fake)["sources"]
    assert set(src) == {"gen_layer.json", "name_spans.jsonl", "books.jsonl", "layer_manifest.json",
                        "routing_lexicon.json"}
    assert src["routing_lexicon.json"] == GC.sha256_file(fake["lexicon"])


def test_a_text_layer_other_than_the_layers_is_refused(fake):
    (fake["text"] / "layer_manifest.json").write_text(json.dumps({"digest": "other"}), encoding="utf-8")
    with pytest.raises(SystemExit):
        build(fake)


def test_problems_name_every_missing_required_name(fake):
    doc = build(fake)
    assert N.problems(doc, cain_required=("派克",), abram_required=("溫蒂",), books_required=("某乙",),
                      blockers_required=("卡洛斯",), store=False) == []
    bad = dict(doc, cain_line=["歐文"])
    assert any("cain_line" in p for p in N.problems(bad, cain_required=("派克",), store=False))
    assert any("keys" in p for p in N.problems({k: doc[k] for k in KEYS[:-1]}, store=False))


def test_build_is_deterministic(fake):
    assert json.dumps(build(fake), ensure_ascii=False) == json.dumps(build(fake), ensure_ascii=False)


def test_the_cli_writes_nowhere_but_the_store_folder(tmp_path):
    with pytest.raises(SystemExit):
        GC.write_json(GC.REPO / "gen_names.json", {})
    assert N.OUT == GC.GEN_NAMES


def test_names_g_imports_neither_a_nor_stage0():
    code = (f"import sys; sys.path.insert(0, {str(H)!r}); import names_g; "
            "print(any(m in sys.modules for m in ('c_common', 'x_common', 'engine_x')))")
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["False"]


# ---------------------------------------------------------------- store
@needs_store
def test_real_file_matches_a_rebuild_and_the_contract():
    doc = N.build()
    assert N.problems(doc) == []
    assert GC.GEN_NAMES.is_file() and GC.read_json(GC.GEN_NAMES) == doc
    assert list(doc) == KEYS and doc["text_digest"] == N.TEXT_DIGEST
    assert doc["gen_layer_sha256"].startswith(GC.GEN_LAYER_SHA256_PREFIX)
    gen = GC.read_json(GC.GEN_LAYER)
    order = sorted(gen["nodes"], key=lambda n: (n["chapter"], n["order"]))
    assert [c["id"] for c in doc["chain"]] == [n["id"] for n in order] and len(doc["chain"]) == 19
    assert [c["chapter"] for c in doc["chain"]] == [5] * 10 + [11] * 9


@needs_store
def test_real_lists_hold_every_name_the_prereg_lists():
    doc = GC.read_json(GC.GEN_NAMES)
    chain = {c["name"] for c in doc["chain"]}
    assert set(N.CAIN_REQUIRED) <= set(doc["cain_line"]) and set(N.ABRAM_REQUIRED) <= set(doc["abram_family"])
    assert set(N.BOOKS_REQUIRED) <= set(doc["other_books"]) and set(N.BLOCKERS_REQUIRED) <= set(doc["lexicon_blockers"])
    for k in ("cain_line", "abram_family", "extra_persons", "lexicon_blockers"):
        assert not set(doc[k]) & chain, k
        assert doc[k] == sorted(set(doc[k])), k
    assert set(doc["abram_family"]) <= set(doc["extra_persons"])
    assert all(any(n in b for n in chain) for b in doc["lexicon_blockers"])


def windows(s: str) -> set[str]:
    return {s[i:i + WINDOW] for i in range(len(s) - WINDOW + 1)}


def real_texts() -> dict[str, list[str]]:
    """The verses, GT v1/v2, A's frozen confirm questions and stage-0's item questions (store and repo)."""
    out = {"verses": [json.loads(line)["text"] for line in
                      (N.TEXT_DIR / "verse_units.jsonl").read_text(encoding="utf-8").splitlines()]}
    for f in ("ground_truth.json", "ground_truth.v2.json"):
        out[f] = [q["question"] for q in GC.read_json(GC.REPO / f)["questions"]]
    out["A_confirm"] = [q["question"] for q in
                        GC.read_json(GC.STORE / "reports/kg_cards_20261018/A_confirm/questions_frozen.json")["questions"]]
    out["stage0_items"] = [it["question"] for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"]]
    return out


@needs_store
def test_these_files_share_no_window_with_a_verse_or_a_real_question():
    """repo 不放任何經節字串與真實題目: no 8-character window of names_g.py or this file (as written or NFKC) is in
    a verse or a real question (counts only)."""
    mine = set()
    for p in (Path(__file__), H / "names_g.py"):
        src = p.read_text(encoding="utf-8")
        mine |= windows(src) | windows(N.nfkc(src))
    texts = real_texts()
    hits = {k: sum(bool((windows(t) | windows(N.nfkc(t))) & mine) for t in v) for k, v in texts.items()}
    assert [len(v) > 0 for v in texts.values()] == [True] * 5 and hits == {k: 0 for k in texts}
