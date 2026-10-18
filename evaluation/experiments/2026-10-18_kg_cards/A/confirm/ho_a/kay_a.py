"""Kay's one check page (confirm_A.md §7): 20 G-auto layer rows and 10 audited questions, then his decisions.

Drawn once, after every slot is done and no draft waits, before K-U2 / F2:
1. layer: random.Random(20261018).sample(sorted(G-auto nodes on both chains), 20), each rendered with
   engine.row_text plus the text of every field's provenance verse (fields, predecessor edge,
   accession sync). Kay marks each row ok / wrong. ≥2 wrong of 20: K0-1b fails and A stops (§6
   wording, 〈條目〉＝K0-1b, 〈值〉＝wrong/20); 1 wrong: recorded only, no layer or setting changes.
2. questions: random.Random(20261018).sample(sorted(passed ids), 10), with question, chain (fact and
   basis verse text), answer key and accepted spellings. Kay picks accept / revise (note → fix and
   re-audit) / drop (dropped; the slot gets one more attempt if it has attempts left).
Never shown: any arm output, derivation lines, ref_disagree / gen_passage. The page is a local HTML
file in <root>/kay/ (store, never the repo); its button writes the decisions JSON for `apply`.

    kay_a.py draw  [--root R]
    kay_a.py apply [--root R] --decisions D.json   # {"layer": {node: "ok"|"wrong"}, "questions": {id: {"decision", "note"}}}
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import ROOT, C, HoError, meta, now, read_json, sha256_file, write_json  # first: sys.path

import banned_a  # noqa: E402
import items_c  # noqa: E402
import state_a as S  # noqa: E402
import support as SU  # noqa: E402
from engine import row_text  # noqa: E402
from regnal import acc_sync, load_auto, load_ref  # noqa: E402

DECISIONS = ("accept", "revise", "drop")
QUESTION_RULE = "題目的接受／修改／刪除只依經文與題目本身判斷，不看層列對錯。"
FIELD_NAME = {"father": "父", "reign": "在位", "age": "登基年齡", "mother": "母", "mother_desc": "母的描述",
              "death": "死亡", "pred": "繼位", "sync": "登基同步"}


def sample_layer(VA, k: int = C.KAY_LAYER_ROWS, seed: int = C.SEED) -> list[str]:
    return random.Random(seed).sample(sorted(VA.chain["I"] + VA.chain["J"]), k)


def sample_questions(ids: Sequence[str], k: int = C.KAY_QUESTIONS, seed: int = C.SEED) -> list[str]:
    return random.Random(seed).sample(sorted(ids), min(k, len(ids)))


def _verse(key: str | None) -> dict[str, Any]:
    return {"key": key, "ref": C.short_ref(key) if key else None, "text": C.ac.verse_text(key) if key else None}


def layer_rows(VA, layer: Mapping[str, Any], ids: Sequence[str]) -> list[dict[str, Any]]:
    """Each sampled node: engine.row_text and the provenance verse of every field it shows."""
    edges = {(e[0], e[1]): e for e in layer["edges"] + layer["fallback_edges"]}
    out = []
    for x in ids:
        n = VA.nodes[x]
        fields = [{"field": FIELD_NAME.get(f, f), **_verse(v)} for f, v in n["prov"].items()]
        pred = VA.succ(x, -1)
        if pred and (pred, x) in edges:
            e = edges[(pred, x)]
            fields.append({"field": FIELD_NAME["pred"], **_verse(e[3] if len(e) > 3 else None)})
        fields += [{"field": FIELD_NAME["sync"], **_verse(v)} for _o, _y, v in acc_sync(VA, x)]
        out.append({"node": x, "row": row_text(VA, x), "fields": fields})
    return out


def question_rows(state: Mapping[str, Any], ids: Sequence[str], seg_doc: Mapping[str, Any], VR) -> list[dict]:
    rows = S.segment_rows(seg_doc)
    out = []
    for qid in ids:
        rec = S.record(state, qid)
        q = rec["item"]
        res = SU.resolve_question(q)
        key = items_c.build_key(q, res["answer"], VR)
        chain = [{"king": c.get("king"), "role": c.get("role"), "fact": c.get("fact"),
                  "basis": [_verse(k) for k in c.get("basis") or []]} for c in q.get("chain") or []]
        out.append({"id": qid, "segment": rec["segment"], "range": rows[rec["segment"]]["range_label"],
                    "kingdom": q.get("kingdom"), "qtype": q.get("qtype"), "question": q.get("question"),
                    "answer": (q.get("answer") or {}).get("text"), "convention": q.get("convention"),
                    "key": ({"type": "名鍵", "accept": key["accept"]} if key["type"] == "name"
                            else {"type": "數鍵", "value": key["value"], "unit": key["unit"]}),
                    "chain": chain})
    return out


_CSS = """:root{--bg:#fbfaf7;--fg:#1d1b18;--mut:#6b655c;--line:#ddd6ca;--acc:#7a3e12}
@media (prefers-color-scheme:dark){:root{--bg:#1b1a18;--fg:#ece7de;--mut:#a39b8f;--line:#3a3631;--acc:#e0a46f}}
body{background:var(--bg);color:var(--fg);font:16px/1.6 "Noto Serif TC",serif;margin:0 auto;max-width:960px;padding:16px}
h1{font-size:1.6rem}h2{border-bottom:2px solid var(--acc);padding-bottom:4px;margin-top:2.2rem}
.card{border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin:14px 0}
.mut{color:var(--mut);font-size:.9rem}.v{margin:2px 0 2px 1em}.k{font-family:monospace;color:var(--acc)}
label{margin-right:1.2em}textarea{width:100%;min-height:3em;background:var(--bg);color:var(--fg)}
button{font-size:1rem;padding:6px 14px;margin:12px 0}"""


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _verses(vs: Sequence[Mapping[str, Any]], label: str = "") -> str:
    return "".join(f'<div class="v">{_e(label or v.get("field", ""))} <span class="k">{_e(v["ref"])}</span> '
                   f'{_e(v["text"])}</div>' for v in vs)


def page_html(layer: Sequence[Mapping[str, Any]], questions: Sequence[Mapping[str, Any]], note: str) -> str:
    parts = [f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>Kay 抽查</title><style>{_CSS}</style></head><body>",
             f"<h1>Kay 抽查</h1><p class='mut'>{_e(note)}</p><h2>一、層 {len(layer)} 列（逐列標對／錯）</h2>"]
    for r in layer:
        parts.append(f"<div class='card' data-node='{_e(r['node'])}'><div>{_e(r['row'])}</div>{_verses(r['fields'])}"
                     f"<label><input type='radio' name='L_{_e(r['node'])}' value='ok'>對</label>"
                     f"<label><input type='radio' name='L_{_e(r['node'])}' value='wrong'>錯</label></div>")
    parts.append(f"<h2>二、{len(questions)} 題（accept／revise／drop）</h2><p class='mut'>{_e(QUESTION_RULE)}</p>")
    for q in questions:
        chain = "".join(f"<div>{_e(c['role'])}：{_e(c['king'])}　{_e(c['fact'])}</div>{_verses(c['basis'], '依據')}"
                        for c in q["chain"])
        parts.append(f"<div class='card' data-q='{_e(q['id'])}'><div class='mut'>{_e(q['id'])}　{_e(q['kingdom'])}"
                     f"　{_e(q['range'])}　{_e(q['qtype'])}</div><p><b>{_e(q['question'])}</b></p>"
                     f"<div>答案：{_e(q['answer'])}　答案鍵：{_e(json.dumps(q['key'], ensure_ascii=False))}</div>"
                     f"<div class='mut'>算法：{_e(q['convention'])}</div>{chain}"
                     + "".join(f"<label><input type='radio' name='Q_{_e(q['id'])}' value='{d}'>{d}</label>" for d in DECISIONS)
                     + f"<textarea name='N_{_e(q['id'])}' placeholder='意見（revise 必填）'></textarea></div>")
    parts.append("<button id='go'>產生決定 JSON</button><textarea id='out' readonly></textarea><script>"
                 "document.getElementById('go').onclick=function(){var d={layer:{},questions:{}};"
                 "document.querySelectorAll('[data-node]').forEach(function(c){var n=c.dataset.node,"
                 "s=c.querySelector('input:checked');d.layer[n]=s?s.value:null;});"
                 "document.querySelectorAll('[data-q]').forEach(function(c){var q=c.dataset.q,"
                 "s=c.querySelector('input:checked');d.questions[q]={decision:s?s.value:null,"
                 "note:c.querySelector('textarea').value};});"
                 "document.getElementById('out').value=JSON.stringify(d,null,1);};</script></body></html>")
    return "".join(parts)


def draw(root: Path, segments_path: Path = C.SEGMENTS) -> dict[str, Any]:
    state = S.load_state(root)
    seg_doc = S.load_segments(segments_path)
    if state.get("kay"):
        raise HoError("the Kay page was already drawn (§7: once)")
    if not S.is_complete(state, S.slot_plan(seg_doc), "main"):
        raise HoError("questions not finished: every slot done and no draft waiting before the Kay page")
    VA, VR = load_auto(C.LAYER_AUTO), load_ref(C.LAYER_REF)
    passed = [r["id"] for r in S.records(state, (S.PASSED,))]
    nodes, qids = sample_layer(VA), sample_questions(passed)
    note = (f"層：random.Random({C.SEED}).sample(sorted(兩鏈上的 G-auto 節點), {len(nodes)})；題：random.Random({C.SEED})"
            f".sample(sorted(通過稽核的 {len(passed)} 題), {len(qids)})。產生時間 {now()}。")
    kdir = Path(root) / "kay"
    page = kdir / "kay_page.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(page_html(layer_rows(VA, read_json(C.LAYER_AUTO), nodes), question_rows(state, qids, seg_doc, VR),
                              note), encoding="utf-8")
    doc = {"meta": meta("kay_a.py draw"), "seed": C.SEED, "layer_nodes": nodes, "question_ids": qids,
           "candidates": sorted(passed), "page_sha256": sha256_file(page)}
    write_json(kdir / "kay_sample.json", doc)
    S.save_state(root, {**state, "kay": {"layer_nodes": nodes, "question_ids": qids, "drawn_utc": now(),
                                         "resolved": False, "layer": None, "decisions": {}}})
    return doc


def layer_verdict(marks: Mapping[str, str], nodes: Sequence[str]) -> dict[str, Any]:
    if set(marks) != set(nodes) or any(marks[n] not in ("ok", "wrong") for n in nodes):
        raise HoError("layer: every sampled row needs ok or wrong")
    wrong = sorted(n for n in nodes if marks[n] == "wrong")
    stop = len(wrong) >= C.KAY_LAYER_STOP_WRONG
    wording = C.WORDING["stop"].format(rule="K0-1b", value=f"{len(wrong)}/{len(nodes)}", state="未跑") if stop else \
        f"K0-1b：{len(wrong)}/{len(nodes)} 列錯，{'記錄，不修層' if wrong else '全對'}"
    return {"n": len(nodes), "wrong": wrong, "n_wrong": len(wrong), "stop": stop, "wording": wording}


def apply(root: Path, decisions: Mapping[str, Any]) -> dict[str, Any]:
    state = S.load_state(root)
    kay = state.get("kay")
    if not kay:
        raise HoError("no Kay page drawn yet")
    if kay.get("resolved"):
        raise HoError("the Kay decisions were already applied")
    qs = decisions.get("questions") or {}
    if set(qs) != set(kay["question_ids"]):
        raise HoError("questions: decide every sampled question, and only those")
    for qid, d in qs.items():
        if d.get("decision") not in DECISIONS:
            raise HoError(f"{qid}: decision must be one of {DECISIONS}")
        if d["decision"] == "revise" and not str(d.get("note") or "").strip():
            raise HoError(f"{qid}: revise needs a note")
        hits = banned_a.check_prompt_text(str(d.get("note") or ""))
        if d["decision"] == "revise" and hits:            # the note goes into the writer's prompt
            raise HoError(f"{qid}: reword the note without {sorted({h.term for h in hits})}")
    layer = layer_verdict(decisions.get("layer") or {}, kay["layer_nodes"])
    for qid, d in qs.items():
        note = str(d.get("note") or "")
        if d["decision"] == "revise":
            req = {"source": "kay", "issues": [note], "suggested_fix": ""}
            state = S.update_record(state, qid, S.NEEDS_FIX, f"Kay 要求修改：{note}", fix_request=req)
        elif d["decision"] == "drop":
            rec = S.record(state, qid)
            state = S.update_record(state, qid, S.DROPPED, f"Kay 刪除：{note}")
            used = S.attempts_used(state, rec["slot"])
            state = {**state, "slot_limit": {**state["slot_limit"],
                                             rec["slot"]: min(S.slot_limit(state, rec["slot"]), used + 1)}}
    decided = {q: {"decision": d["decision"], "note": d.get("note", ""), "at": now()} for q, d in qs.items()}
    state = {**state, "kay": {**kay, "decisions": decided, "layer": layer, "resolved": True}}
    S.save_state(root, state)
    S.write_passed(root, state)
    write_json(Path(root) / "kay" / "k0_1b.json", {"meta": meta("kay_a.py apply"), **layer})
    return state


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kay 抽查頁（§7）：層 20 列＋10 題")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draw", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=ROOT)
        if name == "apply":
            p.add_argument("--decisions", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        doc = draw(a.root)
        print(f"kay_a.py draw: {len(doc['layer_nodes'])} rows, {len(doc['question_ids'])} questions -> {a.root / 'kay'}")
    else:
        state = apply(a.root, read_json(a.decisions))
        print(f"kay_a.py apply: K0-1b {state['kay']['layer']['wording']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HoError, OSError, ValueError) as err:
        print(f"kay_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
