"""Experiment A confirmation set: score_c regression (confirm_A.md §9 test 7), run_c guards (test 10), arms_c,
the trap-rule variants, the dry run and a synthetic end-to-end score → analyze → report.

Nothing launches an agent, calls Ollama or the backend; outputs are written under tmp_path. Tests that
read the store's layers or stage-0 outputs skip when the store is absent.
"""

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_kg_cards" / "A" / "confirm"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import c_common as C  # noqa: E402
import guards_c as G  # noqa: E402
import run_c as R  # noqa: E402

needs_store = pytest.mark.skipif(not C.LAYER_REF.is_file() or not (C.ST0 / "scores.json").is_file()
                                 or not C.SEGMENTS.is_file(), reason=f"store not mounted ({C.ST0})")


def wj(p: Path, obj) -> Path:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def layers():
    from regnal import load_auto, load_ref
    return load_auto(C.LAYER_AUTO), load_ref(C.LAYER_REF)


# ---------------------------------------------------------------- test 7: regression on stage-0
@needs_store
def test_7_score_c_reproduces_stage0_scores(layers):
    import arms_a
    import score_c
    meta = C.read_json(C.ST0 / "arms_meta.json")
    items = [it for it in C.read_json(C.ST0_ITEMS)["items"] if it["id"] in meta]
    by_job = C.cc.done_jobs(C.ST0 / "gen_arms.jsonl")
    # stage-0 reps (2 per arm, G-ref 1) and its template trap rule
    per, missing = score_c.score_items(items, meta, by_job, layers[1], 131072, arms_a.REPS, "template")
    want = C.read_json(C.ST0 / "scores.json")["items"]
    assert missing == [] and set(per) == set(want) and len(per) == 30
    assert all(per[i] == {"reps": want[i]["reps"], "mean": want[i]["mean"]} for i in want)


# ---------------------------------------------------------------- arms_c and trap rules
def test_arms_c_three_reps_rotation_and_abstention():
    import arms_c
    from arms_a import ARMS
    assert arms_c.REPS == {a: 3 for a in ARMS}
    srcs = [{"book_name": "b", "chapter_num": 1, "title": "", "verse_range": "", "content": "c"}]
    its = [{"id": f"X{i}", "question": "q", "sources": srcs} for i in range(3)]
    blocks = dict({a: "x" for a in ARMS}, B0="")
    built = {"X0": {"blocks": blocks}, "X1": {"blocks": dict(blocks, **{"G-auto": None})},
             "X2": {"blocks": dict(blocks, **{"G-ref": None, "G-auto": None})}}
    jobs = arms_c.arm_jobs(its, built)
    assert len(jobs) == 3 * 15 - 3 - 6 and [j["rep"] for j in jobs] == sorted(j["rep"] for j in jobs)
    rot = [a for a in ARMS[2:] + ARMS[:2] if a not in ("G-auto", "G-ref")]
    assert [j["arm"] for j in jobs if j["item"] == "X2" and j["rep"] == 1] == rot
    assert not any(j["arm"] == "G-auto" and j["item"] == "X1" for j in jobs)
    assert all(C.cc.AUX_LABEL not in j["user"] for j in jobs if j["arm"] == "B0")
    meta = {"X0": {"g_auto_fired": True, "g_ref_fired": True}, "X1": {"g_auto_fired": False, "g_ref_fired": True}}
    assert arms_c.expected_jobs(meta) == 30 - 3


@needs_store
def test_trap_rules_and_substitution(layers):
    import score_c
    from dry_run_c import synth_questions
    from items_c import to_item
    VA, VR = layers
    segs = C.read_json(C.SEGMENTS)["segments"]
    q = next(q for q in synth_questions(segs, VR) if q["segment"] == "I2" and q["qtype"] == "S1a" and q["k"] == 2)
    it = to_item(q, [], VR, segs)                                              # 巴沙 → 以拉 → 心利
    from keys_a import king_lexicon, score_line
    line = "經過以拉，第二位是心利"
    got = {r: score_line(score_c.rule_ctx(it, VR, king_lexicon(VR), r), line)["score"] for r in score_c.RULES}
    assert got == {"chain": 1.0, "template": 0.0, "none": 1.0}
    meta = {"g_auto_fired": False, "g_ref_fired": True}
    rec = {"job_id": "x", "content": "答案：心利", "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 10}
    by_job = {f"A|{it['id']}|T-rows|{r}": dict(rec, job_id=f"A|{it['id']}|T-rows|{r}") for r in (1, 2, 3)}
    out = score_c.arm_rep_scores(it, meta, by_job, score_c.rule_ctx(it, VR, king_lexicon(VR)), 131072)
    assert [out[("G-auto", r)]["job_id"] for r in (1, 2, 3)] == [f"A|{it['id']}|T-rows|{r}" for r in (1, 2, 3)]
    assert out[("G-auto", 2)]["substituted_from"] == "T-rows" and out[("G-ref", 1)] is None


# ---------------------------------------------------------------- test 10: run_c guards
def kay_rec(p: Path, n_wrong: int = 1, **over) -> Path:
    """A ho/kay/k0_1b.json as kay_a.py apply writes it."""
    wrong = [f"N{i:02d}" for i in range(n_wrong)]
    return wj(p, {"n": 20, "wrong": wrong, "n_wrong": n_wrong, "stop": n_wrong >= 2, "wording": "x", **over})


def k0_doc(kay: Path, **over):
    doc = {"K0_1": {"pass": True}, "K0_2": {"pass": True}, "K0_3": {"pass": True, "num_ctx": 131072},
           "K0_1b": G.k0_1b_from_kay(kay)}
    doc.update(over)
    return doc


def test_10_k0_gate(tmp_path):
    p, kay = tmp_path / "k0_status.json", kay_rec(tmp_path / "k0_1b.json")
    with pytest.raises(SystemExit, match="missing"):
        R.k0_gate(p, kay)
    R.k0_gate(wj(p, k0_doc(kay)), kay)
    for bad in (k0_doc(kay, K0_3={"pass": True, "num_ctx": 8192}), k0_doc(kay, K0_2={"pass": False}),
                {k: v for k, v in k0_doc(kay).items() if k != "K0_1b"},
                k0_doc(kay, K0_1b=G.k0_1b_record(1))):                         # typed by hand, not Kay's record
        with pytest.raises(SystemExit):
            R.k0_gate(wj(p, bad), kay)
    wj(p, k0_doc(kay))
    kay_rec(kay, 0)                                                            # Kay's record changed afterwards
    with pytest.raises(SystemExit, match="k0_1b.json"):
        R.k0_gate(p, kay)
    stop = kay_rec(tmp_path / "k0_1b_stop.json", 2)
    with pytest.raises(SystemExit, match="K0-1b＝2/20"):
        R.k0_gate(wj(p, k0_doc(stop)), stop)


def test_10_k0_1b_only_from_kay_record(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        G.k0_1b_from_kay(tmp_path / "none.json")
    for bad in ({"n_wrong": 3}, {"n": 19}, {"stop": True}):
        rec = wj(tmp_path / "bad.json", {**C.read_json(kay_rec(tmp_path / "bad.json", 1)), **bad})
        with pytest.raises(ValueError, match="inconsistent"):
            G.k0_1b_from_kay(rec)
    st0 = wj(tmp_path / "st0.json", {k: {"pass": True, "num_ctx": 131072} for k in G.K0_PASS})
    out = tmp_path / "k0_status.json"
    assert R.k0_status(st0, out, tmp_path / "none.json")["K0_1b"]["pass"] is None
    kay = kay_rec(tmp_path / "k0_1b.json", 1)
    doc = R.k0_status(st0, out, kay)
    assert doc["K0_1b"]["pass"] is True and doc["K0_1b"]["wrong"] == 1
    assert doc["K0_1b"]["src_sha256"] == C.sha256_file(kay) and G.k0_problems(out, kay) == []
    with pytest.raises(SystemExit):
        R.main(["k0-1b", "--wrong", "1"])                                     # the manual entry is gone


def test_10_num_ctx_only_131072():
    assert R.options(None) == R.options(131072) == dict(C.cc.OPTIONS, num_ctx=131072)
    with pytest.raises(SystemExit):
        R.options(8192)
    assert G.options_problems(dict(C.cc.OPTIONS, num_ctx=8192))


def test_10_frozen_sha(tmp_path):
    files = [wj(tmp_path / n, {"n": n}) for n in ("questions_frozen.json", "contexts.json")]
    files.append(wj(tmp_path / "items.json", {"inputs_sha256": {p.name: C.sha256_file(p) for p in files}}))
    man = tmp_path / "inputs_manifest.json"
    with pytest.raises(SystemExit):
        R.check_frozen(man, files)                                             # nothing recorded
    wj(man, {"frozen": {p.name: C.sha256_file(p) for p in files}})
    assert set(R.check_frozen(man, files)) == {p.name for p in files}
    wj(files[1], {"n": "changed"})
    with pytest.raises(SystemExit, match="contexts.json"):
        R.check_frozen(man, files)


def test_10_items_must_name_frozen_inputs(tmp_path):
    q, c = wj(tmp_path / "questions_frozen.json", [1]), wj(tmp_path / "contexts.json", [2])
    it = wj(tmp_path / "items.json", {"inputs_sha256": {"questions_frozen.json": "0", "contexts.json": "0"}})
    man = wj(tmp_path / "m.json", {"frozen": {p.name: C.sha256_file(p) for p in (q, c, it)}})
    assert G.frozen_problems(man, (q, c, it), stage0=False) == [
        "items.json built from another questions_frozen.json", "items.json built from another contexts.json"]


def test_10_prompt_sha(monkeypatch):
    R.check_prompts()
    good = {"job_id": "j", "system": C.cc.SYSTEM_PROMPT, "user": "u"}
    R.check_prompts(arm_jobs=[good])
    with pytest.raises(SystemExit, match="arm system prompt"):
        R.check_prompts(arm_jobs=[dict(good, system=C.cc.SYSTEM_PROMPT + " ")])
    monkeypatch.setattr(C.cc, "USER_TEMPLATE", C.cc.USER_TEMPLATE + "x")
    with pytest.raises(SystemExit, match="user_template"):
        R.check_prompts()


def test_10_rerun_guard(tmp_path):
    out, opts, frozen = tmp_path / "gen_arms.jsonl", dict(C.OPTIONS), {"items.json": "a"}
    meta = R.guard(out, opts, "s", "arms", frozen)
    wj(tmp_path / "run_meta_arms.json", meta)
    assert R.guard(out, opts, "s", "arms", frozen)["resumed"]
    for args in ((dict(opts, num_ctx=8192), "s", frozen), (opts, "other", frozen), (opts, "s", {"items.json": "b"})):
        with pytest.raises(SystemExit):
            R.guard(out, args[0], args[1], "arms", args[2])
    (tmp_path / "run_meta_arms.json").unlink()
    out.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        R.guard(out, opts, "s", "arms", frozen)


def test_10_canary(tmp_path):
    its = [{"id": "X"}]
    jobs = [{"job_id": f"A|X|B0|{r}"} for r in (1, 2, 3)]
    rec = {"type": "answer", "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}
    lines = lambda recs: "".join(json.dumps(r) + "\n" for r in recs)  # noqa: E731
    (tmp_path / "gen_seed.jsonl").write_text(lines([dict(rec, job_id="A|X|seed|1")]), encoding="utf-8")
    arms = [dict(rec, job_id=j["job_id"]) for j in jobs]
    (tmp_path / "gen_arms.jsonl").write_text(lines(arms), encoding="utf-8")
    assert R.canary_status(tmp_path, its, jobs, 131072)["pass"]
    err = {"type": "error", "job_id": "A|X|B0|2", "error": "x"}
    (tmp_path / "gen_arms.jsonl").write_text(lines([err] + arms), encoding="utf-8")
    st = R.canary_status(tmp_path, its, jobs, 131072)
    assert not st["pass"] and st["arm_errors"] == 1
    assert R.canary_status(tmp_path, its, jobs, 131072, R.canary_errors(tmp_path, its, jobs))["pass"]
    arms[0]["done_reason"] = "length"
    (tmp_path / "gen_arms.jsonl").write_text(lines(arms), encoding="utf-8")
    st = R.canary_status(tmp_path, its, jobs, 131072)
    assert st["arm_truncated"] == ["A|X|B0|1"] and "content" not in json.dumps(st)
    assert st["pass"]                                                      # truncation = format failure, not a stop
    seed = dict(rec, job_id="A|X|seed|1", done_reason="length")
    (tmp_path / "gen_seed.jsonl").write_text(lines([seed]), encoding="utf-8")
    st = R.canary_status(tmp_path, its, jobs, 131072)
    assert st["seed_truncated"] == ["A|X|seed|1"] and st["pass"]


def test_10_canary_cli_applies_recorded_ignore(tmp_path):
    its = [{"id": "X"}]
    jobs = [{"job_id": f"A|X|B0|{r}"} for r in (1, 2, 3)]
    rec = {"type": "answer", "done_reason": "stop", "prompt_eval_count": 1, "eval_count": 1}
    lines = lambda recs: "".join(json.dumps(r) + "\n" for r in recs)  # noqa: E731
    (tmp_path / "gen_seed.jsonl").write_text(lines([dict(rec, job_id="A|X|seed|1")]), encoding="utf-8")
    err = {"type": "error", "job_id": "A|X|B0|2", "error": "x"}
    (tmp_path / "gen_arms.jsonl").write_text(lines([err] + [dict(rec, job_id=j["job_id"]) for j in jobs]),
                                             encoding="utf-8")
    can = tmp_path / "canary.json"
    assert R.recorded_ignore(can) == {}
    ignore = R.canary_errors(tmp_path, its, jobs)
    st = R.canary_status(tmp_path, its, jobs, 131072, ignore)
    R.record_canary(st, "fixed the socket", ignore, can)
    assert C.read_json(can)["pass"] and R.recorded_ignore(can) == ignore
    assert R.canary_status(tmp_path, its, jobs, 131072, R.recorded_ignore(can))["pass"]   # CLI agrees with canary.json


def test_10_code_guard(tmp_path):
    here = tmp_path / "code"
    here.mkdir()
    (here / "a.py").write_text("x = 1\n", encoding="utf-8")
    man = tmp_path / "inputs_manifest.json"
    with pytest.raises(SystemExit, match="prepare"):
        R.check_code(None, man, here)
    wj(man, {"frozen": {}, "code_confirm": G.code_sha(here)})
    assert R.check_code(None, man, here) == []
    (here / "a.py").write_text("x = 2\n", encoding="utf-8")
    (here / "b.py").write_text("y = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="--code-change"):
        R.check_code(None, man, here)
    assert R.check_code("retry on socket reset", man, here) == ["a.py", "b.py"]
    doc = C.read_json(man)
    assert doc["code_confirm"] == G.code_sha(here) and doc["frozen"] == {}
    assert [(c["files"], c["note"]) for c in doc["code_changes"]] == [(["a.py", "b.py"], "retry on socket reset")]
    assert R.check_code(None, man, here) == []                             # re-pinned after the logged change


# ---------------------------------------------------------------- dry run and end to end
@needs_store
def test_dry_run_builds_every_prompt(tmp_path):
    from dry_run_c import dry_run
    s = dry_run(out_dir=tmp_path)
    assert s["ok"] and s["prompt_sha_ok"] and s["prompt_sha256"] == C.PROMPT_SHA
    assert s["n_items"] == 44 and s["n_arm_jobs"] == 15 * 44 and s["context_n_aux"] == 15


def answer(it, arm, VR) -> str:
    key = it["keys"][0]
    right = f"{key['value']}次" if key["type"] == "number" else VR.nodes[it["gold"][0]]["name"]
    if arm in ("G-auto", "G-ref"):
        mid = [VR.nodes[x]["name"] for x in it["path"][1:-1]]
        return f"推理\n答案：經過{'、'.join(mid)}，{right}" if mid and key["type"] == "name" else f"答案：{right}"
    return "答案：不知道" if arm != "B0" else "沒有答案行"


def synth_night(tmp_path, VR, answer_fn=answer):
    """dry run + synthetic seed and arm answers + manifest, run_meta, k0, k1 → analyze_c arguments."""
    import score_c
    from dry_run_c import dry_run
    dry_run(out_dir=tmp_path)
    jobs, items = C.read_json(tmp_path / "arms_jobs.json"), C.read_json(tmp_path / "items.json")["items"]
    by_id = {it["id"]: it for it in items}
    rec = {"type": "answer", "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 50}
    with (tmp_path / "gen_arms.jsonl").open("w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(dict(rec, job_id=j["job_id"], content=answer_fn(by_id[j["item"]], j["arm"], VR)),
                               ensure_ascii=False) + "\n")
    with (tmp_path / "gen_seed.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(dict(rec, job_id=f"A|{it['id']}|seed|1", content="x"), ensure_ascii=False) + "\n")
    files = [tmp_path / n for n in ("questions_frozen.json", "contexts.json", "items.json")]
    frozen = {p.name: C.sha256_file(p) for p in files}
    man = wj(tmp_path / "inputs_manifest.json", {"frozen": frozen})
    for tag, js in (("arms", jobs), ("seeds", [])):
        wj(tmp_path / f"run_meta_{tag}.json", {"options": dict(C.OPTIONS), "frozen": frozen,
                                                "prompts_sha256": C.ac.prompts_sha256(js)})
    kay = kay_rec(tmp_path / "k0_1b.json")
    k0, k1 = wj(tmp_path / "k0.json", k0_doc(kay)), wj(tmp_path / "k1.json", {"stop": False, "wording": "K1 過"})
    sc = score_c.score_all(tmp_path, tmp_path / "items.json")
    assert sc["missing_jobs"] == [] and sc["n_units"] == 14
    return (tmp_path, tmp_path / "items.json", k0, k1, man, files, kay), frozen


@needs_store
def test_end_to_end_synthetic(tmp_path, layers):
    import analyze_c
    VA, VR = layers
    args, frozen = synth_night(tmp_path, VR)
    _d, _it, k0, k1, man, files, kay = args
    rep = analyze_c.analyze(*args)
    assert rep["verdict"]["result"] == "H1、H2 皆過", rep["verdict"]
    assert rep["sequence"]["H1"]["delta"] == pytest.approx(1.0) and rep["sequence"]["H2"]["tested"]
    tmpl = rep["descriptive"]["trap_rule_sensitivity"]["template"]["G-auto−T-canon"]
    assert tmpl["delta"] < 1.0                                                 # intermediates trap the template rule
    assert rep["k3"]["flag"] is False and rep["calls"]["B0"]["format_fail"] == rep["calls"]["B0"]["n_calls"]
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert C.WORDING["h1_h2"] in md and "合成" not in md
    assert rep["code_changes"] == [] and "程式修改" in md and "0 次" in md
    wj(man, {"frozen": dict(frozen, **{"items.json": "0" * 64})})
    assert analyze_c.analyze(tmp_path, tmp_path / "items.json", k0, k1, man, files, kay)["verdict"]["result"] == "作廢"


def h2_entries(doc):
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "G-auto−T-rows" and isinstance(v, dict):
                yield v
            yield from h2_entries(v)


@needs_store
def test_end_to_end_h1_fails_reports_no_h2_p(tmp_path, layers):
    import analyze_c
    VA, VR = layers

    def no_card(it, arm, VR_):                                     # G-auto answers like the text window
        return answer(it, "T-canon" if arm == "G-auto" else arm, VR_)
    args, _ = synth_night(tmp_path, VR, no_card)
    rep = analyze_c.analyze(*args)
    assert rep["verdict"]["result"] == "H1 未過" and rep["sequence"]["H2"]["tested"] is False
    saved = C.read_json(tmp_path / "report.json")
    found = list(h2_entries(saved))
    assert len(found) >= 4 and not [t for t in found if "p" in t or "p_signflip" in t or "exact" in t]
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    h2_rows = [x for x in md.splitlines() if "G-auto−T-rows" in x]
    assert h2_rows and all("未檢定" in x for x in h2_rows)

