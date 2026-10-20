"""Shared helpers of the rule-seed regression tests (test_regnal_seed*.py).

A small two-kingdom regnal layer, template questions written here (no scripture text, and no
question of experiment A's sets: test_store_synthetic_questions_are_not_store_questions holds
every one of them below 0.8 similarity), recorded-seed files in both formats, a fake /api/ps and
/api/tags, a counting chat and a small job list. Nothing here calls Ollama.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RS = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-19_regnal_seed"
if str(RS) not in sys.path:
    sys.path.insert(0, str(RS))

import rs_cards as K  # noqa: E402
import rs_common as C  # noqa: E402
import rs_run as R  # noqa: E402

ISRAEL = ("耶羅波安", "拿答<耶羅波安", "巴沙", "以拉<巴沙", "心利", "暗利")
JUDAH = ("羅波安", "亞比央<羅波安", "亞撒<亞比央", "約沙法<亞撒", "約蘭<約沙法", "亞哈謝<約蘭")
# an alternative accession age for J06: the S4 guard takes its born line off
CONFLICT = ["J06", "亞哈謝", "age", [33, "1ki.11.2", "ki"], [53, "2ch.22.2", "ch"]]


def _node(nid, kd, spec, order):
    nm, _, father = spec.partition("<")
    fields = {"reign": [8 + order % 5, f"1ki.{order}.1", "ki"], "age": [30 + order % 4, f"1ki.{order}.2", "ki"]}
    if father:
        fields["father"] = [father, f"1ki.{order}.3", "succ"]
    return {"id": nid, "kingdom": kd, "name": nm, "aliases": [], "fields": fields, "evidence": [f"1ki.{order}.1"],
            "pending": False, "order": order, "created_by": "t", "has_acc": True}


def layer_doc(conflicts=(CONFLICT,)):
    nodes, edges = [], []
    for kd, specs in (("I", ISRAEL), ("J", JUDAH)):
        for i, spec in enumerate(specs, 1):
            nodes.append(_node(f"{kd}{i:02d}", kd, spec, len(nodes)))
            if i > 1:
                edges.append([f"{kd}{i - 1:02d}", f"{kd}{i:02d}", "son", "1ki.1.1"])
    return {"policy": "occ", "fn_rule": "slot", "nodes": nodes, "edges": edges, "fallback_edges": [], "syncs": [],
            "conflicts": list(conflicts), "log": [], "occ_alias": [], "union_classes": None}


def lexicon_doc():
    from ragcommon.tests.lexicon_doc import document, name
    return document(names=[name("掃羅", "nm:5b0000000001", "Person")])


def _src(i):
    return {"book_name": "列王紀上", "chapter_num": i, "title": "合成", "verse_range": "1-2",
            "content": f"（合成段落 {i}）"}


def item(iid, question, unit=None):
    it = {"id": iid, "question": question, "sources": [_src(1), _src(2)]}
    return {**it, "unit": unit} if unit else it


CONFIRM = [item("Q1", "耶羅波安之後的第四位王是誰？", "U1"),       # rule I01; set a names two kings
           item("Q2", "亞撒之後的第三位王是誰？", "U1"),           # rule J03 = set a's card
           item("Q3", "亞比央的兒子之後的第一位王是誰？", "U2"),   # the rules abstain: gemma fallback
           item("Q4", "亞哈謝出生那年，作王的是哪一位？", "U2")]   # rule J06: the guard takes its born line
DEV = [item("D1", "巴沙之後的第四位王是誰？"),
       item("D2", "暗利是誰？"),                                  # no cue: not taken
       item("D3", "以拉的兒子之後的第二位王是誰？")]              # the rules abstain: gemma fallback
UNTAKEN = item("Q9", "暗利是誰？", "U9")

RAW_A = {"Q1": "以色列｜耶羅波安\n以色列｜拿答", "Q2": "猶大｜亞撒", "Q3": "猶大｜亞比央", "Q4": "猶大｜亞哈謝"}
AUX_B = {"Q1": ["以色列｜耶羅波安"], "Q2": None, "Q3": ["猶大｜亞比央"], "Q4": ["猶大｜亞哈謝"]}
AUX_C = {"Q1": ["以色列｜耶羅波安", "以色列｜拿答"], "Q2": ["猶大｜亞撒"], "Q3": ["猶大｜亞比央"],
         "Q4": ["猶大｜亞哈謝"]}
RAW_DEV = {"D1": "以色列｜巴沙", "D2": "以色列｜暗利", "D3": "以色列｜以拉"}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def gen_seed_rows(texts):
    return [{"type": "answer", "job_id": f"A|{i}|seed|1", "item": i, "content": t, "done_reason": "stop",
             "eval_count": 10, "prompt_eval_count": 10} for i, t in texts.items()]


def response_rows(seeds):
    return [{"item": i, "error": None, "answer": "x",
             "aux_card": None if s is None else {"kind": "regnal", "text": "t", "seeds": s, "kings": [],
                                                  "lines": 1, "evidence": [], "layer_sha256": "0" * 64}}
            for i, s in seeds.items()]


def make_syn(tmp_path):
    """(layer, its info, the cards doc, {set: items}) on the synthetic layer and seed files."""
    layer_p = tmp_path / "regnal_layer.json"
    layer_p.write_text(json.dumps(layer_doc(), ensure_ascii=False), encoding="utf-8")
    lex_p = tmp_path / "routing_lexicon.json"
    lex_p.write_text(json.dumps(lexicon_doc(), ensure_ascii=False), encoding="utf-8")
    lay, info = C.load_layer(layer_p, lex_p)
    seeds = {"a": K.raw_seeds(write_jsonl(tmp_path / "gen_seed_a.jsonl", gen_seed_rows(RAW_A))),
             "b": K.aux_seeds(write_jsonl(tmp_path / "responses_b.jsonl", response_rows(AUX_B))),
             "c": K.aux_seeds(write_jsonl(tmp_path / "responses_c.jsonl", response_rows(AUX_C))),
             "dev": K.raw_seeds(write_jsonl(tmp_path / "gen_seed_dev.jsonl", gen_seed_rows(RAW_DEV)))}
    sets = {"confirm": K.SetSpec(CONFIRM, {k: seeds[k] for k in "abc"}, only_fired=False),
            "dev": K.SetSpec(DEV, {"dev": seeds["dev"]}, only_fired=True)}
    doc = K.build_cards(lay, info, sets)
    return lay, info, doc, {"confirm": CONFIRM, "dev": DEV}


def slot(doc, set_, item_id, arm, rep):
    return K.slot_map(doc)[(set_, item_id, arm, rep)]


# ---------------------------------------------------------------- runner fakes
EXPECTED = C.EXPECTED_DIGEST


def fake_api(ps_digest=EXPECTED, tags_digest=None, ps_has_model=True):
    def get(path):
        if path == "/api/ps":
            return {"models": [{"name": C.MODEL, "model": C.MODEL, "digest": ps_digest}] if ps_has_model else []}
        if path == "/api/tags":
            return {"models": [{"name": C.MODEL, "model": C.MODEL, "digest": tags_digest}] if tags_digest else []}
        raise AssertionError(path)
    return get


def never(*_a, **_k):
    raise AssertionError("Ollama was called")


class CountingChat:
    """The fake chat, counting calls; ``error`` raises on every call, ``fail_after`` stops after n calls,
    ``raise_at`` raises ``error`` on that call only."""

    def __init__(self, fail_after=None, error=None, raise_at=None):
        self.calls, self.fail_after, self.error, self.raise_at = 0, fail_after, error, raise_at

    def __call__(self, system, user, options):
        if self.raise_at is not None:
            self.calls += 1
            if self.calls == self.raise_at:
                raise self.error
            return R.fake_chat(system, user, options)
        if self.error is not None:
            self.calls += 1
            raise self.error
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise KeyboardInterrupt("simulated stop")
        self.calls += 1
        return R.fake_chat(system, user, options)


def small_jobs(n=6):
    return [{"job_id": f"RS|dev|D{i}|rule|1", "exp": "RS", "set": "dev", "item": f"D{i}", "arm": "rule", "rep": 1,
             "kind": "gen", "seed_source": "rule", "card_sha256": None, "system": "s", "user": f"u{i}"}
            for i in range(n)]


def formal_prereg(header: dict) -> str:
    """A prereg text that passes the content gate for a cards doc's header (no draft mark)."""
    rows = [f"{C.LAYER_LINE} `{header['layer_sha256']}` |",
            f"{C.LEXICON_LINE} sha256 `{header['lexicon_sha256']}` |"]
    rows += [f"| {f} | {sha} |" for f, sha in header["backend_files_sha256"].items()]
    return "# 正式版\n\n" + "\n".join(rows) + "\n"
