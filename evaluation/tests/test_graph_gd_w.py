"""GD experiment §3 W (逐窗重排): the window port and the W file format
(experiments/2026-10-14_graph_gd/rerank_w_stdin.py, _score_w.py).

windows() and score() are executed on the host from rerank_w_stdin.py's source with a
one-token-per-character tokenizer: a single window when blocks + separators fit, the
one-block overlap, a too-long block alone, the next start max(j − 1, i + 1). With the store
mounted, the port is the archived WF/exp/rr_probe_in_container.py code (same AST) and
behaves the same on random contents. The W lines (single-window passages carry their
whole-passage score), the whole-score and W readers (content hashes, arms, scripts,
refcheck, coverage) run on synthetic files. rerank-w flows: test_graph_gd_score_w.py.
"""

import ast
import importlib.util
import json
import random
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
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))
import _score_w as sw  # noqa: E402

ARCHIVED = gd.WF / "exp" / "rr_probe_in_container.py"
ARCHIVED_SHA = "24a3a1438944e3b0fe89efab452729933d094446ea6ceddc9bae02645a0ba809"
needs_store = pytest.mark.skipif(not ARCHIVED.is_file(), reason=f"store not mounted ({gd.STORE})")
SCRIPTS = {name: name[1] * 64 for name in sw.W_SCRIPT_NAMES}
WHOLE_SCRIPTS = {"score.py": "s" * 64, "_score_io.py": "i" * 64, "rerank_stdin.py": "r" * 64}


def functions(path, names=("windows", "score")):
    text = Path(path).read_text(encoding="utf-8")
    return {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name in names}, text


def load_port(path=_DIR / "rerank_w_stdin.py", **env):
    """windows / score of a container script, executed with MAXLEN (and BATCH, reranker)."""
    nodes, text = functions(path)
    ns = {"MAXLEN": 512, "BATCH": 16, **env}
    for node in nodes.values():
        exec(compile(ast.get_source_segment(text, node), str(path), "exec"), ns)
    return ns


def char_tok(text, add_special_tokens=False):
    assert add_special_tokens is False            # the port calls the tokenizer this way only
    return {"input_ids": list(text)}


PORT = load_port()


# ---------------------------------------------------------------- windows() (§3 W)

def test_a_passage_that_fits_the_budget_is_one_window_of_its_whole_content():
    q = "問" * 8                                  # budget 512 − 8 − 4 = 500
    fits = "\n\n".join(["甲" * 249, "乙" * 249])   # (249 + 1) · 2 = 500
    assert PORT["windows"](char_tok, q, fits) == [fits]
    over = fits + "丙"
    assert len(PORT["windows"](char_tok, q, over)) == 2


def test_windows_overlap_by_one_block_and_restart_at_max_j_minus_1_i_plus_1():
    q = "問" * 8
    blocks = ["a" * 199, "b" * 199, "c" * 199, "d" * 199]       # 200 tokens each with the +1
    ws = PORT["windows"](char_tok, q, "\n\n".join(blocks))
    assert ws == ["\n\n".join(blocks[0:2]), "\n\n".join(blocks[1:3]), "\n\n".join(blocks[2:4])]


def test_a_block_longer_than_the_budget_is_a_window_of_its_own():
    q = "問" * 8
    blocks = ["a" * 50, "b" * 700, "c" * 50]
    ws = PORT["windows"](char_tok, q, "\n\n".join(blocks))
    # [a] cannot take b; b alone (j == i); next start max(j − 1, i + 1) = 2 → [c]
    assert ws == [blocks[0], blocks[1], blocks[2]]
    assert PORT["windows"](char_tok, q, "x" * 900) == ["x" * 900]


def test_score_takes_batches_of_sixteen_and_keeps_the_window_order():
    calls = []

    class Reranker:
        @staticmethod
        def rerank(q, batch, top_k):
            calls.append(len(batch))
            out = [{**b, "rerank_score": float(b["content"])} for b in batch]
            return sorted(out, key=lambda r: -r["rerank_score"])[:top_k]

    ns = load_port(reranker=Reranker)
    texts = [str(i / 100) for i in range(37)]
    assert ns["score"]("q", texts) == [i / 100 for i in range(37)] and calls == [16, 16, 5]


def random_content(rng):
    blocks = ["".join(rng.choice("甲乙丙丁戊**12 \n") for _ in range(rng.choice((0, 1, 5, 40, 120, 300, 700))))
              for _ in range(rng.randint(1, 12))]
    return "\n\n".join(blocks)


@needs_store
def test_the_port_is_the_archived_code_statement_for_statement():
    gd.read_pinned(ARCHIVED, ARCHIVED_SHA)                 # the canonical file, unchanged
    old, _ = functions(ARCHIVED)
    new, _ = functions(_DIR / "rerank_w_stdin.py")
    for name in ("windows", "score"):
        assert ast.dump(new[name]) == ast.dump(old[name]), name


@needs_store
@pytest.mark.parametrize("seed", range(4))
def test_the_port_cuts_like_the_archived_windows_on_random_contents(seed):
    rng = random.Random(seed)
    gd.read_pinned(ARCHIVED, ARCHIVED_SHA)
    old = load_port(ARCHIVED)
    for _ in range(300):
        q, content = "問" * rng.randint(0, 120), random_content(rng)
        assert PORT["windows"](char_tok, q, content) == old["windows"](char_tok, q, content)


def test_the_stdin_constants_match_the_w_format():
    tree = ast.parse((_DIR / "rerank_w_stdin.py").read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assert (consts["MAXLEN"], consts["BATCH"], consts["TORCH_THREADS"]) == (sw.W_MAX_LENGTH, 16, 12)


# ---------------------------------------------------------------- W lines

WHOLE = {"Q1": {"ps:a": 0.5, "ps:b": 0.25, "ps:c": 0.125}}
EXPECTED = {"Q1": ("ps:a", "ps:b", "ps:c")}


def container_line(**over):
    return {"type": "w", "sid": "Q1", "scores": {"ps:b": 0.75}, "missing": [], "elapsed_s": 1.5,
            "n_windows": {"ps:a": 1, "ps:b": 3, "ps:c": 1}, **over}


def test_single_window_passages_take_their_whole_score_and_multi_window_their_maximum():
    item = {"sid": "Q1", "pids": list(EXPECTED["Q1"])}
    sw.check_w_container_line(container_line(), item)
    line = sw.complete_w_line(container_line(), WHOLE)
    assert line == {"type": "w", "sid": "Q1", "scores": {"ps:a": 0.5, "ps:b": 0.75, "ps:c": 0.125},
                    "n_windows": {"ps:a": 1, "ps:b": 3, "ps:c": 1}, "elapsed_s": 1.5}
    sw.check_w_record(line, EXPECTED, WHOLE)
    assert sw.scored_windows(line) == 3


@pytest.mark.parametrize("over", [
    {"missing": ["ps:c"]}, {"type": "r"},
    {"n_windows": {"ps:a": 1, "ps:b": 3}},                       # a pool passage without windows
    {"n_windows": {"ps:a": 0, "ps:b": 3, "ps:c": 1}},
    {"scores": {"ps:b": 0.75, "ps:a": 0.5}},                     # a single-window passage scored
    {"scores": {}}, {"scores": {"ps:b": 1.5}}, {"scores": {"ps:b": 1}},
])
def test_malformed_container_lines_are_refused(over):
    with pytest.raises(gd.IntegrityError):
        sw.check_w_container_line(container_line(**over), {"sid": "Q1", "pids": list(EXPECTED["Q1"])})


@pytest.mark.parametrize("change", [
    lambda line: {**line, "scores": {**line["scores"], "ps:a": 0.5000001}},   # not the whole score
    lambda line: {**line, "scores": {k: v for k, v in line["scores"].items() if k != "ps:c"}},
    lambda line: {**line, "n_windows": {**line["n_windows"], "ps:x": 1}},
    lambda line: {**line, "sid": "Q9"},
    lambda line: {**line, "type": "r"},
])
def test_a_w_line_must_cover_the_pool_and_keep_whole_scores_on_single_windows(change):
    with pytest.raises(gd.IntegrityError):
        sw.check_w_record(change(sw.complete_w_line(container_line(), WHOLE)), EXPECTED, WHOLE)


def test_the_scores_content_hash_ignores_order_but_not_values():
    a = sw.scores_content_sha256({"Q2": {"ps:b": 0.1, "ps:a": 0.2}, "Q1": {"ps:a": 0.3}})
    b = sw.scores_content_sha256({"Q1": {"ps:a": 0.3}, "Q2": {"ps:a": 0.2, "ps:b": 0.1}})
    c = sw.scores_content_sha256(MappingProxyType({"Q1": MappingProxyType({"ps:a": 0.3}),
                                                   "Q2": {"ps:a": 0.2, "ps:b": 0.1 + 1e-12}}))
    assert a == b != c


# ---------------------------------------------------------------- readers

QSET = gd.QuestionSet("new82", (gd.Question("Q1", "?", gd.KIN, (("gen.1.1",),), frozenset()),),
                      MappingProxyType({}))
STRICT = {"type": "meta", "build_id": gd.BUILD_ID, "device": "cpu", "batch": 16, "torch_threads": 12,
          "reranker_fingerprint": gd.expected_fingerprint("reranker")}
REFCHECK = {"type": "refcheck", "n_pairs": 32, "max_abs_diff": 0.0, "pass": True, "container_meta": STRICT}


def entry():
    d30 = [f"ps:d{i:02d}" for i in range(30)]
    return {"D30": d30, "C": d30[20:], "GD": ["ps:g1", "ps:g2"], "L": ["ps:l1"]}


LISTS = {"Q1": entry()}
POOL = tuple(sorted(set(entry()["D30"]) | {"ps:g1", "ps:g2"}))


def whole_lines(arms=None, lists_sha=None, **host):
    pids = sorted(set(POOL) | ({"ps:l1"} if arms is None or "L" in arms else set()))
    meta = {**STRICT, "host": {"lists_sha256": lists_sha or gd.lists_sha256(LISTS), "set": "new82",
                               "set_ids_sha256": QSET.ids_sha256, "sha256": WHOLE_SCRIPTS,
                               **({} if arms is None else {"arms": list(arms)}), **host}}
    r = {"type": "r", "sid": "Q1", "scores": {p: 0.5 - i / 100 for i, p in enumerate(pids)},
         "missing": [], "elapsed_s": 1.0}
    return [meta, r, REFCHECK]


def write(path, lines):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


@pytest.mark.parametrize("arms", [None, ("C", "GD"), ("C", "GD", "L")])
def test_whole_scores_load_from_a_finished_rerank_file_with_c_and_gd(tmp_path, arms):
    path = write(tmp_path / "s.jsonl", whole_lines(arms))
    whole = sw.read_whole_scores(path, QSET, LISTS, gd.lists_sha256(LISTS))
    assert whole.arms == arms and set(POOL) <= set(whole.by_qid["Q1"])
    assert whole.content_sha256 == sw.scores_content_sha256(whole.by_qid)


@pytest.mark.parametrize("lines", [
    lambda: whole_lines(("C",)),                                    # GD's pool not scored
    lambda: whole_lines(lists_sha="0" * 64),                        # another lists file
    lambda: whole_lines(set="old31"),
    lambda: whole_lines()[:2],                                      # no refcheck after the r line
    lambda: [whole_lines()[0], whole_lines()[2]],                   # Q1 not scored
    lambda: [{**whole_lines()[0], "batch": 8}, *whole_lines()[1:]],
    lambda: [whole_lines()[0], whole_lines(("C", "GD"))[0], *whole_lines()[1:]],   # arms differ
])
def test_whole_scores_refuse_files_w_cannot_build_on(tmp_path, lines):
    with pytest.raises(gd.IntegrityError):
        sw.read_whole_scores(write(tmp_path / "s.jsonl", lines()), QSET, LISTS, gd.lists_sha256(LISTS))


def w_file_lines(whole, **host):
    n = {p: (2 if i % 3 == 0 else 1) for i, p in enumerate(POOL)}
    scores = {p: (0.9 if n[p] > 1 else whole["Q1"][p]) for p in POOL}
    meta = {**STRICT, "window_max_length": 512,
            "host": {"kind": "rerank-w", "lists_sha256": gd.lists_sha256(LISTS),
                     "scores_sha256": sw.scores_content_sha256(whole), "arms": ["C", "GD"],
                     "set": "new82", "set_ids_sha256": QSET.ids_sha256, "sha256": SCRIPTS, **host}}
    return [meta, {"type": "w", "sid": "Q1", "scores": scores, "n_windows": n, "elapsed_s": 2.0}, REFCHECK]


def read(tmp_path, lines, whole):
    return sw.read_w(write(tmp_path / "w.jsonl", lines), QSET, {"Q1": POOL}, whole, gd.lists_sha256(LISTS))


def test_a_w_file_bound_to_these_lists_and_whole_scores_is_read(tmp_path):
    whole = {"Q1": whole_lines()[1]["scores"]}
    by_qid, metas, n_ref = read(tmp_path, w_file_lines(whole), whole)
    assert by_qid["Q1"]["ps:d00"] == 0.9 and len(metas) == 1 and n_ref == 1


@pytest.mark.parametrize("change", [
    lambda m, w, r: [{**m, "host": {**m["host"], "lists_sha256": "0" * 64}}, w, r],
    lambda m, w, r: [{**m, "host": {**m["host"], "scores_sha256": "0" * 64}}, w, r],
    lambda m, w, r: [{**m, "host": {**m["host"], "arms": ["C", "GD", "L"]}}, w, r],
    lambda m, w, r: [{**m, "host": {**m["host"], "kind": "rerank"}}, w, r],
    lambda m, w, r: [{**m, "host": {**m["host"], "set": "old31"}}, w, r],
    lambda m, w, r: [{**m, "window_max_length": 256}, w, r],
    lambda m, w, r: [{**m, "torch_threads": 6}, w, r],
    lambda m, w, r: [m, w],                                                     # no refcheck
    lambda m, w, r: [m, r],                                                     # Q1 not W-scored
    lambda m, w, r: [m, w, r, {**m, "host": {**m["host"], "sha256": {**SCRIPTS, "_score_w.py": "0" * 64}}}],
    lambda m, w, r: [m, {**w, "scores": {**w["scores"], "ps:d01": 0.123}}, r],  # a single window rescored
])
def test_w_files_that_cannot_prove_their_binding_are_refused(tmp_path, change):
    whole = {"Q1": whole_lines()[1]["scores"]}
    with pytest.raises(gd.IntegrityError):
        read(tmp_path, change(*w_file_lines(whole)), whole)
