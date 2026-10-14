"""GD experiment container runner flows (experiments/2026-10-14_graph_gd/score.py).

The rerank and encode commands against an in-process fake container (resume after a
crash, a cut last line, the trailing §10 refcheck, pins and run settings on the meta line,
the confirmation-set guard), and run_container against real host-python subprocesses
(exit codes, non-JSON output, a closed stdin, a whole rerank through a fake stdin body).
"""

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType

import numpy as np
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

PENDING_PREREG = "# prereg\n\n## 附錄 A：凍結\n\n待追加\n\n## 附錄 B：HO\n\n待追加。\n"
FILLED_A = "# prereg\n\n## 附錄 A：凍結\n\n- 本檔 sha …\n\n## 附錄 B：HO\n\n待追加\n"
QSET = gd.QuestionSet("new82", (
    gd.Question("Q1", "第一題：誰是摩西的父親？", gd.KIN, (("exo.6.20",),), frozenset(), None),
    gd.Question("Q2", "第二題：誰是亞倫的兒子？", gd.KIN, (("exo.6.23",),), frozenset(), None),
    gd.Question("Q3", "第三題", gd.KIN, (("exo.6.24",),), frozenset(), None)),
    MappingProxyType({}))
FAKE_BODY = '''import base64, json, sys
items = json.loads(base64.b64decode(PAYLOAD_B64).decode("utf-8"))
print(json.dumps(META), flush=True)
for item in items:
    scores = {p: 1.0 / (2 + i) for i, p in enumerate(item["pids"])}
    print(json.dumps({"type": "r", "sid": item["sid"], "scores": scores, "missing": [],
                      "elapsed_s": 0.0}), flush=True)
'''


def entry(tag="d"):
    d30 = [f"ps:{tag}.{i}" for i in range(30)]
    return {"D30": d30, "R20": d30[:12], "C": d30[20:30], "GD": ["ps:g.1", "ps:g.2"],
            "L": ["ps:l.1", d30[25]]}


def meta(kind="reranker", **over):
    return {"type": "meta", "build_id": gd.BUILD_ID, f"{kind}_fingerprint": gd.expected_fingerprint(kind),
            **gd.RUN_SETTINGS[kind], **over}


def r_line(sid, pids):
    return {"type": "r", "sid": sid, "scores": {p: 1.0 / (2 + i) for i, p in enumerate(pids)},
            "missing": [], "elapsed_s": 0.5}


def passing_check(max_abs=3e-7):
    return {"type": "refcheck", "n_pairs": 32, "max_abs_diff": max_abs, "pass": max_abs <= gd.DRIFT_TOL,
            "container_meta": meta(), "pairs": []}


class FakeContainer:
    """Stands in for run_container: answers each payload item, or dies after `crash_after`."""

    def __init__(self, meta_line=None, crash_after=None, kind="reranker"):
        self.meta_line, self.crash_after, self.kind = meta_line or meta(kind), crash_after, kind
        self.payloads = []

    def __call__(self, script, err_path, on_line):
        line = script.split("\n", 1)[0]
        items = json.loads(base64.b64decode(line.split('"')[1]).decode("utf-8"))
        self.payloads.append(items)
        on_line(dict(self.meta_line))
        for n, item in enumerate(items):
            if self.crash_after is not None and n == self.crash_after:
                raise sc.ContainerError("container died")
            on_line(self.answer(item))

    def answer(self, item):
        if self.kind == "embedder":
            vec = np.full(gd.EMB_DIM, 0.5, dtype="<f4")
            return {"type": "q", "sid": item["sid"], "vec_b64": base64.b64encode(vec.tobytes()).decode()}
        return r_line(item["sid"], item["pids"])


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    prereg = tmp_path / "prereg.md"
    prereg.write_text(PENDING_PREREG, encoding="utf-8")
    accept = tmp_path / "accept"
    accept.mkdir()
    for name in gd.ACCEPT_FILES:
        (accept / name).write_text(json.dumps({"passed": True, "lists_sha256": "L" * 64}), encoding="utf-8")
    monkeypatch.setattr(sc, "PREREG", prereg)
    monkeypatch.setattr(sc, "ACCEPT", accept)
    monkeypatch.setattr(gd, "container_image_id", lambda *a: gd.IMAGE_ID)
    monkeypatch.setattr(gd, "load_question_set",
                        lambda name: gd.QuestionSet(name, QSET.questions, QSET.sources))
    checks = []
    monkeypatch.setattr(sc, "run_refcheck", lambda host, err: ([], checks.pop(0) if checks else passing_check()))
    lists = tmp_path / "lists.json"
    lists.write_text(json.dumps({"meta": {"set": "new82"},
                                 "lists": {"Q1": entry("a"), "Q2": entry("b")}}), encoding="utf-8")
    return tmp_path, lists, checks


def run_rerank(monkeypatch, fake, lists, out, chunk=5):
    monkeypatch.setattr(sc, "run_container", fake)
    return sc.main(["rerank", "--lists", str(lists), "--out", str(out), "--chunk", str(chunk)])


def kinds(out):
    return [r.get("sid") or r["type"] for r in sc.scan_jsonl(out).records]


# ---------------------------------------------------------------- rerank

def test_rerank_sends_each_union_in_pid_order_and_ends_with_a_refcheck(fake_env, monkeypatch):
    tmp, lists, _ = fake_env
    fake = FakeContainer()
    assert run_rerank(monkeypatch, fake, lists, tmp / "s.jsonl") == 0
    (items,) = fake.payloads
    assert [i["sid"] for i in items] == ["Q1", "Q2"]                  # Q3 is not in the lists
    assert items[0]["query"] == "第一題：誰是摩西的父親？"
    assert items[0]["pids"] == list(sc.pool_union("Q1", entry("a")))
    lines = sc.scan_jsonl(tmp / "s.jsonl").records
    assert kinds(tmp / "s.jsonl") == ["meta", "Q1", "Q2", "refcheck"]
    host = lines[0]["host"]
    assert host["sha256"]["lists"] == gd.file_sha256(lists)
    assert host["lists_sha256"] == gd.lists_sha256(json.loads(lists.read_text())["lists"])
    assert {k: host["sha256"][k] for k in sc.SCRIPT_NAMES} == sc.script_shas()


def test_rerank_resumes_after_a_crash_and_skips_finished_questions(fake_env, monkeypatch):
    tmp, lists, _ = fake_env
    out = tmp / "s.jsonl"
    assert run_rerank(monkeypatch, FakeContainer(crash_after=1), lists, out) == 2
    assert kinds(out) == ["meta", "Q1"]                               # no refcheck after a crash
    second = FakeContainer()
    assert run_rerank(monkeypatch, second, lists, out) == 0
    assert [[i["sid"] for i in p] for p in second.payloads] == [["Q2"]]
    third = FakeContainer()
    assert run_rerank(monkeypatch, third, lists, out) == 0 and third.payloads == []
    assert kinds(out) == ["meta", "Q1", "meta", "Q2", "refcheck"]


def test_a_finished_file_without_its_refcheck_gets_only_the_refcheck(fake_env, monkeypatch):
    tmp, lists, _ = fake_env
    out = tmp / "s.jsonl"
    assert run_rerank(monkeypatch, FakeContainer(), lists, out) == 0
    out.write_text("".join(json.dumps(r) + "\n" for r in sc.scan_jsonl(out).records[:-1]))
    fake = FakeContainer()
    assert run_rerank(monkeypatch, fake, lists, out) == 0 and fake.payloads == []
    assert kinds(out) == ["meta", "Q1", "Q2", "refcheck"]


def test_a_drifted_refcheck_fails_the_run_and_taints_the_file(fake_env, monkeypatch):
    tmp, lists, checks = fake_env
    out = tmp / "s.jsonl"
    checks.append(passing_check(max_abs=2e-4))
    assert run_rerank(monkeypatch, FakeContainer(), lists, out) == 2
    assert kinds(out)[-1] == "refcheck" and not sc.scan_jsonl(out).records[-1]["pass"]
    fake = FakeContainer()
    assert run_rerank(monkeypatch, fake, lists, out) == 2 and fake.payloads == []


def test_rerank_drops_a_cut_last_line_before_appending(fake_env, monkeypatch):
    tmp, lists, _ = fake_env
    out = tmp / "s.jsonl"
    assert run_rerank(monkeypatch, FakeContainer(), lists, out, chunk=1) == 0
    whole = [json.dumps(r) + "\n" for r in sc.scan_jsonl(out).records[:-1]]   # drop the refcheck
    out.write_text("".join(whole[:-1]) + whole[-1][:-40])                      # cut the Q2 line
    fake = FakeContainer()
    assert run_rerank(monkeypatch, fake, lists, out) == 0
    assert [[i["sid"] for i in p] for p in fake.payloads] == [["Q2"]]
    scan = sc.scan_jsonl(out)
    assert not scan.cut_tail and kinds(out) == ["meta", "Q1", "meta", "meta", "Q2", "refcheck"]


@pytest.mark.parametrize("bad", [
    meta(build_id="b20261008_6daa4f31"),
    meta(reranker_fingerprint={**gd.expected_fingerprint("reranker"), "tokenizer_sha": "0" * 64}),
    meta(reranker_fingerprint=None), meta(batch=8), meta(torch_threads=1), meta(device="cuda"),
])
def test_a_container_meta_off_the_pins_stops_before_any_score_is_written(fake_env, monkeypatch, bad):
    tmp, lists, _ = fake_env
    out = tmp / "s.jsonl"
    assert run_rerank(monkeypatch, FakeContainer(meta_line=bad), lists, out) == 2
    assert sc.scan_jsonl(out).records == ()


def test_lists_with_a_question_outside_the_set_are_refused(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    lists = tmp / "bad.json"
    lists.write_text(json.dumps({"meta": {"set": "new82"}, "lists": {"Q9": entry()}}))
    fake = FakeContainer()
    assert run_rerank(monkeypatch, fake, lists, tmp / "s.jsonl") == 2 and fake.payloads == []


# ---------------------------------------------------------------- confirmation-set guard

@pytest.mark.parametrize("name", ["old31", "ho", "gtv2", "nonsense"])
def test_confirmation_sets_are_refused_before_any_container_run(fake_env, monkeypatch, name):
    tmp, _, _ = fake_env
    fake = FakeContainer(kind="embedder")
    monkeypatch.setattr(sc, "run_container", fake)
    assert sc.main(["encode", "--set", name, "--out", str(tmp / "v.jsonl")]) == 2
    lists = tmp / f"{name}.json"
    lists.write_text(json.dumps({"meta": {"set": name}, "lists": {"Q1": entry()}}))
    assert sc.main(["rerank", "--lists", str(lists), "--out", str(tmp / "s.jsonl")]) == 2
    assert fake.payloads == [] and not (tmp / "v.jsonl").exists() and not (tmp / "s.jsonl").exists()


def test_a_filled_appendix_a_unlocks_old31_only_with_both_acceptances_passed(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    sc.PREREG.write_text(FILLED_A, encoding="utf-8")
    fake = FakeContainer(kind="embedder")
    monkeypatch.setattr(sc, "run_container", fake)
    assert sc.main(["encode", "--set", "old31", "--out", str(tmp / "v.jsonl")]) == 0
    assert sc.main(["encode", "--set", "ho", "--out", str(tmp / "h.jsonl")]) == 2  # needs B
    (sc.ACCEPT / "accept_b.json").write_text(json.dumps({"passed": False}))
    assert sc.main(["encode", "--set", "old31", "--out", str(tmp / "w.jsonl")]) == 2


# ---------------------------------------------------------------- encode

def test_encode_writes_meta_and_vectors_and_checks_them_against_a_reference(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    monkeypatch.setattr(sc, "run_container", FakeContainer(kind="embedder"))
    ref = tmp / "ref.jsonl"
    vec = np.full(gd.EMB_DIM, 0.5, dtype="<f4")
    vec[7] += 2e-6
    ref.write_text("".join(json.dumps(r) + "\n" for r in [meta("embedder")] + [
        {"type": "q", "sid": f"{q}|Q", "vec_b64": base64.b64encode(vec.tobytes()).decode()}
        for q in ("Q1", "Q3")]))
    out = tmp / "v.jsonl"
    assert sc.main(["encode", "--set", "new82", "--ids", "Q3,Q1", "--out", str(out), "--ref", str(ref)]) == 0
    lines = sc.scan_jsonl(out).records
    assert [r.get("sid") for r in lines] == [None, "Q3", "Q1"]
    assert lines[0]["host"]["ids"] == ["Q3", "Q1"] and "_score_io.py" in lines[0]["host"]["sha256"]
    report = json.loads((tmp / "v.jsonl.refcheck.json").read_text())
    assert report["pass"] and report["worst"] == pytest.approx(2e-6, rel=0.05)


def test_encode_fails_when_the_reference_differs_by_more_than_1e_5(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    monkeypatch.setattr(sc, "run_container", FakeContainer(kind="embedder"))
    vec = np.full(gd.EMB_DIM, 0.5, dtype="<f4")
    vec[0] = 0.6
    ref = tmp / "ref.jsonl"
    ref.write_text(json.dumps({"type": "q", "sid": "Q1", "vec_b64": base64.b64encode(vec.tobytes()).decode()}) + "\n")
    assert sc.main(["encode", "--set", "new82", "--ids", "Q1", "--out", str(tmp / "v.jsonl"),
                    "--ref", str(ref)]) == 2


def test_outputs_are_never_overwritten_and_ids_must_belong_to_the_set(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    fake = FakeContainer(kind="embedder")
    monkeypatch.setattr(sc, "run_container", fake)
    out = tmp / "v.jsonl"
    out.write_text("keep\n")
    assert sc.main(["encode", "--set", "new82", "--out", str(out)]) == 2
    assert out.read_text() == "keep\n"
    assert sc.main(["encode", "--set", "new82", "--ids", "Q1,Q9", "--out", str(tmp / "w.jsonl")]) == 2
    assert sc.main(["encode", "--set", "new82", "--ids", "Q1,Q1", "--out", str(tmp / "w.jsonl")]) == 2
    assert fake.payloads == []


def test_an_encode_meta_with_the_reranker_fingerprint_is_refused(fake_env, monkeypatch):
    tmp, _, _ = fake_env
    monkeypatch.setattr(sc, "run_container", FakeContainer(meta_line=meta("reranker"), kind="embedder"))
    assert sc.main(["encode", "--set", "new82", "--out", str(tmp / "v.jsonl")]) == 2
    assert not (tmp / "v.jsonl").exists()


# ---------------------------------------------------------------- run_container on real processes

def host_python(monkeypatch, *cmd):
    monkeypatch.setattr(gd, "CONTAINER_PYTHON", cmd or (sys.executable, "-B", "-"))


def test_run_container_feeds_each_json_line_and_reports_a_failed_exit(monkeypatch, tmp_path):
    host_python(monkeypatch)
    got = []
    sc.run_container('import json\nprint(json.dumps({"a": 1}))\n', tmp_path / "e.log", got.append)
    assert got == [{"a": 1}]
    with pytest.raises(sc.ContainerError, match="exited 3"):
        sc.run_container("import sys\nprint('{}')\nsys.exit(3)\n", tmp_path / "e.log", got.append)
    with pytest.raises(sc.ContainerError, match="non-JSON"):
        sc.run_container("print('hello')\n", tmp_path / "e.log", got.append)


def test_run_container_turns_a_closed_stdin_into_a_container_error(monkeypatch, tmp_path):
    host_python(monkeypatch, "sh", "-c", "exec 0<&-; sleep 0.3; exit 5")
    with pytest.raises(sc.ContainerError, match="closed its input"):
        sc.run_container("#" * (4 << 20), tmp_path / "e.log", lambda rec: None)


def test_a_whole_rerank_through_a_host_process_with_a_fake_stdin_body(fake_env, monkeypatch):
    tmp, lists, _ = fake_env
    host_python(monkeypatch)
    body = tmp / "rerank_stdin.py"
    body.write_text(f"META = {json.dumps(meta())!r}\nimport json as _j\nMETA = _j.loads(META)\n" + FAKE_BODY)
    monkeypatch.setattr(sc, "RERANK_STDIN", body)
    out = tmp / "s.jsonl"
    assert sc.main(["rerank", "--lists", str(lists), "--out", str(out), "--chunk", "1"]) == 0
    assert kinds(out) == ["meta", "Q1", "meta", "Q2", "refcheck"]
    assert sc.scan_jsonl(out).records[1]["scores"] == r_line("Q1", sc.pool_union("Q1", entry("a")))["scores"]


def test_a_rerank_output_is_accepted_by_the_pinned_evaluate_reader(fake_env, monkeypatch):
    """score.py rerank → _eval_inputs.Scores(pinned): the host part, run settings and the
    trailing refcheck that score.py writes are exactly what evaluate.py demands."""
    tmp, _, _ = fake_env
    spec = importlib.util.spec_from_file_location("gd_eval_inputs", _DIR / "_eval_inputs.py")
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    rows = {q: entry(q.lower()) for q in QSET.ids}
    lists = tmp / "pinned_lists.json"
    lists.write_text(json.dumps({"meta": {
        "set": "new82", "ids_sha256": QSET.ids_sha256, "build_id": gd.BUILD_ID,
        "layers": dict(gd.LAYER_VERSIONS), "vectors_sha256": gd.VECTORS_SHA256,
        "lists_sha256": gd.lists_sha256(rows), "query_vectors_meta": meta("embedder")}, "lists": rows}))
    host_python(monkeypatch)
    body = tmp / "rerank_stdin.py"
    body.write_text(f"META = {json.dumps(meta())!r}\nimport json as _j\nMETA = _j.loads(META)\n" + FAKE_BODY)
    monkeypatch.setattr(sc, "RERANK_STDIN", body)
    out = tmp / "s.jsonl"
    assert sc.main(["rerank", "--lists", str(lists), "--out", str(out), "--chunk", "2"]) == 0
    read = inputs.Lists(lists, QSET)
    scores = inputs.Scores(out, QSET, read.content_sha256)
    assert scores.pinned and len(scores.metas) == 2 and len(scores.refchecks) == 1
    assert set(scores.by_qid) == set(QSET.ids)
