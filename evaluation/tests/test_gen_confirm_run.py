"""GEN confirmation set: arms, scoring and the driver's runs (arms_g, score_g, run_g, f1_g's records; prereg §4, §6).

Ollama and every LLM are never called: chats are fakes passed to ``execute`` (or put in place of cards_common.chat
inside it), every /api answer comes from a fake ``get``, the K0 test-suite run of the harness record is a fake.
The synthetic tests run on a made-up two-chapter layer, names file, pool, writing order, contexts and questions
(every name, number and string made up; this file shares no 8-character window with the text layer) in temporary
directories, so nothing is written to the store or the repository; and every store path the real line writes
later (every g_common path under OUT_ROOT but pool.json, gen_names.json and power/, with each module alias and
function default bound to one) points into tmp for each test (``later_store_files_in_tmp``, autouse here and in
the files that import it), so the store's later files never change what a test reads. Covered: the
frozen-question contract and the writing order; arms, prompts and the arm rotation; the abstention and G-ref reuse
(an abstained item's G = T-rows = B0 per rep, byte-identical prompts); scoring, truncation and the void counts; the
Ollama checks, the canary and resuming; the anchors, the harness record and --infra-fix; the modules the runners
load. §4.5's gates, the build, the dry run, the formal run, score and analyze, the F1 manifest and F2 are
test_gen_confirm_gates's; the smoke, its redo and its truncation void test_gen_confirm_smoke's (both import the
synthetic set, the fakes and the fixtures from here).
Every negative case is one rule of the prereg (named by its section, or the review id it closes).
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import arms_g as A  # noqa: E402
import f1_g as F1  # noqa: E402
import g_common as GC  # noqa: E402
import gencard  # noqa: E402
import run_g as R  # noqa: E402
import score_g as SG  # noqa: E402

cc = A.cc
I = A.S.items_x
STORE_OK = GC.POOL.is_file() and GC.GEN_NAMES.is_file() and GC.GEN_LAYER.is_file() and GC.R4_LAYER.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({GC.OUT_ROOT})")
QUIET = {"log": lambda *_a: None}
NC = 131072
OLD_LINE = "2026-10-21 K0：記下工具的雜湊值"                # in the log when the K0 record is made
NEW_LINE = "2026-10-22 修正：換回釘定的版本後續跑"           # added after it
STORE_INPUTS = (GC.POOL, GC.GEN_NAMES, GC.OUT_ROOT / "power")    # in the store before F1: read as they are


# ---------------------------------------------------------------- the store's later files never reach a test (m12)
@pytest.fixture(autouse=True)
def later_store_files_in_tmp(tmp_path, monkeypatch):
    """Every g_common path under OUT_ROOT but STORE_INPUTS, and each module attribute of this folder bound to one,
    points into tmp (review m12): order.json, f2.json, void.json, ho/freeze.json, run/ ... of the real line never
    change what a test reads, and writable() refuses the real OUT_ROOT (OUT_ROOT is the tmp one). A function default
    bound at definition time keeps the store path (the tests pass those paths; a write there is refused)."""
    fake, moved, real = tmp_path / "out_root", {}, GC.OUT_ROOT
    for name, v in list(vars(GC).items()):
        if isinstance(v, Path) and (v == real or real in v.parents) and \
                not any(v == k or k in v.parents for k in STORE_INPUTS):
            moved.setdefault(id(v), (v, fake / v.relative_to(real)))
            monkeypatch.setattr(GC, name, moved[id(v)][1])
    for m in [m for m in list(sys.modules.values()) if H in Path(getattr(m, "__file__", None) or "/").parents]:
        for a, x in list(vars(m).items()):
            if m is not GC and id(x) in moved and moved[id(x)][0] is x:
                monkeypatch.setattr(m, a, moved[id(x)][1])
    return fake

# ---------------------------------------------------------------- a synthetic layer, pool and questions (made up)
# (id, name, begetting age, remaining years, stated lifespan); G05.06 is the engine's taken row
CH5 = (("G05.00", "歐文", 100, 700, 800), ("G05.01", "派克", 90, 800, 890), ("G05.02", "柯林", 80, 700, 780),
       ("G05.03", "達倫", 70, 750, 820), ("G05.04", "艾德", 60, 700, 760), ("G05.05", "費滋", 150, 600, 750),
       ("G05.06", "葛雷", 60, 300, 360), ("G05.07", "漢斯", 400, None, 900))
CH11 = (("G11.00", "伊凡", 95, 500, None), ("G11.01", "傑克", 35, 400, None), ("G11.02", "凱文", 30, 400, None),
        ("G11.03", "雷恩", 32, 400, None), ("G11.04", "莫頓", 30, 200, None), ("G11.05", "奈特", 70, None, 200))
NAME = {r[0]: r[1] for r in CH5 + CH11}
T = {"F1": "依創世記，{x}幾歲時，{y}出生？", "F5": "依創世記，{x}去世那年，{y}幾歲？"}
NO_CUE = "依創世記，{x}與{y}是什麼關係？"


def gen_doc() -> dict:
    nodes, edges, derived = [], [], {}
    for ch, rows in ((5, CH5), (11, CH11)):
        for order, (gid, name, b, r, t) in enumerate(rows):
            f = {"beget": [b, f"syn.{ch}.{3 * order}"]}
            if r is not None:
                f["remain"] = [r, f"syn.{ch}.{3 * order + 1}"]
            if t is not None:
                f["total"] = [t, f"syn.{ch}.{3 * order + 2}"]
            else:
                derived[gid] = b + r
            nxt = rows[order + 1][1] if order + 1 < len(rows) else None
            nodes.append({"id": gid, "name": name, "chapter": ch, "order": order, "sons": [nxt] if nxt else [],
                          "fields": f, "flood_offset": [2, "syn.11.0"] if gid == "G11.00" else None})
        edges += [[a[0], b[0], "son", f"syn.{ch}.{3 * i}"] for i, (a, b) in enumerate(zip(rows, rows[1:]))]
    nodes[len(CH5) - 1]["sons"] = ["伊凡", "路易", "馬丁"]
    return {"schema": "arith.gen_layer.v1", "text_digest": "syn", "nodes": nodes, "edges": edges,
            "conflict_edges": [["G05.07", "G11.00", "son", "syn.5.30"]], "flood": {"noah_age": [450, "syn.7.6"]},
            "derived": {"total": derived}, "checks": {}}


def names_doc(gen: dict) -> dict:
    chain = [{"id": n["id"], "name": n["name"], "chapter": n["chapter"]}
             for n in sorted(gen["nodes"], key=lambda n: (n["chapter"], n["order"]))]
    return {"schema": "gen_confirm.gen_names.v1", "text_digest": "syn", "gen_layer_sha256": "syn", "chain": chain,
            "cain_line": ["卡恩", "米雅"], "abram_family": ["亞瑟", "莎拉妮"], "extra_persons": ["卡恩", "米雅", "亞瑟", "莎拉妮"],
            "other_books": ["某丁福音"], "lexicon_blockers": ["柯林頓"], "sources": {}}


GEN = gen_doc()
L = gencard.parse(GEN, names_doc(GEN), common_words={})


def syn_pool() -> list[dict]:
    """Every pool-shaped (type, X, Y) of the synthetic chains, in stage-0's pool sort, flags spread over them."""
    out = []
    for ch in (5, 11):
        ids = list(L.chains[ch])
        for i, x in enumerate(ids):
            for j in range(i + 2, len(ids)):
                y, n, t, ty = ids[j], L.age_at_birth(x, ids[j]), L.lifespan[x], L.lifespan[ids[j]]
                if j - i <= 4 and t is not None and n < t:
                    out.append(("F1", ch, x, y, n, ids[i:j + 1]))
                if x not in L.taken and None not in (t, ty) and 0 < t - n < ty:
                    out.append(("F5", ch, x, y, t - n, ids[i:j + 1]))
    out.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    return [dict(sid=f"S{k:02d}", qtype=q, chapter=ch, stratum=f"{q}c{ch}", d=len(p) - 1, x=x, y=y, pair=f"{x}>{y}",
                 persons=list(p), edges=[f"{p[i]}>{p[i + 1]}" for i in range(len(p) - 1)], gold=g,
                 marker_required=k % 7 == 0, homonym=k % 5 == 0, shem_x=k % 11 == 0, dup_gold=k % 9 == 0)
            for k, (q, ch, x, y, g, p) in enumerate(out)]


POOL = syn_pool()
SIDS = [s["sid"] for s in POOL]
ORDER = SIDS[1::2] + SIDS[::2]                                  # a made-up writing order


def syn_item(slot: dict, question: str, gen: dict) -> dict:
    """A made-up base item: one made-up passage, stage-0's arith key on the slot's gold."""
    return {"question": question, "keys": [I.arith_key(slot["gold"], ["A", "Y"], [f"syn.{slot['chapter']}.0"])],
            "distractors": [], "context_from": "syn",
            "sources": [{"book_name": "某書", "chapter_num": slot["chapter"], "title": "假標題", "verse_range": "1-9",
                         "content": f"假經文第{slot['chapter']}章"}]}


def frozen_doc(pool: list[dict] = POOL, skip: tuple[str, ...] = (), override: dict | None = None,
               unopened: tuple[str, ...] = ()) -> dict:
    """A frozen set of every slot but ``skip`` (attrition: failed) and ``unopened`` (the slots after n_target),
    template questions unless ``override``."""
    override, out = override or {}, set(skip) | set(unopened)
    qs = [{"sid": s["sid"], "question": override.get(s["sid"]) or T[s["qtype"]].format(x=NAME[s["x"]], y=NAME[s["y"]])}
          for s in pool if s["sid"] not in out]
    att = {c: [] for c in A.ATTRITION}
    att["failed"], att["unopened"] = list(skip), list(unopened)
    return {"schema": A.FROZEN_SCHEMA, "n_target": len(pool) - len(unopened), "questions": qs, "attrition": att}


def slot(sid: str) -> dict:
    return next(s for s in POOL if s["sid"] == sid)


def pick(qtype: str, k: int = 0) -> str:
    return [s["sid"] for s in POOL if s["qtype"] == qtype][k]


def wrong_pair_question(sid: str) -> str:
    """A template question naming another pair of the slot's chapter (the rule fires on it: a wrong seed)."""
    s = slot(sid)
    other = next(p for p in POOL if p["qtype"] == s["qtype"] and p["chapter"] == s["chapter"] and p["pair"] != s["pair"]
                 and p["x"] == s["x"])
    return T[s["qtype"]].format(x=NAME[other["x"]], y=NAME[other["y"]])


ABST, WRONG = pick("F1", 1), pick("F5", 2)


@pytest.fixture(scope="module")
def built():
    doc = frozen_doc(override={ABST: NO_CUE.format(x=NAME[slot(ABST)["x"]], y=NAME[slot(ABST)["y"]]),
                               WRONG: wrong_pair_question(WRONG)})
    return doc, A.build(doc, POOL, L, GEN, syn_item, order=ORDER)


def src_of(doc: dict) -> SimpleNamespace:
    return SimpleNamespace(frozen=doc, frozen_sha256=GC.sha256_text(json.dumps(doc, sort_keys=True)), pool=POOL,
                           gen=GEN, L=L, item_of=syn_item, order=ORDER)


# ---------------------------------------------------------------- the frozen-question contract
def test_frozen_contract_accepts_a_partition_of_the_pool():
    assert len(POOL) >= 30 and len({s["stratum"] for s in POOL}) == 4
    assert A.frozen_problems(frozen_doc(skip=("S03",)), POOL, ORDER) == []
    assert [f["sid"] for f in A.load_frozen(frozen_doc(), POOL, ORDER)] == SIDS


def test_frozen_contract_refusals_name_sids_never_text():
    def bad(doc):
        out = A.frozen_problems(doc, POOL, ORDER)
        assert out and not any("依創世記" in p for p in out)
        return out
    doc = frozen_doc()
    assert any("schema" in p for p in bad(dict(doc, schema="other")))
    assert any("ascending" in p for p in bad(dict(doc, questions=doc["questions"][::-1])))
    assert any("ascending" in p for p in bad(dict(doc, questions=doc["questions"] + doc["questions"][-1:])))
    assert any("pool sid" in p for p in bad(dict(doc, questions=doc["questions"] + [{"sid": "S99", "question": "某"}])))
    assert any("no question text" in p for p in bad(dict(doc, questions=[dict(doc["questions"][0], question=" ")]
                                                          + doc["questions"][1:])))
    assert any("qtype" in p for p in bad(dict(doc, questions=[dict(doc["questions"][0], qtype="F9")] + doc["questions"][1:])))
    assert any("partition" in p for p in bad(frozen_doc(skip=("S03",)) | {"attrition": {c: [] for c in A.ATTRITION}}))
    assert any("attrition" in p for p in bad(dict(doc, attrition={"failed": []})))
    assert any("unopened" in p for p in bad(dict(doc, n_target=len(POOL) - 1)))
    assert any("slot count" in p for p in bad(dict(doc, n_target=True)))
    assert any("slot count" in p for p in bad(dict(doc, n_target=len(POOL) + 1)))           # RUN-3 A17
    with pytest.raises(SystemExit, match="contract"):
        A.load_frozen(dict(doc, schema="other"), POOL, ORDER)


def test_frozen_contract_checks_the_writing_order():
    """§1.2, §2.3 (RUN-8): unopened = the slots after n_target in order.json; every other slot before it."""
    assert A.frozen_problems(frozen_doc(skip=(ORDER[0],), unopened=tuple(ORDER[-3:])), POOL, ORDER) == []
    head = frozen_doc(unopened=tuple(ORDER[:3]))                     # opened slots listed as unopened
    assert any("unopened is not the slots after n_target" in p for p in A.frozen_problems(head, POOL, ORDER))
    late = frozen_doc(skip=(ORDER[-1],), unopened=tuple(ORDER[-4:-1]))      # a failed slot past n_target
    out = A.frozen_problems(late, POOL, ORDER)
    assert any("lies after n_target" in p for p in out) and any("unopened is not" in p for p in out)
    for order in (ORDER[:-1], ORDER + ORDER[:1], ORDER[:-1] + ["S99"]):
        assert any("permutation" in p for p in A.frozen_problems(frozen_doc(), POOL, order))


def test_make_item_keeps_the_base_key_and_swaps_only_the_question():
    fq = A.load_frozen(frozen_doc(), POOL, ORDER)[0]
    it = A.make_item(fq, GEN, syn_item)
    assert it["question"] == fq["question"] and it["keys"][0]["value"] == fq["gold"] and it["id"] == fq["sid"]
    with pytest.raises(ValueError, match="key"):
        A.make_item(fq, GEN, lambda s, q, g: dict(syn_item(s, q, g), keys=[I.arith_key(s["gold"] + 1, ["A", "Y"], [])]))
    with pytest.raises(ValueError, match="frozen question"):
        A.make_item(fq, GEN, lambda s, q, g: dict(syn_item(s, q, g), question="別的"))


# ---------------------------------------------------------------- arms, prompts, rotation
def test_arms_are_the_card_its_rows_and_no_block_under_as_prompt(built):
    _doc, b = built
    sid = pick("F1", 0)
    it = next(i for i in b["items"] if i["id"] == sid)
    card, ctx = gencard.card(it["question"], L), cc.build_context(it["sources"])
    users = {j["arm"]: j["user"] for j in b["jobs"] if j["item"] == sid and j["rep"] == 1}
    assert set(users) == {"G", "T-rows", "B0"} and b["meta"][sid]["reuse"] == {"G-ref": "G"}
    assert users["G"] == cc.build_user(ctx, it["question"], card.g_block)
    assert users["T-rows"] == cc.build_user(ctx, it["question"], card.t_block)
    assert users["B0"] == cc.build_user(ctx, it["question"], None)
    assert all(j["system"] == cc.SYSTEM_PROMPT for j in b["jobs"])
    m = b["meta"][sid]
    assert m["prompt_sha256"]["G-ref"] == m["prompt_sha256"]["G"] and m["covered"] and not m["wrong"]
    assert A.card_problems(b["items"], b["cards"], b["meta"]) == {} and A.job_problems(b["items"], b["jobs"], b["meta"]) == []


def test_jobs_run_rep_then_item_then_the_rotated_arms(built):
    _doc, b = built
    items = [it["id"] for it in b["items"]]
    for rep in range(1, A.REPS + 1):
        js = [j for j in b["jobs"] if j["rep"] == rep]
        assert [j["item"] for j in js] == sorted((j["item"] for j in js), key=items.index)
        for i, sid in enumerate(items):
            rot = A.ARMS[i % 4:] + A.ARMS[:i % 4]
            assert [j["arm"] for j in js if j["item"] == sid] == [a for a in rot if a in b["meta"][sid]["jobs"]]
    assert {j["job_id"].split("|")[0] for j in b["jobs"]} == {"GC"} and len(b["jobs"]) == A.n_expected(b["meta"])
    assert b["jobs"][0]["job_id"] == f"GC|{items[0]}|G|1"


def test_an_abstention_has_no_g_or_t_rows_job_and_their_prompts_would_be_b0s(built):
    _doc, b = built
    m = b["meta"][ABST]
    assert not m["rule"]["fired"] and m["rule"]["reason"] and not m["carded"] and not m["covered"]
    assert m["jobs"] == ["B0", "G-ref"] and m["reuse"] == {"G": "B0", "T-rows": "B0"} and m["gref_job"]
    assert m["prompt_sha256"]["G"] == m["prompt_sha256"]["T-rows"] == m["prompt_sha256"]["B0"]
    assert not any(j["item"] == ABST and j["arm"] in ("G", "T-rows") for j in b["jobs"])


def test_g_ref_runs_only_when_the_rule_seeds_are_not_the_gold_pair(built):
    _doc, b = built
    m = b["meta"][WRONG]
    assert m["rule"]["fired"] and not m["seeds_ok"] and m["rule"]["seeds"] != m["gold_seeds"] and m["gref_job"]
    assert m["wrong"] and not m["covered"] and m["gref_covered"] and m["reuse"] == {}
    gref = next(j for j in b["jobs"] if j["item"] == WRONG and j["arm"] == "G-ref")
    it = next(i for i in b["items"] if i["id"] == WRONG)
    gold_card = gencard.card_for_seeds((it["x"], it["y"]), L)
    assert gref["user"] == cc.build_user(cc.build_context(it["sources"]), it["question"], gold_card.g_block)
    ok = [s for s, mm in b["meta"].items() if mm["seeds_ok"]]
    assert ok and not any(j["arm"] == "G-ref" and j["item"] in ok for j in b["jobs"])
    assert not any(b["meta"][s]["gref_job"] for s in ok)                                   # RUN-3 X8
    meas = A.rule_measures(b["meta"])
    n = len(b["items"])
    assert (meas["a_meas"]["k"], meas["w_meas"]["k"], meas["R_trig"]["k"], meas["R_seed"]["k"]) == (n - 2, 1, n - 1, n - 2)
    assert meas["abstained"] == [ABST] and meas["wrong"] == [WRONG] and sum(meas["abstentions"].values()) == 1


def test_card_and_job_problems_catch_each_broken_rule(built):
    """§4.1, F3 (RUN-3 A8, A9, A12): blocks ≤ 900, reuse byte-equal, T-rows = G's rows, K0-card, one system prompt."""
    _doc, b = built
    sid = pick("F5", 0)
    meta = {**b["meta"], sid: {**b["meta"][sid], "block_chars": {**b["meta"][sid]["block_chars"], "G": 901}}}
    assert "G block 901 chars > 900" in A.card_problems(b["items"], b["cards"], meta)[sid]
    sha = {**b["meta"][ABST]["prompt_sha256"], "G": "0" * 64}
    meta = {**b["meta"], ABST: {**b["meta"][ABST], "prompt_sha256": sha}}
    assert any("would not equal" in p for p in A.card_problems(b["items"], b["cards"], meta)[ABST])
    carded = next(s for s, cd in b["cards"].items() if cd["g"] and cd["g"]["lines"])
    cd = b["cards"][carded]
    cards = {**b["cards"], carded: {**cd, "g": {**cd["g"], "t_block": cd["g"]["t_block"] + "多"}}}
    assert A.card_problems(b["items"], cards, b["meta"]) == {carded: ["T-rows is not G's kept rows"]}
    cards = {**b["cards"], carded: {**cd, "gref": {**cd["gref"], "covers": False}}}
    assert A.card_problems(b["items"], cards, b["meta"]) == {carded: ["the gold-seed card does not cover the gold"]}
    assert A.job_problems(b["items"], b["jobs"][:-1], b["meta"])
    jobs = [dict(b["jobs"][0], system="別的系統提示")] + b["jobs"][1:]
    assert A.job_problems(b["items"], jobs, b["meta"]) == ["a job with another system prompt"]


def test_card_and_trigger_must_agree(built, monkeypatch):
    """RUN-3 A18: a card exactly when the rule fires, on the trigger's seeds."""
    _doc, b = built
    it = next(i for i in b["items"] if b["meta"][i["id"]]["carded"])
    monkeypatch.setattr(A.gencard, "card", lambda q, L: None)
    with pytest.raises(ValueError, match="disagree"):
        A.item_cards(it, L)


# ---------------------------------------------------------------- scoring
def rec(job: dict, answer: str, **kw) -> dict:
    return {"type": "answer", "job_id": job["job_id"], "content": f"推理略。\n答案：{answer}", "prompt_eval_count": 10,
            "eval_count": 5, "done_reason": "stop", "elapsed_s": 1.0, **kw}


def write_gen(d: Path, recs: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / SG.GEN).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")


def test_scoring_reuses_b0_for_an_abstention_and_g_for_g_ref(built, tmp_path):
    _doc, b = built
    gold = {it["id"]: it["gold"] for it in b["items"]}
    recs = [rec(j, f"{gold[j['item']] + (j['rep'] == 2 and j['arm'] == 'B0')}歲") for j in b["jobs"]]
    write_gen(tmp_path, recs)
    sc = SG.score_all(tmp_path, b["items"], b["meta"], b["jobs"], num_ctx=NC)
    assert sc["missing_jobs"] == [] and sc["n_records"] == len(b["jobs"])
    row = sc["items"][ABST]
    for r in range(1, 4):
        g, t, b0 = (row["reps"][f"{a}|{r}"] for a in ("G", "T-rows", "B0"))
        assert g["substituted_from"] == t["substituted_from"] == "B0" and g["score"] == t["score"] == b0["score"]
        assert g["job_id"] == b0["job_id"]
    assert row["mean"]["G"] == row["mean"]["T-rows"] == row["mean"]["B0"] == {"frac": "2/3", "float": 2 / 3}
    ok = next(s for s, m in b["meta"].items() if m["seeds_ok"])
    assert all(sc["items"][ok]["reps"][f"G-ref|{r}"]["substituted_from"] == "G" for r in range(1, 4))
    assert sc["items"][ok]["mean"]["G-ref"] == sc["items"][ok]["mean"]["G"]
    assert sc["counts"]["G"]["calls"] == sum(j["arm"] == "G" for j in b["jobs"])        # reused records are no calls
    assert sc["truncation_problems"] == [] and sc["items"][ok]["unit"] == ok


def test_truncation_no_answer_missing_reps_and_slow_calls(built, tmp_path):
    _doc, b = built
    gold = {it["id"]: it["gold"] for it in b["items"]}
    g_jobs = [j for j in b["jobs"] if j["arm"] == "G"]
    trunc_ids = {g_jobs[1]["job_id"], g_jobs[2]["job_id"]}
    recs = [rec(j, f"{gold[j['item']]}歲", **({"done_reason": "length"} if j["job_id"] in trunc_ids else {}),
                **({"elapsed_s": 121.0} if j is g_jobs[3] else {})) for j in b["jobs"][1:]]
    recs.append({**rec(b["jobs"][0], ""), "content": "沒有答案行"})
    write_gen(tmp_path, recs)
    sc = SG.score_all(tmp_path, b["items"], b["meta"], b["jobs"], num_ctx=NC)
    assert sc["truncation"]["G"] == 2 and "G truncated 2 times" in sc["truncation_problems"]
    assert "G and T-rows truncations differ by 2" in sc["truncation_problems"] and sc["counts"]["G"]["over_120s"] == 1
    for jid in trunc_ids:                                  # §6 (RUN-2 S8): a truncated call is 0, its gold line unread
        _exp, sid, arm, r = jid.split("|")
        v = sc["items"][sid]["reps"][f"{arm}|{r}"]
        assert v["truncated"] and v["score"] == 0 and v["score_any"] == 0 and v["answer_line"] is None
    first = b["jobs"][0]
    r0 = sc["items"][first["item"]]["reps"][f"{first['arm']}|{first['rep']}"]
    assert r0["format_fail"] and r0["score"] == 0
    write_gen(tmp_path, recs[1:])
    sc = SG.score_all(tmp_path, b["items"], b["meta"], b["jobs"], num_ctx=NC)
    assert sc["missing_jobs"] == [b["jobs"][1]["job_id"]]
    assert sc["items"][b["jobs"][1]["item"]]["mean"][b["jobs"][1]["arm"]] is None


def test_a_job_of_no_item_arm_is_refused(built, tmp_path):
    """RUN-3 S9: the job list is exactly the build's item arms."""
    _doc, b = built
    ok = next(s for s, m in b["meta"].items() if m["seeds_ok"])
    stray = dict(b["jobs"][0], job_id=A.job_id(ok, "G-ref", 1), item=ok, arm="G-ref")
    write_gen(tmp_path, [])
    with pytest.raises(ValueError, match="no item arm"):
        SG.score_all(tmp_path, b["items"], b["meta"], b["jobs"] + [stray], num_ctx=NC)


def test_truncated_is_score_as_truncated():
    from score_a import truncated
    for r in ({"done_reason": "length"}, {"done_reason": "stop", "prompt_eval_count": 131000, "eval_count": 72},
              {"done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}, {}, {"prompt_eval_count": None}):
        for nc in (NC, None, 0):
            assert SG.truncated(r, nc) == truncated(r, nc)
    assert SG.truncation_problems({"G": 1, "T-rows": 0, "B0": 1, "G-ref": 2}) == ["G-ref truncated 2 times"]


# ---------------------------------------------------------------- Ollama checks, execute, canary
class Api:
    """A fake Ollama: /api/ps, /api/tags, /api/version."""

    def __init__(self, digest=GC.EXPECTED_DIGEST, version=GC.OLLAMA_VERSION, loaded=True, others=(), down=False):
        self.digest, self.version, self.loaded, self.others, self.down = digest, version, loaded, list(others), down

    def __call__(self, path: str) -> dict:
        if self.down:
            raise urllib.error.URLError("refused")
        if path == "/api/version":
            return {"version": self.version} if self.version else {}
        mine = [{"name": GC.MODEL, "model": GC.MODEL, "digest": self.digest}]
        if path == "/api/ps":
            return {"models": (mine if self.loaded else []) + [{"name": o, "digest": "f" * 64} for o in self.others]}
        return {"models": mine}


class Chat:
    def __init__(self, fail_users=(), **over):
        self.calls, self.fail, self.over = 0, set(fail_users), over

    def __call__(self, system, user, options=None):
        self.calls += 1
        if user in self.fail:
            raise urllib.error.URLError("connection reset")
        return {"content": "推理略。\n答案：1歲", "thinking_chars": 0, "prompt_eval_count": 10, "eval_count": 5,
                "done_reason": "stop", "elapsed_s": 0.0, **self.over}


def fake_jobs(n: int) -> list[dict]:
    return [{"job_id": f"GC|S{i:02d}|B0|1", "exp": "GC", "item": f"S{i:02d}", "family": "GEN", "arm": "B0", "rep": 1,
             "kind": "gen", "system": "系統甲", "user": f"假問題{i}"} for i in range(n)]


@pytest.fixture
def root(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setattr(R, "RUN_ROOT", run)
    monkeypatch.setattr(R, "inputs_sha", lambda: {"items.json": "x"})
    return run


def test_before_problems_and_run_state_pin_the_ollama_version():
    assert R.before_problems(R.ollama_check(Api(), "before")) == []
    assert any("0.32.5" in p for p in R.before_problems(R.ollama_check(Api(version="0.1.0"), "before")))
    assert any("digest" in p for p in R.before_problems(R.ollama_check(Api(digest="0" * 64), "before")))
    assert any("not ours alone" in p for p in R.before_problems(R.ollama_check(Api(others=["x:1b"]), "before")))
    b = {"when": "before", "t": "t0", "digest": GC.EXPECTED_DIGEST, "version": GC.OLLAMA_VERSION}
    a = dict(b, when="after", t="t1")
    assert R.run_state({"checks": [b, a]}) == ("ok", [])
    assert R.run_state({"checks": [b, dict(a, version="0.33.0")]})[0] == "void"
    assert R.run_state({"checks": [b, dict(a, digest=None)]})[0] == "unknown"
    assert R.run_state({"checks": [b]})[0] == "unfinished"


def test_execute_runs_a_limited_canary_session_then_the_rest(root):
    d, js = root / "formal", fake_jobs(35)
    chat = Chat()
    meta = R.execute(d, js, "formal", chat=chat, get=Api(), limit=R.CANARY_CALLS, **QUIET)
    assert chat.calls == 30 and len(meta["missing"]) == 5 and meta["n_jobs"] == 35
    st = R.canary_status(d, js)
    assert st["pass"] and st["n_canary"] == 30
    again = Chat()
    R.execute(d, js, "formal", chat=again, get=Api(), limit=R.CANARY_CALLS, **QUIET)
    assert again.calls == 0                                           # the canary's jobs are done: no session
    meta = R.execute(d, js, "formal", chat=again, get=Api(), **QUIET)
    assert again.calls == 5 and meta["missing"] == [] and meta["state"] == "ok" and len(meta["checks"]) == 4
    assert meta["options"] == dict(R.X.OPTIONS) and meta["ollama_version"] == GC.OLLAMA_VERSION


def test_a_canary_with_an_error_line_fails(root):
    d, js = root / "formal", fake_jobs(31)
    R.execute(d, js, "formal", chat=Chat(fail_users={"假問題3"}), get=Api(), limit=R.CANARY_CALLS, **QUIET)
    st = R.canary_status(d, js)
    assert not st["pass"] and st["errors"] == 3 and st["missing"] == ["GC|S03|B0|1"]


def test_execute_refuses_another_kind_jobs_or_version_and_voids_on_a_changed_version(root):
    d, js = root / "formal", fake_jobs(3)
    R.execute(d, js, "formal", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="not smoke"):
        R.execute(d, js, "smoke", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="differ"):
        R.execute(d, fake_jobs(4), "formal", chat=Chat(), get=Api(), **QUIET)
    with pytest.raises(SystemExit, match="refused before any call"):
        R.execute(root / "smoke", js, "smoke", chat=Chat(), get=Api(version="0.1.0"), **QUIET)
    with pytest.raises(SystemExit, match="not the smoke's"):
        R.refuse_before_call(d, R.run_meta(d), R.ollama_check(Api(), "before"), "0.1.0")
    with pytest.raises(SystemExit, match="writes only under"):
        R.execute(root.parent / "elsewhere", js, "dry_run", chat=Chat(), get=Api(), **QUIET)
    api, inner = Api(), Chat()

    def going_down(system, user, options=None):                    # the after-check of this session gets no answer
        api.down = True
        return inner(system, user, options)
    d2 = root / "dry_run"
    meta = R.execute(d2, js, "dry_run", chat=going_down, get=api, **QUIET)
    assert meta["state"] == "unknown"
    with pytest.raises(SystemExit, match="the run is void"):        # its stand-in after-check has another version
        R.execute(d2, js, "dry_run", chat=Chat(), get=Api(version="0.33.0"), **QUIET)
    with pytest.raises(SystemExit, match="not resumed"):
        R.execute(d2, js, "dry_run", chat=Chat(), get=Api(), **QUIET)


def test_execute_resumes_a_changed_harness_only_with_infra_fix(root, monkeypatch):
    """§4.5 (RUN-3 X11): a formal run's harness changes only under --infra-fix, kept in harness_history."""
    hp = {"v": {"files_sha256": {"a.py": "1"}, "sha256": "h1"}}
    monkeypatch.setattr(F1, "harness_pins", lambda *a, **k: hp["v"])
    d, js = root / "formal", fake_jobs(4)
    R.execute(d, js, "formal", chat=Chat(fail_users={"假問題3"}), get=Api(), **QUIET)
    hp["v"] = {"files_sha256": {"a.py": "2"}, "sha256": "h2"}
    with pytest.raises(SystemExit, match="harness differs"):
        R.execute(d, js, "formal", chat=Chat(), get=Api(), **QUIET)
    meta = R.execute(d, js, "formal", chat=Chat(), get=Api(), infra_fix=NEW_LINE, **QUIET)
    assert meta["missing"] == [] and meta["harness"]["sha256"] == "h2"
    assert [(h["from"], h["to"], h["files"], h["note"]) for h in meta["harness_history"]] == [("h1", "h2", ["a.py"], NEW_LINE)]
    with pytest.raises(SystemExit, match="resume without it"):
        R.execute(d, js, "formal", chat=Chat(), get=Api(), infra_fix=NEW_LINE, **QUIET)
    with pytest.raises(SystemExit, match="formal run only"):
        R.execute(root / "smoke", js, "smoke", chat=Chat(), get=Api(), infra_fix=NEW_LINE, **QUIET)
    d2 = root / "dry_run"
    R.execute(d2, js, "dry_run", chat=Chat(fail_users={"假問題3"}), get=Api(), **QUIET)
    hp["v"] = {"files_sha256": {"a.py": "3"}, "sha256": "h3"}
    assert R.execute(d2, js, "dry_run", chat=Chat(), get=Api(), **QUIET)["missing"] == []      # a dry run: as is


# ---------------------------------------------------------------- anchors, the harness and its record
def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def logged(tmp_path, monkeypatch):
    """A tmp prereg.md and K0 harness record (fake pins h1): OLD_LINE was in the log at K0, NEW_LINE came after."""
    pre, rec = tmp_path / "prereg.md", tmp_path / "harness_record.json"
    pre.write_text(f"# 規格\n\n## 執行紀錄\n\n### {OLD_LINE}\n", encoding="utf-8")
    hp = {"v": {"files_sha256": {"a.py": "1"}, "sha256": "h1"}}
    monkeypatch.setattr(F1, "PREREG", pre)
    monkeypatch.setattr(F1, "HARNESS_RECORD", rec)
    monkeypatch.setattr(F1, "harness_pins", lambda *a, **k: hp["v"])
    F1.record_k0(git=lambda: [], tests=lambda: [])
    with pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {NEW_LINE}\n")
    return SimpleNamespace(pre=pre, rec=rec, hp=hp)


def test_harness_files_cover_gencard_the_tests_and_prereg_above_its_log(tmp_path):
    h, t = tmp_path / "h", tmp_path / "t"
    (h / "gencard").mkdir(parents=True)
    t.mkdir()
    (h / "prereg.md").write_text("# 規格\n內文\n\n## 執行紀錄\n", encoding="utf-8")
    (h / "a.py").write_text("x = 1\n", encoding="utf-8")
    (h / "gencard" / "b.py").write_text("y = 1\n", encoding="utf-8")
    (h / "notes.md").write_text("不釘\n", encoding="utf-8")
    (t / "test_gen_confirm_a.py").write_text("z = 1\n", encoding="utf-8")
    (t / "test_other.py").write_text("w = 1\n", encoding="utf-8")
    pins = F1.harness_files_sha256(h, t)
    assert set(pins) == {"a.py", "gencard/b.py", "prereg.md", "tests/test_gen_confirm_a.py"}
    assert pins["prereg.md"] == GC.sha256_text("# 規格\n內文\n")
    (h / "prereg.md").write_text("# 規格\n內文\n\n## 執行紀錄\n\n- 修了逾時。\n", encoding="utf-8")
    assert F1.harness_files_sha256(h, t) == pins
    real = F1.harness_files_sha256()
    assert {"run_g.py", "arms_g.py", "gencard/card.py", "prereg.md", "tests/test_gen_confirm_run.py",
            "tests/test_gen_confirm_core.py"} <= set(real)


def test_git_problems(tmp_path):
    repo = tmp_path / "repo"
    h, t = repo / "h", repo / "t"
    (h / "gencard").mkdir(parents=True)
    t.mkdir()
    _git(repo, "init", "-q")
    pre = h / "prereg.md"
    pre.write_text("正式版\n", encoding="utf-8")
    (h / "gencard" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (t / "test_gen_confirm_a.py").write_text("x = 1\n", encoding="utf-8")
    assert "prereg.md not committed" in F1.git_problems(pre, h, t)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "t")
    assert F1.git_problems(pre, h, t) == []
    (h / "gencard" / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert F1.git_problems(pre, h, t) == ["harness files changed or untracked since the last commit"]
    _git(repo, "checkout", "-q", "--", "h/gencard/a.py")
    (t / "test_gen_confirm_b.py").write_text("y = 1\n", encoding="utf-8")
    assert F1.git_problems(pre, h, t) == ["test files changed or untracked since the last commit"]


def test_an_anchor_is_one_new_whole_line_of_the_log(tmp_path):
    """RUN-4: never a substring, a short string, a repeated line, a used anchor or a line older than the step."""
    pre = tmp_path / "prereg.md"
    pre.write_text(f"# 規格：不在紀錄裡的一行文字\n\n## 執行紀錄\n\n### {NEW_LINE}\n\n- 第二行：重跑正式跑之前先檢查\n"
                   "- 第二行：重跑正式跑之前先檢查\n", encoding="utf-8")
    assert F1.log_lines(pre)[0] == NEW_LINE and F1.anchor_problems(NEW_LINE, pre) == []
    assert F1.anchor_problems(f"  {NEW_LINE} ", pre) == []
    assert F1.anchor_problems("修正逾時", pre) == ["the anchor is shorter than 12 characters",
                                               "the anchor is not a whole line of prereg.md's 執行紀錄"]
    assert F1.anchor_problems(NEW_LINE[:-2], pre) == ["the anchor is not a whole line of prereg.md's 執行紀錄"]
    assert F1.anchor_problems("規格：不在紀錄裡的一行文字", pre) == ["the anchor is not a whole line of prereg.md's 執行紀錄"]
    assert F1.anchor_problems("第二行：重跑正式跑之前先檢查", pre) == ["the anchor is on more than one line of the log"]
    assert F1.anchor_problems(None, pre)[0].startswith("the anchor is shorter")
    assert F1.anchor_problems(NEW_LINE, pre, used=[NEW_LINE]) == ["the anchor was used by an earlier record"]
    assert F1.anchor_problems(NEW_LINE, pre, seen=F1.lines_sha256([NEW_LINE])) == [
        "the anchor line was in the log before this step"]


def test_harness_record_k0_changes_and_problems(logged):
    pins, rec, pre = logged.hp, logged.rec, logged.pre
    get = lambda: pins["v"]  # noqa: E731
    with pytest.raises(SystemExit, match="made once"):
        F1.record_k0(git=lambda: [], tests=lambda: [])
    with pytest.raises(SystemExit, match="suite fails"):
        F1.record_k0(record=rec.parent / "k0b.json", git=lambda: [], tests=lambda: ["the test_gen_confirm_* suite fails (x)"])
    assert not (rec.parent / "k0b.json").exists()
    k0 = GC.read_json(rec)["k0"]
    assert k0["sha256"] == "h1" and k0["log_lines_sha256"] == F1.lines_sha256([OLD_LINE])
    assert F1.harness_problems() == []
    pins["v"] = {"files_sha256": {"a.py": "2"}, "sha256": "h2"}
    assert F1.harness_problems() == ["the harness differs from its record (K0 or the last logged change)"]
    with pytest.raises(SystemExit, match="before this step"):                    # RUN-4: a line older than K0
        F1.record_change(OLD_LINE, git=lambda: [], tests=lambda: [])
    with pytest.raises(SystemExit, match="whole line"):
        F1.record_change("2026", git=lambda: [], tests=lambda: [])
    with pytest.raises(SystemExit, match="suite fails"):
        F1.record_change(NEW_LINE, git=lambda: [], tests=lambda: ["the test_gen_confirm_* suite fails (1 failed)"])
    with pytest.raises(SystemExit, match="harness files changed"):
        F1.record_change(NEW_LINE, git=lambda: ["harness files changed"], tests=lambda: [])
    extra = "2026-10-22 同一天的另一行紀錄說明"
    with open(pre, "a", encoding="utf-8") as f:
        f.write(f"- {extra}\n")
    doc = F1.record_change(NEW_LINE, git=lambda: [], tests=lambda: [])
    ch = doc["changes"][0]
    assert ch["files"] == ["a.py"] and doc["current"]["sha256"] == "h2" and ch["note"] == NEW_LINE
    assert ch["log_lines_sha256"] == F1.lines_sha256([OLD_LINE, NEW_LINE, extra]) and F1.harness_problems(pins=get) == []
    pins["v"] = {"files_sha256": {"a.py": "3"}, "sha256": "h3"}
    with pytest.raises(SystemExit, match="used by an earlier record|before this step"):     # one line, one change
        F1.record_change(NEW_LINE, git=lambda: [], tests=lambda: [])
    with pytest.raises(SystemExit, match="before this step"):            # in the log at the last change already
        F1.record_change(extra, git=lambda: [], tests=lambda: [])
    pins["v"] = {"files_sha256": {"a.py": "2"}, "sha256": "h2"}
    with open(pre, "a", encoding="utf-8") as f:
        f.write("\n### 2026-10-24 第二次修正：連線逾時\n")
    with pytest.raises(SystemExit, match="nothing to record"):
        F1.record_change("2026-10-24 第二次修正：連線逾時", git=lambda: [], tests=lambda: [])
    pre.write_text(f"# 規格\n\n## 執行紀錄\n\n- {NEW_LINE}（後來改寫的一行）\n", encoding="utf-8")   # only inside a line
    assert F1.harness_problems() == ["harness change h2: its anchor is not a line of the log"]
    pre.write_text("# 規格\n\n## 執行紀錄\n", encoding="utf-8")                  # the anchor left the log
    assert F1.harness_problems() == ["harness change h2: its anchor is not a line of the log"]
    assert F1.harness_problems(record=rec.parent / "none.json")


def test_infra_fix_resumes_only_under_the_last_recorded_change(logged, root):
    """RUN-4: run --infra-fix A needs harness-change --anchor A first, a formal run, A unused by its sessions."""
    assert R.infra_fix_problems(NEW_LINE) == [
        "--infra-fix: the anchor is not the harness record's last change (harness-change --anchor first)",
        "--infra-fix resumes a formal run and there is none"]
    js = fake_jobs(2)
    R.execute(root / "formal", js, "formal", chat=Chat(fail_users={"假問題1"}), get=Api(), **QUIET)
    logged.hp["v"] = {"files_sha256": {"a.py": "2"}, "sha256": "h2"}
    F1.record_change(NEW_LINE, git=lambda: [], tests=lambda: [])
    assert R.infra_fix_problems(NEW_LINE) == []
    assert R.infra_fix_problems(OLD_LINE) == [
        "--infra-fix: the anchor is not the harness record's last change (harness-change --anchor first)"]
    R.execute(root / "formal", js, "formal", chat=Chat(), get=Api(), infra_fix=NEW_LINE, **QUIET)
    assert R.infra_fix_problems(NEW_LINE) == ["--infra-fix: an earlier session of the formal run used this anchor"]
    second = "2026-10-24 第二次修正：連線逾時的上限"
    with logged.pre.open("a", encoding="utf-8") as f:
        f.write(f"\n### {second}\n")
    logged.hp["v"] = {"files_sha256": {"a.py": "3"}, "sha256": "h3"}
    F1.record_change(second, git=lambda: [], tests=lambda: [])
    assert R.infra_fix_problems(second) == []
    assert R.infra_fix_problems(NEW_LINE) == [R.INFRA_NOT_LAST,
                                              "--infra-fix: an earlier session of the formal run used this anchor"]



def test_runners_load_only_the_allowed_modules_of_a_and_none_of_ho_or_qset():
    code = (f"import sys; sys.path.insert(0, {str(H)!r}); import run_g, f1_g, f2_g; from pathlib import Path; "
            "kg = Path(run_g.GC.REPO, 'evaluation/experiments/2026-10-18_kg_cards/A/confirm').resolve(); "
            "f = lambda m: Path(getattr(m, '__file__', None) or '/').resolve(); "
            "print(sorted(n for n, m in list(sys.modules.items()) if kg in f(m).parents)); "
            "print(any('regnal_qset' in str(f(m)) or 'ho_a' in f(m).parts for m in list(sys.modules.values()))); "
            "print('config' in sys.modules, 'utils' in sys.modules)")
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[:3] == ["['analyze_c', 'c_common', 'guards_c']", "False", "False False"]
