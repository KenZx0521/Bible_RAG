"""GD experiment shared module (experiments/2026-10-14_graph_gd/gd_common.py).

Unit tests drive §4 key resolution, the §2 id sha, the confirmation-set guard and the
§10 fingerprint/meta helpers on small in-memory inputs. With the store mounted, the
NEW82 / OLD31 loaders and §4 gold are checked against the prereg numbers and the
archived outputs (PN/questions_valid.json, PO/gold.json, the PO hop_slots interval rule
re-derived here), and the pins against the archived container meta lines.
"""

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# prefixes the prereg text pins (§2, §10)
PREREG_PREFIXES = {"new82_ids": "84985f6d", "old31_ids": "868f75d6", "questions_v5": "4b37e5c3",
                   "usable": "0ade60b8", "api_arms": "7e28ef3b", "vectors": "870ca1fc",
                   "image": "c79266296cb0", "rr_tok": "69564b69", "rr_probe": "0e7683de",
                   "emb_tok": "21106b6d", "emb_probe": "a0e8db60", "rr_rev": "953dc6f6",
                   "emb_rev": "5617a9f6"}


def units(*spans):
    """VerseUnits from (unit_key, v_start, v_end) in order."""
    return gd.VerseUnits(tuple(k for k, _, _ in spans), {k: (a, b) for k, a, b in spans})


GEN = units(("gen.1.1", 1, 1), ("gen.1.2", 2, 2), ("gen.1.3", 3, 3),
            ("gen.2.29", 29, 29), ("gen.24.29-30", 29, 30), ("gen.24.31", 31, 31))
VI = gd.VerseIndex({k: f"ps:{k}" for k in GEN.order},
                   {**{k: () for k in GEN.order}, "gen.1.3": ("ps:gen.1.3b",)})


# ---------------------------------------------------------------- §4 key resolution

def test_a_whole_or_merged_unit_key_resolves_to_itself():
    assert gd.resolve_key("gen.1.2", GEN) == ("gen.1.2",)
    assert gd.resolve_key("gen.24.29-30", GEN) == ("gen.24.29-30",)


def test_a_verse_inside_a_merged_unit_resolves_to_that_unit():
    assert gd.resolve_key("gen.24.30", GEN) == ("gen.24.29-30",)
    assert gd.find_unit("gen.2.30", GEN) is None          # gen.2. is not a prefix of gen.24.


def test_a_range_key_takes_every_unit_between_its_ends_in_canonical_order():
    assert gd.resolve_key("gen.1.1-gen.1.3", GEN) == ("gen.1.1", "gen.1.2", "gen.1.3")


@pytest.mark.parametrize("key", ["1sa.25.1b", "gen.1.1a", "gen.1.1b-gen.1.3"])
def test_half_verse_keys_raise_their_own_error(key):
    with pytest.raises(gd.HalfVerseKeyError):
        gd.resolve_key(key, GEN)


@pytest.mark.parametrize("key", ["gen.9.9", "gen.1", "gen.1.3-gen.1.1", "gen.24.29-31"])
def test_unresolvable_or_reversed_keys_raise_instead_of_giving_empty_gold(key):
    with pytest.raises(gd.GoldError):
        gd.resolve_key(key, GEN)


def test_hop_gold_is_the_union_of_passage_ids_and_split_passage_ids():
    assert gd.hop_gold(["gen.1.2", "gen.1.3"], GEN, VI) == {"ps:gen.1.2", "ps:gen.1.3",
                                                            "ps:gen.1.3b"}
    with pytest.raises(gd.GoldError):
        gd.hop_gold([], GEN, VI)


def test_ids_sha_is_the_sorted_newline_join_without_a_trailing_newline():
    assert gd.ids_sha256(["b", "a"]) == hashlib.sha256(b"a\nb").hexdigest()
    with pytest.raises(gd.IntegrityError):
        gd.ids_sha256(["a", "a"])


# ---------------------------------------------------------------- confirmation-set guard

PREREG_HEAD = "# prereg\n\n## 附錄（只追加，不改前文）\n\n- **附錄 A**（凍結點）：…。待追加。\n"


@pytest.mark.parametrize("tail, a_filled", [
    ("", False),
    ("\n## 附錄 A：凍結\n\n待追加。\n", False),
    ("\n## 附錄 A：凍結\n\n- 本檔 sha …\n", True),
    ("\n## 附錄 AB\n\n- x\n", False),
    ("\n## 附錄 A\n\n- 待追加\n", False),                       # placeholder as a bullet
    ("\n## 附錄 A\n\n（待追加）\n\n**待追加**\n", False),        # in brackets / bold
    ("\n## 附錄 A\n\nTODO\n\n1. TBD\n", False),
    ("\n```\n## 附錄 A\n- sha …\n```\n", False),               # inside a code fence
    ("\n## 附錄 A\n\n```\nx = 1\n```\n", False),               # only a fenced block
    ("\n## 附錄 A\n\n待追加\n\n## 附錄 B\n\n- x\n", False),    # B's content is not A's
])
def test_appendix_counts_only_a_heading_with_real_content(tmp_path, tail, a_filled):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(PREREG_HEAD + tail, encoding="utf-8")
    assert gd.appendix_has_content("A", prereg) is a_filled


def accept_dir(tmp_path, a=True, b=True):
    """An accept/ directory whose accept_a.json / accept_b.json say passed=a / b."""
    d = tmp_path / "accept"
    d.mkdir(exist_ok=True)
    for name, ok in (("accept_a.json", a), ("accept_b.json", b)):
        if ok is not None:
            (d / name).write_text(json.dumps({"passed": ok, "lists_sha256": "L" * 64}), encoding="utf-8")
    return d


def test_confirmation_sets_stay_locked_until_their_appendices_exist(tmp_path):
    prereg, acc = tmp_path / "prereg.md", accept_dir(tmp_path)
    prereg.write_text(PREREG_HEAD, encoding="utf-8")
    gd.assert_set_allowed("new82", prereg, acc)
    for name in ("old31", "ho", "gtv2", "nope"):
        with pytest.raises(gd.ConfirmationLockedError):
            gd.assert_set_allowed(name, prereg, acc)
    prereg.write_text(PREREG_HEAD + "\n## 附錄 A\n\n- sha …\n", encoding="utf-8")
    gd.assert_set_allowed("old31", prereg, acc)
    with pytest.raises(gd.ConfirmationLockedError, match="B"):
        gd.assert_set_allowed("ho", prereg, acc)


@pytest.mark.parametrize("a, b", [(True, False), (False, True), (True, None), (None, None)])
def test_a_filled_appendix_a_still_needs_both_acceptance_files_passed(tmp_path, a, b):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(PREREG_HEAD + "\n## 附錄 A\n\n- sha …\n", encoding="utf-8")
    acc = accept_dir(tmp_path, a, b)
    gd.assert_set_allowed("new82", prereg, acc)
    with pytest.raises(gd.ConfirmationLockedError, match="accept_"):
        gd.assert_set_allowed("old31", prereg, acc)


@pytest.mark.parametrize("b_doc", [{"passed": True, "pinned": False, "lists_sha256": "L" * 64},
                                   {"passed": True, "lists_sha256": "X" * 64},
                                   {"passed": True}])
def test_acceptance_b_must_be_pinned_and_on_the_lists_of_acceptance_a(tmp_path, b_doc):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(PREREG_HEAD + "\n## 附錄 A\n\n- sha …\n", encoding="utf-8")
    acc = accept_dir(tmp_path)
    (acc / "accept_b.json").write_text(json.dumps(b_doc), encoding="utf-8")
    with pytest.raises(gd.ConfirmationLockedError, match="accept_"):
        gd.assert_set_allowed("old31", prereg, acc)


def _accepted():
    docs = [json.loads((gd.ACCEPT_DIR / n).read_text(encoding="utf-8"))
            for n in gd.ACCEPT_FILES if (gd.ACCEPT_DIR / n).is_file()]
    return len(docs) == len(gd.ACCEPT_FILES) and all(
        d.get("passed") is True and d.get("pinned", True) is True for d in docs) and len(
        {d.get("lists_sha256") for d in docs} - {None}) == 1 and all(d.get("lists_sha256") for d in docs)


def test_the_registered_prereg_locks_exactly_the_sets_whose_appendices_are_empty():
    filled = {a: gd.appendix_has_content(a) for a in ("A", "B")}
    for name, needs in gd.SET_REQUIRES.items():
        if all(filled[a] for a in needs) and (not needs or _accepted()):
            gd.assert_set_allowed(name)
        else:
            with pytest.raises(gd.ConfirmationLockedError):
                gd.assert_set_allowed(name)


# ---------------------------------------------------------------- §10 fingerprints and meta

def test_pins_start_with_the_prefixes_written_in_the_prereg():
    text = gd.PREREG_PATH.read_text(encoding="utf-8")
    pins = {"rr_tok": gd.FINGERPRINTS["reranker"]["tokenizer_sha"],
            "rr_probe": gd.FINGERPRINTS["reranker"]["probe_ids_sha"],
            "emb_tok": gd.FINGERPRINTS["embedder"]["tokenizer_sha"],
            "emb_probe": gd.FINGERPRINTS["embedder"]["probe_ids_sha"],
            "rr_rev": gd.REVISIONS["reranker"], "emb_rev": gd.REVISIONS["embedder"],
            "vectors": gd.VECTORS_SHA256, "image": gd.IMAGE_ID.removeprefix("sha256:"),
            "new82_ids": gd.IDS_SHA256["new82"], "old31_ids": gd.IDS_SHA256["old31"],
            "questions_v5": gd.FILE_SHA256[gd.NEW82_FILE], "usable": gd.FILE_SHA256[gd.OLD31_FILE],
            "api_arms": gd.FILE_SHA256[gd.OLD31_API]}
    for name, prefix in PREREG_PREFIXES.items():
        assert pins[name].startswith(prefix) and prefix in text, name
    assert (gd.FINGERPRINTS["reranker"]["unk_count"], gd.FINGERPRINTS["embedder"]["unk_count"]) \
        == (2, 3)
    assert gd.BUILD_ID in text and all(v in text for v in gd.LAYER_VERSIONS.values())


def test_verify_fingerprint_needs_every_pinned_key_and_a_matching_revision():
    good = gd.expected_fingerprint("reranker")
    gd.verify_fingerprint("reranker", good)
    gd.verify_fingerprint("reranker", {k: v for k, v in good.items() if k != "revision"})
    for bad in ({**good, "unk_count": 3}, {**good, "revision": "0" * 40},
                {k: v for k, v in good.items() if k != "probe_ids_sha"}):
        with pytest.raises(gd.IntegrityError):
            gd.verify_fingerprint("reranker", bad)


def test_verify_container_meta_checks_the_build_and_the_kinds_fingerprint():
    line = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu",
            "embedder_fingerprint": dict(gd.FINGERPRINTS["embedder"])}
    gd.verify_container_meta(line, "embedder")
    for bad in ({**line, "build_id": "b20261008_6daa4f31"}, {**line, "device": "cuda"},
                {k: v for k, v in line.items() if k != "device"}):
        with pytest.raises(gd.IntegrityError):
            gd.verify_container_meta(bad, "embedder")
    with pytest.raises(gd.IntegrityError):
        gd.verify_container_meta(line, "reranker")


def test_strict_container_meta_also_needs_the_run_settings():
    line = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu", "batch": 16, "torch_threads": 12,
            "reranker_fingerprint": gd.expected_fingerprint("reranker")}
    gd.verify_container_meta(line, "reranker", strict=True)
    gd.verify_container_meta({k: v for k, v in line.items() if k != "batch"}, "reranker")
    for over in ({"batch": 99}, {"torch_threads": 1}, {"device": "cuda"}):
        with pytest.raises(gd.IntegrityError):
            gd.verify_container_meta({**line, **over}, "reranker", strict=True)


def test_collect_meta_records_the_environment_pins_and_file_shas(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "1")
    meta = gd.collect_meta({"prereg copy": gd.PREREG_PATH}, batch=16)
    assert meta["pythonhashseed"] == "1" and meta["batch"] == 16
    assert meta["sha256"]["prereg copy"] == meta["sha256"]["prereg.md"]
    assert set(meta["sha256"]) >= {"gd_common.py", "_gd_store.py", "_gd_sets.py", "_gd_pool.py"}
    assert meta["blas"] and all("num_threads" in b and b["name"] for b in meta["blas"])
    assert (meta["build_id"], meta["layers"]) == (gd.BUILD_ID, dict(gd.LAYER_VERSIONS))
    with pytest.raises(gd.GdError):
        gd.collect_meta(build_id="other")


# ---------------------------------------------------------------- store: archived meta lines

def _meta_line(path):
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.readline())


@needs_store
def test_pinned_fingerprints_are_the_archived_container_meta_lines():
    rr, emb = _meta_line(gd.EV / "ev_sel_out.jsonl"), _meta_line(gd.PN / "encode_out.jsonl")
    assert rr["reranker_fingerprint"] == dict(gd.FINGERPRINTS["reranker"])
    assert emb["embedder_fingerprint"] == dict(gd.FINGERPRINTS["embedder"])
    gd.verify_container_meta(rr, "reranker")
    gd.verify_container_meta(emb, "embedder")
    layer_fp = json.loads((gd.LAYERS_ROOT / "emb" / gd.LAYER_VERSIONS["emb"]
                           / "encoder_fingerprint.json").read_text(encoding="utf-8"))
    assert layer_fp["reranker"]["revision"] == gd.REVISIONS["reranker"]
    assert layer_fp["bge_m3"]["revision"] == gd.REVISIONS["embedder"]


# ---------------------------------------------------------------- store: layers

def test_a_layer_version_missing_from_the_store_is_an_integrity_error(tmp_path):
    with pytest.raises(gd.IntegrityError, match="not in the store"):
        gd.load_passages(tmp_path)
    with pytest.raises(gd.IntegrityError, match="missing"):
        gd.read_pinned(tmp_path / "none.json", "0" * 64)


@needs_store
def test_layers_load_with_the_prereg_counts():
    assert len(gd.load_passages()) == gd.N_PASSAGES == 2773
    assert [p.row for p in gd.load_passages()] == list(range(2773))
    emb = gd.load_emb()
    assert emb.matrix.shape == (34058, 1024) and not emb.matrix.flags.writeable
    assert len(emb.row_pids) == 34058 and len(set(emb.row_pids)) == 2773
    assert len(gd.load_verse_index().passage_of) == len(gd.load_verse_units().order) == 31021
    assert (len(gd.load_book_names()), len(gd.load_query_aliases())) == (66, 17)
    assert len(gd.load_kg0_names()) == 2926


@needs_store
def test_body_spans_give_the_prereg_bip_graph_size():
    vi = gd.load_verse_index().passage_of
    spans = gd.load_body_spans()
    edges = {(vi[s.container_id], s.norm_key) for s in spans}
    assert len({s.norm_key for s in spans}) == 2929 and len(edges) == 16616


# ---------------------------------------------------------------- store: question sets and gold

@needs_store
def test_new82_matches_the_prereg_counts_and_the_archived_gold():
    s = gd.load_new82()
    assert (len(s.questions), s.n_hops, s.ids_sha256[:8]) == (82, 223, "84985f6d")
    rows = json.loads((gd.PN / "questions_valid.json").read_text(encoding="utf-8"))
    valid = {r["id"]: r["gold"] for r in rows}
    assert list(valid) == list(s.ids)
    same = [set(valid[q.qid][h]) == gold for q in s.questions
            for h, gold in enumerate(gd.question_gold(q))]
    assert (sum(same), len(same)) == (223, 223)
    missing = [len(q.missing_hops) for q in s.questions]
    assert (sum(missing), sum(m > 0 for m in missing)) == (102, 63)
    counts = Counter(q.category for q in s.questions)
    assert [counts[c] for c in gd.CATEGORIES] == [13, 14, 12, 34, 9]


def _canon_pos():
    """Canon.pos of E7/reenable/common.py: unit order, then slot -> unit, then a/b half -> verse."""
    text = gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"]
    order = {k: i for i, k in enumerate(gd.load_verse_units().order)}
    with open(text / "verse_slots.jsonl", encoding="utf-8") as fh:
        slot_unit = {r["slot_key"]: r["unit_key"] for r in map(json.loads, fh)}

    def pos(key):
        if key in order:
            return order[key]
        if slot_unit.get(key) in order:
            return order[slot_unit[key]]
        return pos(key[:-1]) if key[-1:] in ("a", "b") and key[-2:-1].isdigit() else None
    return pos


@needs_store
def test_old31_gold_matches_the_po_hop_slots_rule_on_all_101_hops():
    s = gd.load_old31()
    assert (len(s.questions), s.n_hops, s.ids_sha256[:8]) == (31, 101, "868f75d6")
    pos = _canon_pos()
    spans = [(p.passage_id, pos(p.start_key), pos(p.end_key)) for p in gd.load_passages()]
    po = json.loads((gd.PO / "gold.json").read_text(encoding="utf-8"))
    assert list(po) == list(s.ids)
    same_rule = same_po = n_po = 0
    for q in s.questions:
        assert {int(h) for h in po[q.qid]["missing"]} == q.prod_d5_missing
        for h, gold in enumerate(gd.question_gold(q)):
            rule = {pid for slot in q.hops[h] for pid, a, b in spans
                    if a is not None and b is not None and a <= pos(slot) <= b}
            same_rule += rule == gold
            if str(h) in po[q.qid]["missing"]:
                n_po += 1
                same_po += set(po[q.qid]["missing"][str(h)]["gold_pids"]) == gold
    assert (same_rule, same_po, n_po) == (101, 58, 58)


@needs_store
def test_old31_categories_and_prod_d5_missing_hops():
    s = gd.load_old31()
    counts = Counter(q.category for q in s.questions)
    assert [counts[c] for c in gd.CATEGORIES] == [7, 9, 4, 10, 1]
    assert sum(len(q.prod_d5_missing) for q in s.questions) == 58      # §4 另附 prod D5
    assert all(q.missing_hops is None for q in s.questions)            # §4 缺跳 = D5≈, from scores
    assert all(q.core is None and q.shortcut is None for q in s.questions)


@needs_store
def test_question_files_hash_to_the_prereg_prefixes():
    got = {p.name: gd.file_sha256(p)[:8] for p in (gd.NEW82_FILE, gd.OLD31_FILE, gd.OLD31_API)}
    assert got == {"questions_v5.json": "4b37e5c3", "usable.json": "0ade60b8",
                   "api_arms.json": "7e28ef3b"}
    ids = {n: (gd.X_DATA / f"{n}_ids.txt").read_bytes() for n in ("new82", "old31")}
    assert hashlib.sha256(ids["new82"]).hexdigest() == gd.load_new82().ids_sha256
    assert hashlib.sha256(ids["old31"]).hexdigest() == gd.load_old31().ids_sha256


@needs_store
def test_neither_set_has_a_split_unit_in_its_gold():
    vu, vi = gd.load_verse_units(), gd.load_verse_index()
    split = [u for s in (gd.load_new82(), gd.load_old31()) for q in s.questions for h in q.hops
             for key in h for u in gd.resolve_key(key, vu) if vi.split_of[u]]
    assert split == []
