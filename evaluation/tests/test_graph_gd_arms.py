"""GD experiment arms (experiments/2026-10-14_graph_gd/arms.py and its _gd_lex.py).

Unit tests drive prereg §3 on small synthetic inputs: the PPR iteration (hand values and
the converged linear-system solution), the (-round(r, 12), row) sort key, dense ranking
ties, CJK-bigram BM25 with **n** verse markers, LEXPRF's q(t), the four G name-linking
steps, no padding of short extras, the record-level R20 list (§4 D5≈ input), the
vector-file reader and the confirmation-set guard. With the store mounted, the bip graph
counts and the NEW82 lists are checked against the prereg numbers and the archived EV/AT
prf_lists.json, PN/rr_d5_in.json and FM/gd_hub.json (驗收 A), and the CLI's output and meta.
"""

import base64
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
_ARMS_SPEC = importlib.util.spec_from_file_location("gd_arms", _DIR / "arms.py")
arms = importlib.util.module_from_spec(_ARMS_SPEC)
sys.modules["gd_arms"] = arms                       # dataclasses resolve the module by name
_ARMS_SPEC.loader.exec_module(arms)
lex = sys.modules["_gd_lex"]

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# p0 - n0 - p1 - n1, p2 has no name (dangling)
TINY = arms.build_bip(["p0", "p1", "p2"], [("p1", "n1"), ("p0", "n0"), ("p1", "n0")])


# ---------------------------------------------------------------- bip graph and PPR

def test_bip_nodes_are_passages_in_row_order_then_sorted_names():
    assert TINY.passages == ("p0", "p1", "p2") and TINY.names == ("n0", "n1")
    assert TINY.n_edges == 3 and list(TINY.deg) == [1, 2, 0, 2, 1]
    pairs = list(zip(TINY.src.tolist(), TINY.dst.tolist(), strict=True))
    assert pairs == sorted(pairs)
    with pytest.raises(gd.GdError):
        arms.build_bip(["p0"], [("p9", "n0")])


def test_ppr_matches_hand_computed_iterations():
    assert arms.ppr(TINY, {0: 1.0}, iters=1).tolist() == [0.5, 0.0, 0.0]
    # r1 = (p0 .5, n0 .5); P^T r1 = (p0 .25, p1 .25, n0 .5); r2 = .5 e + .5 P^T r1
    assert arms.ppr(TINY, {0: 1.0}, iters=2).tolist() == [0.625, 0.125, 0.0]


def test_dangling_mass_goes_back_to_the_seed_distribution():
    assert arms.ppr(TINY, {2: 1.0}, iters=7).tolist() == [0.0, 0.0, 1.0]


def test_seed_weights_are_normalised_and_empty_seeds_raise():
    np.testing.assert_array_equal(arms.ppr(TINY, {0: 2.0, 1: 6.0}), arms.ppr(TINY, {0: 0.25, 1: 0.75}))
    with pytest.raises(gd.GdError):
        arms.ppr(TINY, {})


def test_ppr_converges_to_the_linear_system_solution():
    rng = np.random.default_rng(7)
    passages = [f"p{i}" for i in range(8)]
    edges = {(passages[i], f"n{j}") for i in range(6) for j in range(4) if rng.random() < 0.5}
    g = arms.build_bip(passages, edges)                      # p6, p7 dangling
    seeds = {0: 0.3, 3: 0.2, 7: 0.5}
    n, alpha = g.n_nodes, arms.PPR_ALPHA
    e = np.zeros(n)
    e[list(seeds)] = list(seeds.values())
    pt = np.zeros((n, n))
    for u, v in zip(g.src, g.dst, strict=True):
        pt[v, u] += 1.0 / g.deg[u]
    dangling = (g.deg == 0).astype(float)
    exact = np.linalg.solve(np.eye(n) - (1 - alpha) * (pt + np.outer(e, dangling)), alpha * e)
    np.testing.assert_allclose(arms.ppr(g, seeds, iters=200), exact[:g.n_pass], atol=1e-13)
    assert math.isclose(exact.sum(), 1.0)


def test_ppr_order_ranks_by_rounded_score_then_row_and_drops_tiny_scores():
    scores = np.array([0.3, 0.3 + 1e-14, 0.5, 1e-12, 2e-12, 0.0, 0.3 + 2e-12])
    assert arms.ppr_order(scores) == [2, 6, 0, 1, 4]


def test_extra_skips_the_base_and_duplicates_and_is_never_padded():
    assert arms.take_extra(["a", "b", "a", "c"], {"b"}) == ["a", "c"]
    assert arms.take_extra([f"p{i}" for i in range(30)], set(), n=10) == [f"p{i}" for i in range(10)]


def test_scaled_weights_sum_to_the_mass():
    assert arms.scaled({"a": 1.0, "b": 3.0}, 0.5) == {"a": 0.125, "b": 0.375}


# ---------------------------------------------------------------- dense D(q)

def test_dense_takes_each_passages_best_record_and_breaks_ties_by_pid():
    matrix = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8], [0.0, 1.0]], dtype=np.float32)
    dense = arms.build_dense(matrix, ["pb", "pc", "pb", "pa"])
    # cos with (0, 1): pb = max(0, .8), pc = 1, pa = 1 (tie with pc -> sorted pid first)
    assert dense.ranking(np.array([0.0, 1.0], dtype=np.float32)) == ("pa", "pc", "pb")
    assert dense.matrix.dtype == np.float64 and not dense.matrix.flags.writeable
    assert matrix.flags.writeable                             # the caller's array is untouched


# ---------------------------------------------------------------- L / LEXPRF

def test_bigrams_stay_inside_cjk_runs_and_verse_markers_split_runs():
    assert arms.bigrams("起初，上帝創造天地。") == ["起初", "上帝", "帝創", "創造", "造天", "天地"]
    assert arms.bigrams("A天B地C 1") == []
    assert arms.passage_bigrams("**1** 天地**2**地是**3-4**是的**5a**的確") == [
        "天地", "地是", "是的", "的確"]


def bm25_term(idf, f, length, avgdl):
    return idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * length / avgdl))


def test_bm25_uses_k1_b_avgdl_and_the_plus_one_idf():
    bm = arms.build_bm25(["a", "b", "c"], ["天地", "天天地", "人"])
    assert bm.length == (1, 2, 0) and bm.avgdl == 1.0
    idf = {"天地": math.log(1 + 1.5 / 2.5), "天天": math.log(1 + 2.5 / 1.5)}      # N = 3, df 2 and 1
    assert bm.idf == idf
    got = bm.scores({"天地": 1.0, "天天": 2.0, "無無": 5.0})
    b_score = bm25_term(idf["天地"], 1, 2, 1.0) + 2 * bm25_term(idf["天天"], 1, 2, 1.0)
    assert got == pytest.approx({0: bm25_term(idf["天地"], 1, 1, 1.0), 1: b_score})
    assert arms.by_score(bm, got, range(3)) == ["b", "a", "c"]


def test_lexprf_query_mixes_question_tf_and_top_feedback_terms():
    bm = arms.build_bm25(["a", "b", "c"], ["天地天地", "地人", "人人"])
    q = arms.lexprf_query(bm, "天地人", [0, 1])
    fb = defaultdict(float)
    for rank, i in enumerate([0, 1]):
        for t, f in bm.tf[i].items():
            fb[t] += (1 / (rank + 1)) * f / bm.length[i] * bm.idf[t]
    z = sum(fb.values())
    want = {"天地": 0.25 + 0.5 * fb["天地"] / z, "地人": 0.25 + 0.5 * fb["地人"] / z,
            "地天": 0.5 * fb["地天"] / z}
    assert list(q) == ["天地", "地人", "地天"]                  # question terms first
    assert q == pytest.approx(want) and sum(q.values()) == pytest.approx(1.0)


def test_lexprf_feedback_cut_breaks_ties_by_term(monkeypatch):
    bm = arms.build_bm25(["a", "b"], ["甲乙丙", "丁"])          # 甲乙, 乙丙 tie in fb
    monkeypatch.setattr(lex, "LEXPRF_TERMS", 1)
    assert list(arms.lexprf_query(bm, "", [0])) == ["乙丙"]     # 乙 (U+4E59) < 甲 (U+7532)


# ---------------------------------------------------------------- G name linking

def names(*rows):
    return tuple(gd.Kg0Name(key, tuple(surfaces)) for key, *surfaces in rows)


def test_book_masks_add_long_upper_lower_stems_and_sort_by_length_then_string():
    assert arms.book_masks(["創世記", "列王紀上", "王上下"]) == ("列王紀上", "列王紀", "創世記", "王上下")


def test_surf_table_keeps_row_order_skips_short_surfaces_and_aliases_only_fill_gaps():
    table = arms.surf_table(names(("亞伯拉罕", "亞伯蘭", "亞"), ("撒拉", "撒萊")),
                            [("亞伯蘭", "別人"), ("撒拉氏", "撒拉")])
    assert list(table.items()) == [("亞伯蘭", "亞伯拉罕"), ("亞伯拉罕", "亞伯拉罕"),
                                   ("撒萊", "撒拉"), ("撒拉", "撒拉"), ("撒拉氏", "撒拉")]
    with pytest.raises(gd.IntegrityError):
        arms.surf_table(names(("甲", "約翰"), ("乙", "約翰")), [])


def test_linking_is_longest_first_without_overlap_and_ordered_by_position():
    linker = arms.build_linker([], names(("亞伯", "亞伯"), ("亞伯拉罕", "亞伯拉罕"), ("撒拉", "撒拉")), [])
    assert linker.link("撒拉是亞伯拉罕的妻子，亞伯是另一人，撒拉") == ("撒拉", "亞伯拉罕", "亞伯")


def test_equal_length_surfaces_follow_table_insertion_order():
    text = "撒母耳膏掃羅以後"
    first = arms.build_linker([], names(("掃羅", "掃羅"), ("羅以", "羅以")), [])
    second = arms.build_linker([], names(("羅以", "羅以"), ("掃羅", "掃羅")), [])
    assert first.link(text) == ("掃羅",) and second.link(text) == ("羅以",)


def test_book_names_and_their_stems_are_masked_before_linking():
    linker = arms.build_linker(["撒母耳記上"], names(("撒母耳", "撒母耳")), [])
    assert linker.link("撒母耳記上說") == () and linker.link("撒母耳記載") == ()
    assert linker.link("撒母耳記上記撒母耳") == ("撒母耳",)


# ---------------------------------------------------------------- arms on a synthetic world

def world():
    """25 passages ranked p00..p24 by dense; seeds reach p21 (亞當) and p22 (夏娃) only;
    該隱 links p20 and p24; LEXPRF terms hit p20 and p23 only."""
    pids = [f"p{i:02d}" for i in range(25)]
    matrix = np.diag(np.linspace(1.0, 0.04, 25)).astype(np.float32)
    edges = [("p00", "亞當"), ("p21", "亞當"), ("p05", "夏娃"), ("p22", "夏娃"),
             ("p20", "該隱"), ("p24", "該隱")]
    contents = ["起初神創造"] * 20 + ["該隱殺了亞伯", "日月星辰", "日月星辰", "該隱", "日月星辰"]
    linker = arms.build_linker([], names(("亞當",), ("夏娃",), ("該隱",), ("亞伯",)), [])
    ctx = arms.ArmContext(arms.build_dense(matrix, pids), arms.build_bip(pids, edges), linker,
                          arms.build_bm25(pids, contents))
    return ctx, np.ones(25, dtype=np.float32)


def test_short_extras_stay_short_and_pools_can_hold_fewer_than_30():
    ctx, vec = world()
    out = ctx.lists("該隱是誰", vec)
    assert out["D30"] == [f"p{i:02d}" for i in range(25)] and out["C"] == out["D30"][20:]
    assert out["R20"] == out["D30"][:20]                          # one record per passage here
    assert out["GD"] == ["p21", "p22"] and out["GD_DEGNORM"] == ["p21", "p22"]
    assert set(out["G"]) == {"p20", "p21", "p22", "p24"}
    assert out["L"][:2] == ["p23", "p20"] and sorted(out["L"]) == out["C"]
    assert sorted(out["LEXPRF"]) == ["p20", "p23"]
    sizes = arms.pool_sizes({"q": out})["q"]
    assert sizes == {"C": 25, "GD": 22, "GD_DEGNORM": 22, "G": 24, "L": 25, "LEXPRF": 22}


def test_r20_is_the_deduplicated_passages_of_the_top_20_records_in_record_order():
    # 24 records: p0 owns rows 0-3, p1 rows 4-5, then one passage per row; cosine falls by row
    row_pids = ["p0"] * 4 + ["p1"] * 2 + [f"q{i:02d}" for i in range(18)]
    matrix = np.diag(np.linspace(1.0, 0.1, 24)).astype(np.float32)
    dense = arms.build_dense(matrix, row_pids)
    rank, r20 = dense.search(np.ones(24, dtype=np.float32))
    assert r20 == ("p0", "p1", *[f"q{i:02d}" for i in range(14)])      # rows 0-19 → 16 passages
    assert rank[:3] == ("p0", "p1", "q00") and set(r20) <= set(rank[:20])


def test_g_falls_back_to_gd_when_the_question_links_no_bip_name():
    ctx, vec = world()
    out = ctx.lists("亞伯是誰", vec)                            # 亞伯 is a kg0 name without body spans
    assert ctx.question_names("亞伯是誰") == () and out["G"] == out["GD"]


# ---------------------------------------------------------------- vectors and the guard

def encode_file(tmp_path, sids, meta=None):
    meta = meta or {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu",
                    "embedder_fingerprint": dict(gd.FINGERPRINTS["embedder"])}
    vec = base64.b64encode(np.full(gd.EMB_DIM, 0.5, dtype=np.float32).tobytes()).decode()
    rows = [meta] + [{"type": "q", "sid": s, "vec_b64": vec} for s in sids]
    path = tmp_path / "enc.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_vector_file_takes_question_sids_in_either_format(tmp_path):
    vecs, meta = arms.load_query_vectors(encode_file(tmp_path, ["A|Q", "A|ROLE1", "B"]), ["A", "B"])
    assert sorted(vecs) == ["A", "B"] and vecs["A"].shape == (gd.EMB_DIM,)
    assert meta["build_id"] == gd.BUILD_ID


@pytest.mark.parametrize("sids, meta", [
    (["A|Q"], None),                                                    # B missing
    (["A", "A|Q", "B"], None),                                          # A twice
    (["A", "B"], {"type": "meta", "build_id": "other", "embedder_fingerprint": {}}),
    (["A", "B"], {"type": "meta", "build_id": gd.BUILD_ID, "device": "cuda",
                  "embedder_fingerprint": dict(gd.FINGERPRINTS["embedder"])}),
])
def test_vector_file_problems_raise(tmp_path, sids, meta):
    with pytest.raises(gd.IntegrityError):
        arms.load_query_vectors(encode_file(tmp_path, sids, meta), ["A", "B"])


def test_the_guard_runs_before_anything_is_read(tmp_path, monkeypatch):
    def locked(name, prereg=gd.PREREG_PATH):
        raise gd.ConfirmationLockedError(name)

    def boom(*a, **k):
        raise AssertionError("read before the guard")

    monkeypatch.setattr(gd, "assert_set_allowed", locked)
    monkeypatch.setattr(gd, "load_question_set", boom)
    monkeypatch.setattr(arms, "load_context", boom)
    with pytest.raises(gd.ConfirmationLockedError):
        arms.main(["--set", "old31", "--vectors", str(tmp_path / "none"), "--out", str(tmp_path / "o")])
    assert not (tmp_path / "o").exists()


@pytest.mark.skipif(gd.appendix_has_content("A"), reason="prereg appendix A is filled")
@pytest.mark.parametrize("name", ["old31", "ho"])
def test_confirmation_sets_are_refused_while_appendix_a_is_pending(tmp_path, name):
    with pytest.raises(gd.ConfirmationLockedError, match="待追加"):
        arms.main(["--set", name, "--vectors", str(tmp_path / "v"), "--out", str(tmp_path / "o")])


# ---------------------------------------------------------------- store: 驗收 A on NEW82

@pytest.fixture(scope="module")
def new82():
    qs = gd.load_new82()
    vecs, _ = arms.load_query_vectors(gd.PN / "encode_out.jsonl", qs.ids)
    ctx = arms.load_context()
    return qs, ctx, arms.checked_lists(ctx, qs.questions, vecs)


@needs_store
def test_store_bip_graph_has_the_prereg_counts(new82):
    _, ctx, _ = new82
    assert (ctx.graph.n_pass, len(ctx.graph.names), ctx.graph.n_edges) == (2773, 2929, 16616)


ARCHIVED = [("d20", "EV", "d20"), ("d20", "AT", "d20"), ("C", "EV", "ctrl_extra"), ("C", "AT", "CTRL"),
            ("GD", "EV", "PPR_DENSEONLY"), ("G", "EV", "PPR_BIP"), ("G", "AT", "PPR_BIP"),
            ("L", "EV", "BM25_Q"), ("L", "AT", "BM25Q"), ("LEXPRF", "AT", "LEXPRF")]


@needs_store
@pytest.mark.parametrize("arm, src, key", ARCHIVED)
def test_store_new82_lists_equal_the_archived_prf_lists(new82, arm, src, key):
    _, _, lists = new82
    ref = json.loads((getattr(gd, src) / "prf_lists.json").read_text(encoding="utf-8"))
    mine = {q: (v["D30"][:20] if arm == "d20" else v[arm]) for q, v in lists.items()}
    assert mine == {q: ref[q][key] for q in lists}


@needs_store
@pytest.mark.parametrize("arm", ["GD", "GD_DEGNORM"])
def test_store_new82_pool_reach_on_missing_hops_equals_gd_hub(new82, arm):
    qs, _, lists = new82
    reach, wins, losses = 0, 0, 0
    for q in qs.questions:
        d30, extra = lists[q.qid]["D30"], set(lists[q.qid][arm])
        golds = gd.question_gold(q)
        arm_hit = sum(bool(golds[h] & (set(d30[:20]) | extra)) for h in q.missing_hops)
        ctrl_hit = sum(bool(golds[h] & set(d30)) for h in q.missing_hops)
        reach, wins, losses = reach + arm_hit, wins + (arm_hit > ctrl_hit), losses + (arm_hit < ctrl_hit)
    ref = json.loads((gd.FM / "gd_hub.json").read_text(encoding="utf-8"))[arm]
    assert (reach, wins, losses) == (ref["reach"], ref["q_w"], ref["q_l"])


@needs_store
def test_the_stored_new82_lists_are_this_code_s_output(new82):
    """store new82/lists.json (the input of score.py rerank) equals a fresh run, and its meta
    pins the current scripts and vectors (prereg.md is left out: appendices get appended);
    a stale file has to be regenerated, and 驗收 A rerun, before scoring."""
    path = gd.OUT_ROOT / "new82" / "lists.json"
    if not path.is_file():
        pytest.skip(f"{path} not written yet (arms.py --set new82)")
    qs, _, lists = new82
    doc = json.loads(path.read_text(encoding="utf-8"))
    meta = doc["meta"]
    assert doc["lists"] == lists and list(doc["lists"]) == list(qs.ids)
    assert meta["lists_sha256"] == arms.lists_sha256(doc["lists"])
    assert (meta["set"], meta["ids_sha256"]) == ("new82", gd.IDS_SHA256["new82"])
    current = {**{p.name: p for p in (*gd.MODULE_FILES, *arms.SCRIPT_FILES)},
               "query_vectors": gd.PN / "encode_out.jsonl"}
    assert {k: meta["sha256"][k] for k in current} == {k: gd.file_sha256(p) for k, p in current.items()}


@needs_store
def test_r20_is_the_archived_d5_input_of_every_new82_question(new82):
    qs, _, lists = new82
    d5_in = {i["sid"].split("|")[0]: i["pids"]
             for i in json.loads(gd.read_pinned(gd.PN / "rr_d5_in.json",
                                                gd.ARCHIVE_SHA256[gd.PN / "rr_d5_in.json"]))}
    assert {q: lists[q]["R20"] for q in qs.ids} == {q: d5_in[q] for q in qs.ids}


@needs_store
def test_the_cli_writes_the_lists_with_their_meta(new82, tmp_path):
    qs, _, lists = new82
    out = tmp_path / "lists.json"
    assert arms.main(["--set", "new82", "--vectors", str(gd.PN / "encode_out.jsonl"), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    meta = doc["meta"]
    assert doc["lists"] == lists and meta["lists_sha256"] == gd.lists_sha256(lists)
    assert (meta["graph"]["edges"], meta["n_questions"], meta["build_id"]) == (16616, 82, gd.BUILD_ID)
    assert meta["query_vectors_meta"]["embedder_fingerprint"] == dict(gd.FINGERPRINTS["embedder"])
    assert set(meta["sha256"]) >= {"prereg.md", "_gd_pool.py", "arms.py", "_gd_lex.py", "query_vectors"}
    with pytest.raises(gd.GdError, match="overwrite"):
        arms.main(["--set", "new82", "--vectors", str(gd.PN / "encode_out.jsonl"), "--out", str(out)])
