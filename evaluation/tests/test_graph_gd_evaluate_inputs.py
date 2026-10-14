"""GD experiment evaluate.py inputs (experiments/2026-10-14_graph_gd/_eval_inputs.py).

Unit tests on small files: the §3 pool shape of lists.json, the scores-file line checks,
and provenance (§10): pinned lists must carry the set, layers, vectors, build and their own
content hash; pinned scores must name these lists, this set and one set of scorer scripts,
pass the strict reranker run settings on every meta line and end each scoring run with a
passing refcheck line. Unpinned files still get every container meta line checked.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _SPEC = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_SPEC)
    sys.modules["gd_common"] = gd
    _SPEC.loader.exec_module(gd)
if "gd_evaluate" in sys.modules:
    ev = sys.modules["gd_evaluate"]
else:
    _SPEC_EV = importlib.util.spec_from_file_location("gd_evaluate", _DIR / "evaluate.py")
    ev = importlib.util.module_from_spec(_SPEC_EV)
    sys.modules["gd_evaluate"] = ev
    _SPEC_EV.loader.exec_module(ev)
I = ev.I  # noqa: E741

D30 = [f"ps:{i:02d}" for i in range(30)]
SCRIPTS = {name: name[0] * 64 for name in ("score.py", "_score_io.py", "rerank_stdin.py")}
STRICT = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu", "batch": 16, "torch_threads": 12,
          "reranker_fingerprint": gd.expected_fingerprint("reranker")}
LOOSE = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu",
         "reranker_fingerprint": dict(gd.FINGERPRINTS["reranker"])}


def qset(*ids, name="new82"):
    return gd.QuestionSet(name, tuple(gd.Question(q, "?", gd.KIN, (("gen.1.1",),), frozenset())
                                      for q in ids), MappingProxyType({}))


def entry(**over):
    return {"D30": D30, "R20": D30[:12], "C": D30[20:], "GD": ["ps:99"], "L": [], "LEXPRF": [],
            **over}


def lists_meta(qs, rows, **over):
    return {"set": qs.name, "ids_sha256": qs.ids_sha256, "build_id": gd.BUILD_ID,
            "layers": dict(gd.LAYER_VERSIONS), "vectors_sha256": gd.VECTORS_SHA256,
            "lists_sha256": gd.lists_sha256(rows),
            "query_vectors_meta": {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu",
                                   "embedder_fingerprint": dict(gd.FINGERPRINTS["embedder"])},
            **over}


def write_lists(path, rows, meta=None):
    path.write_text(json.dumps({"meta": meta or {}, "lists": rows}), encoding="utf-8")
    return path


def write_scores(path, *lines):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def row(qid, scores, missing=()):
    return {"type": "r", "sid": qid, "scores": scores, "missing": list(missing), "elapsed_s": 1.0}


def host(qs, lists_sha, **over):
    return {**STRICT, "host": {"lists_sha256": lists_sha, "sha256": dict(SCRIPTS), "set": qs.name,
                               "set_ids_sha256": qs.ids_sha256, **over}}


def refcheck(**over):
    return {"type": "refcheck", "n_pairs": 32, "max_abs_diff": 4e-7, "pass": True,
            "container_meta": STRICT, **over}


# ---------------------------------------------------------------- §3 shape

@pytest.mark.parametrize("extra, ok", [(D30[20:30], True), (D30[20:29], False), (["ps:99"], False)])
def test_c_extra_must_be_dense_20_to_30(tmp_path, extra, ok):
    rows = {"Q": entry(C=extra)}
    if ok:
        lists = I.Lists(write_lists(tmp_path / "l.json", rows), qset("Q"), pinned=False)
        assert len(lists.pools["C"]["Q"]) == 30 and len(lists.pools["GD"]["Q"]) == 21
        assert lists.r20["Q"] == tuple(D30[:12])
    else:
        with pytest.raises(gd.GdError):
            I.Lists(write_lists(tmp_path / "l.json", rows), qset("Q"), pinned=False)


@pytest.mark.parametrize("over", [{"GD": [D30[3]]}, {"GD": ["ps:a", "ps:a"]},
                                  {"GD": [f"ps:x{i}" for i in range(11)]}, {"R20": ["ps:99"]},
                                  {"R20": []}, {"W": []}, {"D30": D30[:29]}])
def test_extra_r20_and_keys_must_keep_the_section_3_shape(tmp_path, over):
    with pytest.raises(gd.GdError):
        I.Lists(write_lists(tmp_path / "l.json", {"Q": entry(**over)}), qset("Q"), pinned=False)


def test_lists_must_cover_exactly_the_question_set_and_each_arm_every_question(tmp_path):
    rows = {"Q1": entry(), "Q2": {k: v for k, v in entry().items() if k != "GD"}}
    with pytest.raises(gd.GdError, match="missing for some"):
        I.Lists(write_lists(tmp_path / "l.json", rows), qset("Q1", "Q2"), pinned=False)
    with pytest.raises(gd.IntegrityError):
        I.Lists(write_lists(tmp_path / "l.json", {"Q1": rows["Q1"]}), qset("Q1", "Q2"), pinned=False)


# ---------------------------------------------------------------- lists provenance

def test_pinned_lists_need_their_meta_to_name_the_set_pins_and_content(tmp_path):
    qs, rows = qset("Q"), {"Q": entry()}
    lists = I.Lists(write_lists(tmp_path / "l.json", rows, lists_meta(qs, rows)), qs)
    assert lists.pinned and lists.content_sha256 == gd.lists_sha256(rows)
    with pytest.raises(gd.IntegrityError):
        I.Lists(write_lists(tmp_path / "l.json", rows), qs)                # no meta
    for over in ({"set": "old31"}, {"ids_sha256": "0" * 64}, {"layers": {}}, {"build_id": "b0"},
                 {"vectors_sha256": "0" * 64}, {"lists_sha256": "0" * 64},
                 {"query_vectors_meta": {"type": "meta", "build_id": gd.BUILD_ID}}):
        with pytest.raises(gd.IntegrityError):
            I.Lists(write_lists(tmp_path / "l.json", rows, lists_meta(qs, rows, **over)), qs)


def test_the_content_hash_ignores_the_meta_but_not_the_lists(tmp_path):
    qs, rows = qset("Q"), {"Q": entry()}
    a = I.Lists(write_lists(tmp_path / "a.json", rows, lists_meta(qs, rows, time_utc="x")), qs)
    b = I.Lists(write_lists(tmp_path / "b.json", rows, lists_meta(qs, rows, time_utc="y")), qs)
    assert a.content_sha256 == b.content_sha256
    assert gd.lists_sha256({"Q": entry(GD=["ps:98"])}) != a.content_sha256


# ---------------------------------------------------------------- scores, unpinned

def test_unpinned_scores_load_with_a_fingerprinted_meta(tmp_path):
    s = I.Scores(write_scores(tmp_path / "s.jsonl", LOOSE, row("Q", {"ps:a": 0.5})), qset("Q"), None)
    assert s.by_qid["Q"]["ps:a"] == 0.5 and len(s.metas) == 1 and not s.pinned


@pytest.mark.parametrize("lines, error", [
    ([row("Q", {"ps:a": 0.5})], gd.IntegrityError),                                  # no meta
    ([{"type": "meta", "build_id": "b_WRONG"}, LOOSE, row("Q", {"ps:a": 0.5})], gd.IntegrityError),
    ([LOOSE, row("Q", {"ps:a": 0.5}), {**STRICT, "build_id": "b0", "reranker_fingerprint": None,
                                         "embedder_fingerprint": {}}], gd.IntegrityError),
    ([{**LOOSE, "build_id": "b0"}, row("Q", {"ps:a": 0.5})], gd.IntegrityError),
    ([{**LOOSE, "device": "cuda"}, row("Q", {"ps:a": 0.5})], gd.IntegrityError),
    ([LOOSE, row("Q", {"ps:a": 0.5}, missing=["ps:b"])], gd.GdError),                # 分數缺漏
    ([LOOSE, row("Q", {"ps:a": 0.5}), row("Q", {"ps:a": 0.5})], gd.GdError),         # scored twice
    ([LOOSE, {"type": "x"}, row("Q", {"ps:a": 0.5})], gd.GdError),
    ([LOOSE, row("Q", {"ps:a": "high"})], gd.GdError),
    ([LOOSE, row("Q", {"ps:a": 0.5}), refcheck(**{"pass": False, "max_abs_diff": 0.2})], gd.IntegrityError),
])
def test_scores_refuse_broken_files(tmp_path, lines, error):
    with pytest.raises(error):
        I.Scores(write_scores(tmp_path / "s.jsonl", *lines), qset("Q"), None)


# ---------------------------------------------------------------- scores, pinned

def test_pinned_scores_name_these_lists_and_end_with_a_passing_refcheck(tmp_path):
    qs = qset("Q1", "Q2")
    lines = [host(qs, "L" * 64), row("Q1", {"ps:a": 0.5}), host(qs, "L" * 64),
             row("Q2", {"ps:a": 0.4}), refcheck()]
    s = I.Scores(write_scores(tmp_path / "s.jsonl", *lines), qs, "L" * 64)
    assert s.pinned and len(s.refchecks) == 1 and len(s.metas) == 2


@pytest.mark.parametrize("change", [
    lambda qs, L: [host(qs, "X" * 64), row("Q1", {"ps:a": 0.5}), refcheck()],           # other lists
    lambda qs, L: [host(qs, L), row("Q1", {"ps:a": 0.5})],                               # no refcheck
    lambda qs, L: [host(qs, L), refcheck(), host(qs, L), row("Q1", {"ps:a": 0.5})],     # none after
    lambda qs, L: [{**host(qs, L), "batch": 99}, row("Q1", {"ps:a": 0.5}), refcheck()],  # §3 batch
    lambda qs, L: [{**host(qs, L), "torch_threads": 1}, row("Q1", {"ps:a": 0.5}), refcheck()],
    lambda qs, L: [host(qs, L), row("Q1", {"ps:a": 0.5}),
                   refcheck(container_meta={**STRICT, "batch": 8})],
    lambda qs, L: [host(qs, L, set="old31"), row("Q1", {"ps:a": 0.5}), refcheck()],
    lambda qs, L: [host(qs, L), host(qs, L, sha256={**SCRIPTS, "score.py": "0" * 64}),
                   row("Q1", {"ps:a": 0.5}), refcheck()],                                # mixed scripts
    lambda qs, L: [LOOSE, row("Q1", {"ps:a": 0.5}), refcheck()],                         # no host part
])
def test_pinned_scores_refuse_files_that_cannot_prove_their_origin(tmp_path, change):
    qs = qset("Q1")
    with pytest.raises(gd.IntegrityError):
        I.Scores(write_scores(tmp_path / "s.jsonl", *change(qs, "L" * 64)), qs, "L" * 64)
