"""GD experiment container runner (experiments/2026-10-14_graph_gd/score.py, _score_io.py).

Unit tests run without the container: the stdin payload, the container scripts' §3
constants, the pool union, scores-file scanning and the resume bookkeeping (meta pins and
run settings, the lists content hash and scorer scripts recorded in every meta line,
refcheck lines). The rerank / refpairs / encode flows against fake containers are in
test_graph_gd_score_flows.py, the store-backed checks in test_graph_gd_score_store.py.
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
if "gd_common" in sys.modules:
    gd = sys.modules["gd_common"]
else:
    _GD = importlib.util.spec_from_file_location("gd_common", _DIR / "gd_common.py")
    gd = importlib.util.module_from_spec(_GD)
    sys.modules["gd_common"] = gd
    _GD.loader.exec_module(gd)
_SPEC = importlib.util.spec_from_file_location("graph_gd_score", _DIR / "score.py")
sc = importlib.util.module_from_spec(_SPEC)
sys.modules["graph_gd_score"] = sc        # dataclasses resolve annotations through sys.modules
_SPEC.loader.exec_module(sc)

SCRIPTS = {name: name[0] * 64 for name in ("score.py", "_score_io.py", "rerank_stdin.py")}


def dense(tag="d"):
    return [f"ps:{tag}.{i}" for i in range(30)]


def entry(tag="d", gd_extra=("ps:g.1", "ps:g.2")):
    d30 = dense(tag)
    return {"D30": d30, "C": d30[20:30], "GD": list(gd_extra), "L": ["ps:l.1", d30[25]]}


def meta(kind="reranker", **over):
    line = {"type": "meta", "build_id": gd.BUILD_ID,
            f"{kind}_fingerprint": gd.expected_fingerprint(kind), **gd.RUN_SETTINGS[kind]}
    return {**line, **over}


def r_line(sid, pids, **over):
    return {"type": "r", "sid": sid, "scores": {p: 1.0 / (2 + i) for i, p in enumerate(pids)},
            "missing": [], "elapsed_s": 0.5, **over}


def jsonl(lines):
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)


# ---------------------------------------------------------------- payload and container scripts

def test_the_payload_is_base64_utf8_json_on_a_line_before_the_body():
    items = [{"sid": "N_KIN_01", "query": "摩西和亞倫是什麼關係？", "pids": ["ps:exo.6.14"]}]
    body = "import base64, json\nOUT = json.loads(base64.b64decode(PAYLOAD_B64).decode('utf-8'))\n"
    script = sc.build_script(body, items)
    first, rest = script.split("\n", 1)
    assert first.startswith('PAYLOAD_B64 = "') and rest == body
    ns = {}
    exec(compile(script, "<stdin>", "exec"), ns)  # what python -B - does with it
    assert ns["OUT"] == items


def _constants(tree):
    return {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}


@pytest.mark.parametrize("name", ["encode_stdin.py", "rerank_stdin.py", "rerank_w_stdin.py"])
def test_container_scripts_read_the_payload_and_write_no_files(name):
    tree = ast.parse((_DIR / name).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "PAYLOAD_B64" in names
    assert not calls & {"open", "write_text", "write_bytes", "save", "dump", "savez"}
    assert "retrieve_dense" not in calls          # encode returns vectors only


@pytest.mark.parametrize("name", ["rerank_stdin.py", "rerank_w_stdin.py"])
def test_rerank_scripts_use_the_section_3_batch_and_threads(name):
    consts = _constants(ast.parse((_DIR / name).read_text(encoding="utf-8")))
    assert consts["BATCH"] == 16 and consts["TORCH_THREADS"] == 12


# ---------------------------------------------------------------- pool union

def test_the_union_is_the_dense_head_and_every_arms_extra_in_pid_order():
    e = entry()
    union = sc.pool_union("Q1", e)
    want = set(e["D30"][:20]) | set(e["C"]) | set(e["GD"]) | set(e["L"])
    assert union == tuple(sorted(want)) and len(union) == len(want)
    assert set(e["D30"][20:30]) <= set(union)                  # C's extra is D[20:30]


def test_an_arm_may_bring_fewer_than_ten_or_no_passages():
    assert sc.pool_union("Q1", {**entry(), "GD": []}) == sc.pool_union(
        "Q1", {"D30": dense(), "C": dense()[20:30], "L": ["ps:l.1", dense()[25]]})


@pytest.mark.parametrize("change", [
    {"GD": ["ps:d.3"]},                                   # inside D[0:20]
    {"GD": [f"ps:g.{i}" for i in range(11)]},             # more than 10
    {"GD": ["ps:g.1", "ps:g.1"]},                         # repeated
    {"D30": dense()[:29]},                                # not 30
    {"D30": dense()[:29] + ["ps:d.0"]},                   # not distinct
])
def test_malformed_lists_are_rejected(change):
    with pytest.raises(gd.IntegrityError):
        sc.pool_union("Q1", {**entry(), **change})


def test_a_question_without_arms_is_rejected():
    with pytest.raises(gd.IntegrityError):
        sc.pool_union("Q1", {"D30": dense()})


# ---------------------------------------------------------------- scanning and resume bookkeeping

def test_scan_keeps_complete_lines_and_marks_an_unterminated_tail(tmp_path):
    path = tmp_path / "s.jsonl"
    whole = jsonl([meta(), r_line("Q1", ["ps:a"])])
    path.write_text(whole + '{"type": "r", "sid": "Q2", "sco', encoding="utf-8")
    scan = sc.scan_jsonl(path)
    assert [r["type"] for r in scan.records] == ["meta", "r"]
    assert scan.cut_tail and scan.keep_bytes == len(whole.encode("utf-8"))


def test_scan_treats_an_unparsable_last_line_as_cut_but_not_a_middle_one(tmp_path):
    good = jsonl([meta()])
    last = tmp_path / "last.jsonl"
    last.write_text(good + '{"type": "r", "si\n', encoding="utf-8")
    scan = sc.scan_jsonl(last)
    assert scan.cut_tail and scan.keep_bytes == len(good.encode("utf-8"))
    middle = tmp_path / "middle.jsonl"
    middle.write_text(good + "{oops\n" + jsonl([meta()]), encoding="utf-8")
    with pytest.raises(gd.IntegrityError, match="line 2"):
        sc.scan_jsonl(middle)


def test_scan_of_a_missing_or_complete_file(tmp_path):
    assert sc.scan_jsonl(tmp_path / "none.jsonl") == sc.Scan((), 0, False)
    path = tmp_path / "s.jsonl"
    path.write_text(jsonl([meta()]), encoding="utf-8")
    assert not sc.scan_jsonl(path).cut_tail


EXPECTED = {"Q1": ("ps:a", "ps:b"), "Q2": ("ps:c",)}


def host_meta_line(lists_sha="L" * 64, scripts=None, **over):
    return {**meta(**over), "host": {"lists_sha256": lists_sha, "sha256": dict(scripts or SCRIPTS)}}


def refcheck_line(**over):
    return {"type": "refcheck", "n_pairs": 32, "max_abs_diff": 3e-7, "pass": True,
            "container_meta": meta(), **over}


def test_completed_counts_questions_scored_exactly_on_their_union():
    lines = [host_meta_line(), r_line("Q1", ["ps:a", "ps:b"]), refcheck_line()]
    assert sc.completed(lines, EXPECTED, "L" * 64, SCRIPTS) == {"Q1"}
    assert not sc.needs_refcheck(lines) and sc.needs_refcheck(lines[:2])
    assert sc.needs_refcheck(lines + [r_line("Q2", ["ps:c"])]) and not sc.needs_refcheck(lines[:1])


@pytest.mark.parametrize("lines", [
    [r_line("Q1", ["ps:a", "ps:b"])],                                     # no meta line first
    [host_meta_line(), r_line("Q1", ["ps:a"])],                            # pids differ
    [host_meta_line(), r_line("Q1", ["ps:a", "ps:b"], missing=["ps:b"])],  # build lacks a pid
    [host_meta_line(), r_line("Q1", ["ps:a", "ps:b"], scores={"ps:a": 1, "ps:b": 0.5})],
    [host_meta_line(), r_line("Q1", ["ps:a", "ps:b"], scores={"ps:a": 1.5, "ps:b": 0.5})],
    [host_meta_line(), r_line("Q9", ["ps:a"])],                            # not in the lists
    [host_meta_line(), r_line("Q2", ["ps:c"]), r_line("Q2", ["ps:c"])],    # scored twice
    [host_meta_line(lists_sha="X" * 64), r_line("Q2", ["ps:c"])],          # other lists.json
    [host_meta_line(scripts={**SCRIPTS, "_score_io.py": "0" * 64})],       # other scorer code
    [host_meta_line(), r_line("Q2", ["ps:c"]), refcheck_line(**{"pass": False, "max_abs_diff": 0.1})],
    [host_meta_line(), refcheck_line(container_meta=meta(batch=8))],
])
def test_completed_refuses_foreign_or_inconsistent_lines(lines):
    with pytest.raises(gd.IntegrityError):
        sc.completed(lines, EXPECTED, "L" * 64, SCRIPTS)


@pytest.mark.parametrize("over", [
    {"build_id": "b20261008_e0b00000"},
    {"reranker_fingerprint": {**gd.expected_fingerprint("reranker"), "unk_count": 3}},
    {"reranker_fingerprint": {**gd.expected_fingerprint("reranker"), "revision": "0" * 40}},
    {"batch": 99}, {"torch_threads": 1}, {"device": "cuda"},
])
def test_completed_checks_every_meta_line_against_the_pins(over):
    with pytest.raises(gd.IntegrityError):
        sc.completed([host_meta_line(**over)], EXPECTED, "L" * 64, SCRIPTS)


def test_the_refcheck_record_lists_every_pair_and_strips_the_host_part():
    ref = [("Q1", "ps:a", 0.5), ("Q1", "ps:b", 0.25)]
    rec = sc.refcheck_record(ref, {"Q1": {"ps:a": 0.5 + 2e-6, "ps:b": 0.25}},
                             {**meta(), "host": {"x": 1}, "chunk": ["Q1"]})
    assert rec["pass"] and rec["max_abs_diff"] == pytest.approx(2e-6) and rec["n_pairs"] == 2
    assert rec["container_meta"] == meta() and rec["pairs"][1] == ["Q1", "ps:b", 0.25, 0.25, 0.0]
    bad = sc.refcheck_record(ref, {"Q1": {"ps:a": 0.6, "ps:b": 0.25}}, meta())
    assert not bad["pass"]
