"""GD experiment score.py rerank-w (§3 W) and rerank --arms, against in-process fake containers.

rerank --arms scores D30[:20] ∪ the chosen arms' extra and records the arms (a resume with
other arms is refused). rerank-w reads the finished rerank file of the same lists, sends
each question's C∪GD pool in pid order, fills single-window passages with their whole
score, ends with the §10 refcheck, resumes after a crash or a partial --ids run, refuses a
scores file it cannot build on and a container off the pins, and its output is what
evaluate.py's pinned W reader (_eval_inputs.WScores) accepts.
"""

import base64
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
    _GD = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_GD)
    sys.modules["gd_common"] = gd
    _GD.loader.exec_module(gd)
if "graph_gd_score" in sys.modules:
    sc = sys.modules["graph_gd_score"]
else:
    _SPEC = importlib.util.spec_from_file_location("graph_gd_score", _DIR / "score.py")
    sc = importlib.util.module_from_spec(_SPEC)
    sys.modules["graph_gd_score"] = sc
    _SPEC.loader.exec_module(sc)
sw = sc.sw

QSET = gd.QuestionSet("new82", (
    gd.Question("Q1", "第一題", gd.KIN, (("exo.6.20",),), frozenset(), None),
    gd.Question("Q2", "第二題", gd.KIN, (("exo.6.23",),), frozenset(), None),
    gd.Question("Q3", "第三題", gd.KIN, (("exo.6.24",),), frozenset(), None)), MappingProxyType({}))
PENDING_PREREG = "# prereg\n\n## 附錄 A：凍結\n\n待追加\n\n## 附錄 B：HO\n\n待追加\n"


def entry(tag):
    d30 = [f"ps:{tag}.{i:02d}" for i in range(30)]
    return {"D30": d30, "R20": d30[:12], "C": d30[20:30], "GD": [f"ps:{tag}.g1", f"ps:{tag}.g2"],
            "L": [f"ps:{tag}.l1", d30[25]], "LEXPRF": []}


ROWS = {q: entry(q.lower()) for q in QSET.ids}


def meta(**over):
    return {"type": "meta", "build_id": gd.BUILD_ID, "reranker_fingerprint": gd.expected_fingerprint("reranker"),
            **gd.RUN_SETTINGS["reranker"], **over}


def w_meta(**over):
    return meta(**{"window_max_length": 512, **over})


def passing_check():
    return {"type": "refcheck", "n_pairs": 32, "max_abs_diff": 0.0, "pass": True, "container_meta": meta(),
            "pairs": []}


def windows_of(pid):
    return 1 + (sum(map(ord, pid)) % 3)          # 1, 2 or 3 windows, fixed per pid


class Fake:
    """Stands in for run_container: rerank (r lines) or rerank-w (w lines) answers per item."""

    def __init__(self, meta_line=None, crash_after=None):
        self.meta_line, self.crash_after, self.payloads = meta_line, crash_after, []

    def __call__(self, script, err_path, on_line):
        items = json.loads(base64.b64decode(script.split("\n", 1)[0].split('"')[1]).decode("utf-8"))
        self.payloads.append(items)
        is_w = "window_max" in script
        on_line(dict(self.meta_line or (w_meta() if is_w else meta())))
        for n, item in enumerate(items):
            if self.crash_after is not None and n == self.crash_after:
                raise sc.ContainerError("container died")
            on_line(self.w(item) if is_w else self.r(item))

    @staticmethod
    def r(item):
        return {"type": "r", "sid": item["sid"], "missing": [], "elapsed_s": 0.1,
                "scores": {p: 1.0 / (2 + i) for i, p in enumerate(item["pids"])}}

    @staticmethod
    def w(item):
        n = {p: windows_of(p) for p in item["pids"]}
        return {"type": "w", "sid": item["sid"], "missing": [], "elapsed_s": 0.2, "n_windows": n,
                "scores": {p: 0.99 for p, k in n.items() if k > 1}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(PENDING_PREREG, encoding="utf-8")
    monkeypatch.setattr(sc, "PREREG", prereg)
    monkeypatch.setattr(sc, "ACCEPT", tmp_path)
    monkeypatch.setattr(gd, "container_image_id", lambda *a: gd.IMAGE_ID)
    monkeypatch.setattr(gd, "load_question_set", lambda name: gd.QuestionSet(name, QSET.questions, QSET.sources))
    monkeypatch.setattr(sc, "run_refcheck", lambda host, err: ([], passing_check()))
    lists = tmp_path / "lists.json"
    lists.write_text(json.dumps({"meta": {
        "set": "new82", "ids_sha256": QSET.ids_sha256, "build_id": gd.BUILD_ID,
        "layers": dict(gd.LAYER_VERSIONS), "vectors_sha256": gd.VECTORS_SHA256,
        "lists_sha256": gd.lists_sha256(ROWS),
        "query_vectors_meta": {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu",
                               "embedder_fingerprint": dict(gd.FINGERPRINTS["embedder"])}},
        "lists": ROWS}), encoding="utf-8")
    return tmp_path, lists


def run(monkeypatch, fake, *argv):
    monkeypatch.setattr(sc, "run_container", fake)
    return sc.main([str(a) for a in argv])


def rerank(monkeypatch, lists, out, *extra):
    return run(monkeypatch, Fake(), "rerank", "--lists", lists, "--out", out, *extra)


def records(path):
    return sc.scan_jsonl(path).records


def kinds(path):
    return [r.get("sid") or r["type"] for r in records(path)]


# ---------------------------------------------------------------- rerank --arms

def test_rerank_with_arms_scores_only_their_union_and_records_them(env, monkeypatch):
    tmp, lists = env
    fake = Fake()
    assert run(monkeypatch, fake, "rerank", "--lists", lists, "--out", tmp / "s.jsonl", "--arms", "GD,C") == 0
    want = sorted(set(ROWS["Q1"]["D30"][:20]) | set(ROWS["Q1"]["C"]) | set(ROWS["Q1"]["GD"]))
    assert fake.payloads[0][0]["pids"] == want and "ps:q1.l1" not in want
    assert records(tmp / "s.jsonl")[0]["host"]["arms"] == ["C", "GD"]
    assert rerank(monkeypatch, lists, tmp / "all.jsonl") == 0
    assert records(tmp / "all.jsonl")[0]["host"]["arms"] == ["C", "GD", "L", "LEXPRF"]


def test_a_resume_with_other_arms_is_refused(env, monkeypatch):
    tmp, lists = env
    out = tmp / "s.jsonl"
    assert run(monkeypatch, Fake(crash_after=1), "rerank", "--lists", lists, "--out", out, "--arms", "C,GD") == 2
    fake = Fake()
    assert run(monkeypatch, fake, "rerank", "--lists", lists, "--out", out, "--arms", "C,GD,L") == 2
    assert fake.payloads == [] and kinds(out) == ["meta", "Q1"]
    assert run(monkeypatch, fake, "rerank", "--lists", lists, "--out", out, "--arms", "C,GD") == 0
    assert kinds(out) == ["meta", "Q1", "meta", "Q2", "Q3", "refcheck"]


@pytest.mark.parametrize("spec", ["C,XX", "C,C", ",", "G_D", "GD_DEGNORM"])
def test_bad_or_absent_arms_exit_2_before_any_container_run(env, monkeypatch, spec):
    tmp, lists = env
    fake = Fake()
    assert run(monkeypatch, fake, "rerank", "--lists", lists, "--out", tmp / "s.jsonl", "--arms", spec) == 2
    assert fake.payloads == [] and not (tmp / "s.jsonl").exists()


def test_parse_arms_orders_by_the_arm_table():
    assert sc.parse_arms(" GD , C ") == ("C", "GD") and sc.parse_arms(None) is None


# ---------------------------------------------------------------- rerank-w

def whole_file(monkeypatch, tmp, lists, *extra):
    out = tmp / "s.jsonl"
    assert rerank(monkeypatch, lists, out, *extra) == 0
    return out


def rerank_w(monkeypatch, fake, lists, scores, out, *extra):
    return run(monkeypatch, fake, "rerank-w", "--lists", lists, "--scores", scores, "--out", out, *extra)


def test_rerank_w_sends_the_c_gd_pool_and_fills_single_windows_with_whole_scores(env, monkeypatch):
    tmp, lists = env
    scores = whole_file(monkeypatch, tmp, lists)
    fake, out = Fake(), tmp / "w.jsonl"
    assert rerank_w(monkeypatch, fake, lists, scores, out) == 0
    (items,) = fake.payloads
    assert [i["sid"] for i in items] == list(QSET.ids)
    assert items[0]["pids"] == list(sc.arms_union("Q1", ROWS["Q1"], ("C", "GD")))
    assert "window_max" in sc.RERANK_W_STDIN.read_text(encoding="utf-8")
    lines = records(out)
    assert kinds(out) == ["meta", "Q1", "Q2", "Q3", "refcheck"]
    whole = {r["sid"]: r["scores"] for r in records(scores) if r["type"] == "r"}
    host = lines[0]["host"]
    assert (host["kind"], host["arms"], host["lists_sha256"]) == ("rerank-w", ["C", "GD"], gd.lists_sha256(ROWS))
    assert host["scores_sha256"] == sw.scores_content_sha256(whole)
    assert {k: host["sha256"][k] for k in sw.W_SCRIPT_NAMES} == sc.w_script_shas()
    assert host["sha256"]["scores"] == gd.file_sha256(scores)
    for line in lines[1:4]:
        assert set(line) == {"type", "sid", "scores", "n_windows", "elapsed_s"}
        for pid, n in line["n_windows"].items():
            assert line["scores"][pid] == (0.99 if n > 1 else whole[line["sid"]][pid])


def test_rerank_w_resumes_after_a_crash_and_after_a_partial_ids_run(env, monkeypatch):
    tmp, lists = env
    scores, out = whole_file(monkeypatch, tmp, lists), tmp / "w.jsonl"
    assert rerank_w(monkeypatch, Fake(), lists, scores, out, "--ids", "Q2") == 0
    assert kinds(out) == ["meta", "Q2", "refcheck"]
    assert rerank_w(monkeypatch, Fake(crash_after=1), lists, scores, out, "--chunk", "5") == 2
    assert kinds(out) == ["meta", "Q2", "refcheck", "meta", "Q1"]
    fake = Fake()
    assert rerank_w(monkeypatch, fake, lists, scores, out) == 0
    assert [[i["sid"] for i in p] for p in fake.payloads] == [["Q3"]]
    again = Fake()
    assert rerank_w(monkeypatch, again, lists, scores, out) == 0 and again.payloads == []
    assert kinds(out)[-2:] == ["Q3", "refcheck"]


def test_rerank_w_drops_a_cut_last_line(env, monkeypatch):
    tmp, lists = env
    scores, out = whole_file(monkeypatch, tmp, lists), tmp / "w.jsonl"
    assert rerank_w(monkeypatch, Fake(), lists, scores, out, "--chunk", "1") == 0
    whole = [json.dumps(r) + "\n" for r in records(out)[:-1]]
    out.write_text("".join(whole[:-1]) + whole[-1][:-30])       # Q3 cut, no refcheck
    fake = Fake()
    assert rerank_w(monkeypatch, fake, lists, scores, out) == 0
    assert [[i["sid"] for i in p] for p in fake.payloads] == [["Q3"]] and not sc.scan_jsonl(out).cut_tail


@pytest.mark.parametrize("bad", [w_meta(window_max_length=256), meta(), w_meta(torch_threads=6),
                                 w_meta(build_id="b20261008_6daa4f31")])
def test_a_w_container_off_the_pins_writes_nothing(env, monkeypatch, bad):
    tmp, lists = env
    scores, out = whole_file(monkeypatch, tmp, lists), tmp / "w.jsonl"
    assert rerank_w(monkeypatch, Fake(meta_line=bad), lists, scores, out) == 2
    assert records(out) == ()


def test_rerank_w_needs_a_finished_scores_file_of_these_lists_with_c_and_gd(env, monkeypatch):
    tmp, lists = env
    fake = Fake()
    only_c = tmp / "c.jsonl"
    assert rerank(monkeypatch, lists, only_c, "--arms", "C,L") == 0
    assert rerank_w(monkeypatch, fake, lists, only_c, tmp / "w1.jsonl") == 2
    scores = whole_file(monkeypatch, tmp, lists)
    cut = tmp / "cut.jsonl"
    cut.write_text("".join(json.dumps(r) + "\n" for r in records(scores)[:-1]))   # no refcheck
    assert rerank_w(monkeypatch, fake, lists, cut, tmp / "w2.jsonl") == 2
    other = tmp / "other.json"
    rows = {**ROWS, "Q3": {**ROWS["Q3"], "GD": ["ps:q3.g9"]}}
    other.write_text(json.dumps({"meta": {"set": "new82"}, "lists": rows}))
    assert rerank_w(monkeypatch, fake, other, scores, tmp / "w3.jsonl") == 2   # scores of other lists
    assert fake.payloads == []


@pytest.mark.parametrize("name", ["old31", "ho", "gtv2"])
def test_rerank_w_refuses_confirmation_sets_before_reading_anything(env, monkeypatch, name):
    tmp, _ = env
    lists = tmp / f"{name}.json"
    lists.write_text(json.dumps({"meta": {"set": name}, "lists": ROWS}))
    fake = Fake()
    assert rerank_w(monkeypatch, fake, lists, tmp / "none.jsonl", tmp / "w.jsonl") == 2
    assert fake.payloads == [] and not (tmp / "w.jsonl").exists()


def test_the_w_file_is_what_the_pinned_evaluate_reader_accepts(env, monkeypatch):
    tmp, lists = env
    spec = importlib.util.spec_from_file_location("gd_eval_inputs_w", _DIR / "_eval_inputs.py")
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    scores, out = whole_file(monkeypatch, tmp, lists), tmp / "w.jsonl"
    assert rerank_w(monkeypatch, Fake(), lists, scores, out, "--chunk", "2") == 0
    read_lists = inputs.Lists(lists, QSET)
    read_scores = inputs.Scores(scores, QSET, read_lists.content_sha256)
    w = inputs.WScores(out, QSET, read_lists, read_scores)
    assert set(w.by_qid) == set(QSET.ids) and len(w.metas) == 2 and w.n_refchecks == 1
    assert read_scores.arms == ("C", "GD", "L", "LEXPRF")
    other = tmp / "s2.jsonl"
    assert rerank(monkeypatch, lists, other) == 0            # same lists, scores of another run
    tweaked = [dict(r, scores={**r["scores"], "ps:q1.00": 0.0}) if r.get("sid") == "Q1" else r
               for r in records(other)]
    other.write_text("".join(json.dumps(r) + "\n" for r in tweaked))
    with pytest.raises(gd.IntegrityError, match="whole-score content"):
        inputs.WScores(out, QSET, read_lists, inputs.Scores(other, QSET, read_lists.content_sha256))
