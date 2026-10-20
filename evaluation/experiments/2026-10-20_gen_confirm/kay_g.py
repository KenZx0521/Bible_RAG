"""Kay's check page of the GEN confirmation set and his decisions (prereg §3.4, §3.6, §3.7, §8.1-9).

    kay_g.py draw                      # once, after every written slot is done and no draft waits (and K-P let it go)
    kay_g.py apply --decisions D.json  # once; then run_ho_g.py kay for the revisions and the kept disputes

Draw: ``random.Random(KAY_SAMPLE_SEED).sample(sorted(passed sids), min(KAY_QUESTIONS, n))`` and every slot in
dispute. The page is a local HTML file in the store (HO_ROOT/kay/kay_page.html, never the repo); its button writes the
decisions JSON. Per sampled question: the slot (English definition, X, Y, the marker), the program gold, the
question, the writer's answer and steps with each cited verse's text read from the text layer, and the auditor's
value and reading. Per dispute: its kind, the reason, what 「留」 means for it (KEEP_MEANS), the draft to keep or drop
(for an audit-vs-mech conflict also the version the auditor read), the audit, the mech findings, and for §3.6 row 3
the CPU comparison of the cited verses with stage-0's independent reader (the attempt's gold trace). Never any arm
output, card, layer row, gencard or trigger output (§3.7, §5.5): nothing here imports or runs gencard.

Decisions {"questions": {sid: {"decision": accept|revise|drop, "note", "gold_wrong"}}, "disputes": {sid:
{"decision": keep|drop, "note", "gold_wrong"}}}, every sampled and every disputed sid and only those:
* accept: nothing changes; revise (a note, memory-marker checked: it goes into the fixer's prompt): one fix of source
  kay under HO_ROOT/kay, mech, a re-audit that must pass outright and the three-way comparison (runs_g); a failure
  is a Kay drop; drop: the slot is abandoned (attrition kay; unlike A, no new attempt).
* dispute keep, by kind: no_change after a mech fix, and an audit-vs-mech conflict → Kay overrules the mech rule:
  the draft (for the conflict: the revision made on the audit's finding) goes on to the value-blind audit and the
  three-way comparison (after a conflict the audit round is spent, so that audit must pass outright); its overruled
  mech errors are recorded (kept_mech: later mech checks of this attempt and freeze_g accept exactly those);
  no_change after an audit fix → Kay overrules the audit finding and keeps the draft the auditor read: it passes only
  when writer, auditor and program gold agree, else the slot closes as failed (why kept_dispute); §3.6 row 3 has no
  keep: gold_wrong true is K-gold, else the slot is deleted (other_quantity). dispute drop: the slot is abandoned
  (attrition kay; row 3: other_quantity).
Stops (kay.json, analyze_g.stop_sentence, state 未凍結): K-Kay when ≥ K_KAY_STOP of the sampled questions are dropped,
a revision that failed (or that the hard cap stopped) counting as a drop; K-gold when Kay marks any program gold wrong
(or the CPU trace did). kay.json is rewritten when the revisions settle (``final``); run_ho_g.py kay starts no
further wave once a stop holds.
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import analyze_g as AG
import banned_g as B
import g_common as GC
import hog_common as H
import prompts_g as P
import runs_g as RU
import state_g as S
from hog_common import HoError, now, read_json, write_json

SCHEMA = "gen_confirm.kay.v1"
K_KAY_STOP = GC.K_KAY_STOP                          # prereg §3.7: 10 題中刪 ≥3 題
Q_DECISIONS, D_DECISIONS = ("accept", "revise", "drop"), ("keep", "drop")
PAGE, SAMPLE = GC.KAY_PAGE, GC.KAY_SAMPLE
QUESTION_RULE = "每題只依經文與題目本身判斷；本頁不含任何臂的輸出、卡片、層列或觸發結果。"
KIND_LABEL = {"no_change": "修題者回 no_change（附理由）", "audit_mech_conflict": "稽核意見與機械檢查衝突",
              "program_differs": "§3.6 第三種情況：出題者＝稽核者≠程式 gold"}
KEEP_MEANS = {"no_change:mech": "留＝推翻機械檢查：這份稿接著做看不到值的稽核與三方比對。",
              "no_change:audit": "留＝推翻稽核意見：出題者、稽核者與程式 gold 三方一致才通過，否則這個題位以失敗收。",
              "audit_mech_conflict:audit": "留＝推翻機械檢查：依稽核意見改過的這一版再做一次看不到值的稽核與三方比對，"
                                           "稽核輪已用，須一次通過，否則以失敗收。",
              "program_differs": "沒有「留」：勾「程式 gold 錯」就是 K-gold（本線停）；否則問了別的量，刪題。"}
Verses = Callable[[str], list[tuple[str, str]]]


def sample(passed: Sequence[str], k: int = GC.KAY_QUESTIONS, seed: int = GC.KAY_SAMPLE_SEED) -> list[str]:
    return random.Random(seed).sample(sorted(passed), min(k, len(passed)))


def keep_key(d: Mapping[str, Any]) -> str:
    return "program_differs" if d["kind"] == "program_differs" else f"{d['kind']}:{d.get('source')}"


def require_applied(state: Mapping[str, Any]) -> dict[str, Any]:
    kay = state.get("kay")
    if not kay or not kay.get("applied"):
        raise HoError("Kay's decisions are not applied: kay_g.py draw, then apply (prereg §3.7)")
    return kay


# ---------------------------------------------------------------- page rows (store only)
def _steps(item: Mapping[str, Any] | None, verses: Verses) -> list[dict[str, Any]]:
    return [{"person": s.get("person"), "fact": s.get("fact"), "verse": s.get("verse"),
             "texts": verses(str(s.get("verse") or ""))} for s in (item or {}).get("steps") or () if isinstance(s, Mapping)]


def _audit(a: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if not a else {k: a.get(k) for k in ("value", "reading", "findings", "checked", "severity")}


def _slot_head(ctx_plan: S.Plan, names: P.Names, sid: str) -> dict[str, Any]:
    sp = ctx_plan.slots[sid]
    spec = P.slot_spec(sp.row, names, sp.qid)
    return {"sid": sid, "qid": sp.qid, "qtype": spec.qtype, "chapter": spec.chapter, "definition": spec.definition,
            "identity": spec.identity, "x": spec.x, "y": spec.y, "marker": spec.marker, "gold": sp.row["gold"]}


def _item_part(item: Mapping[str, Any] | None, verses: Verses) -> dict[str, Any]:
    it = item or {}
    return {"question": it.get("question"), "answer": it.get("answer"), "convention": it.get("convention"),
            "notes": it.get("notes"), "steps": _steps(it, verses)}


def question_rows(state: Mapping[str, Any], plan: S.Plan, names: P.Names, sids: Sequence[str],
                  verses: Verses) -> list[dict[str, Any]]:
    out = []
    for sid in sids:
        att = S.current(S.slot(state, sid))
        out.append({**_slot_head(plan, names, sid), **_item_part(att["item"], verses),
                    "audit": _audit(att["audits"][-1] if att["audits"] else None)})
    return out


def _trace_rows(trace: Mapping[str, Any] | None, verses: Verses) -> dict[str, Any] | None:
    if not trace:
        return None
    units = list(dict.fromkeys(list(trace.get("reader_verses") or ()) + list(trace.get("cited_units") or ())))
    return {**{k: trace.get(k) for k in ("gold", "reader_value", "reader_problems", "agrees", "cited_verses",
                                         "cited_not_read", "read_not_cited", "unresolved_cited", "writer_value",
                                         "auditor_value")},
            "verses": [{"unit": u, "read": u in (trace.get("reader_verses") or ()),
                        "cited": u in (trace.get("cited_units") or ()), "numbers": (trace.get("numbers") or {}).get(u),
                        "texts": verses(u)} for u in units]}


def dispute_rows(state: Mapping[str, Any], plan: S.Plan, names: P.Names, sids: Sequence[str],
                 verses: Verses) -> list[dict[str, Any]]:
    out = []
    for sid in sids:
        d = S.slot(state, sid)["dispute"]
        out.append({**_slot_head(plan, names, sid), "kind": d["kind"], "label": KIND_LABEL[d["kind"]],
                    "source": d.get("source"), "reason": d.get("reason"), "keep_means": KEEP_MEANS[keep_key(d)],
                    "keep_allowed": d["kind"] != "program_differs", "values": d.get("values"),
                    "candidate": _item_part(d.get("candidate"), verses),
                    "audited": _item_part(d["audited"], verses) if d.get("audited") else None,
                    "audit": _audit(d.get("audit")), "mech": d.get("mech") or [],
                    "trace": _trace_rows(d.get("gold_trace"), verses)})
    return out


# ---------------------------------------------------------------- the page
_CSS = """:root{--bg:#fbfaf7;--fg:#1d1b18;--mut:#6b655c;--line:#ddd6ca;--acc:#7a3e12;--warn:#9a2b1f}
@media (prefers-color-scheme:dark){:root{--bg:#1b1a18;--fg:#ece7de;--mut:#a39b8f;--line:#3a3631;--acc:#e0a46f;--warn:#f08a7a}}
body{background:var(--bg);color:var(--fg);font:16px/1.6 "Noto Serif TC",serif;margin:0 auto;max-width:960px;padding:16px}
h1{font-size:1.6rem}h2{border-bottom:2px solid var(--acc);padding-bottom:4px;margin-top:2.2rem}
.card{border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin:14px 0}
.mut{color:var(--mut);font-size:.9rem}.v{margin:2px 0 2px 1em}.k{font-family:monospace;color:var(--acc)}
.warn{color:var(--warn)}label{margin-right:1.2em}textarea{width:100%;min-height:3em;background:var(--bg);color:var(--fg)}
table{border-collapse:collapse;margin:6px 0}td,th{border:1px solid var(--line);padding:2px 6px;vertical-align:top}
button{font-size:1rem;padding:6px 14px;margin:12px 0}"""


def _e(s: Any) -> str:
    return html.escape("" if s is None else (s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)))


def _verses_html(texts: Sequence[Sequence[str]]) -> str:
    return "".join(f'<div class="v"><span class="k">{_e(u)}</span> {_e(t)}</div>' for u, t in texts) or \
        '<div class="v warn">（找不到這個經節鍵）</div>'


def _item_html(part: Mapping[str, Any], title: str = "") -> str:
    steps = "".join(f"<div>{_e(s['person'])}：{_e(s['fact'])}　<span class='k'>{_e(s['verse'])}</span></div>"
                    f"{_verses_html(s['texts'])}" for s in part["steps"])
    return (f"{f'<div class=mut>{_e(title)}</div>' if title else ''}<p><b>{_e(part['question'])}</b></p>"
            f"<div>出題者答案：{_e(part['answer'])}　算法：{_e(part['convention'])}</div>"
            f"<div class='mut'>附註：{_e(part['notes'])}</div>{steps}")


def _audit_html(a: Mapping[str, Any] | None) -> str:
    if not a:
        return ""
    fs = "".join(f"<div class='v'>{_e(f.get('severity'))}：{_e(f.get('issue'))}（建議：{_e(f.get('suggested_fix'))}）</div>"
                 for f in a.get("findings") or ())
    return f"<div>稽核者的值：{_e(a['value'])}</div><div>稽核者的讀法：{_e(a['reading'])}</div>{fs}"


def _head_html(r: Mapping[str, Any]) -> str:
    marker = f"　辨識詞：{_e(r['marker'])}" if r["marker"] else ""
    return (f"<div class='mut'>{_e(r['qid'])}　{_e(r['sid'])}　{_e(r['qtype'])}　Genesis {_e(r['chapter'])}</div>"
            f"<div>{_e(r['definition'])}{_e(r['identity'])}</div><div>X＝{_e(r['x'])}　Y＝{_e(r['y'])}{marker}</div>"
            f"<div>程式 gold：<b>{_e(r['gold'])}</b></div>")


def _choices(prefix: str, sid: str, options: Sequence[str], disabled: Sequence[str] = ()) -> str:
    radios = "".join(f"<label><input type='radio' name='{prefix}_{_e(sid)}' value='{o}'"
                     f"{' disabled' if o in disabled else ''}>{o}</label>" for o in options)
    return (radios + f"<label><input type='checkbox' name='G_{_e(sid)}'>程式 gold 錯</label>"
            f"<textarea name='N_{_e(sid)}' placeholder='意見（revise 必填）'></textarea>")


def _trace_html(t: Mapping[str, Any] | None) -> str:
    if not t:
        return ""
    rows = "".join(f"<tr><td class='k'>{_e(v['unit'])}</td><td>{'讀取' if v['read'] else ''}</td>"
                   f"<td>{'引用' if v['cited'] else ''}</td><td>{_e(v['numbers'])}</td><td>{_verses_html(v['texts'])}"
                   f"</td></tr>" for v in t["verses"])
    agree = "一致" if t["agrees"] else "<span class='warn'>不一致（K-gold）</span>"
    return (f"<div>CPU 比對：獨立讀取的值 {_e(t['reader_value'])}，與程式 gold {agree}；出題者 {_e(t['writer_value'])}，"
            f"稽核者 {_e(t['auditor_value'])}</div><div class='mut'>引用但讀取沒用：{_e(t['cited_not_read'])}；"
            f"讀取用了但沒引用：{_e(t['read_not_cited'])}；找不到的引用：{_e(t['unresolved_cited'])}</div>"
            f"<table><tr><th>經節</th><th>讀取</th><th>引用</th><th>數字</th><th>經文</th></tr>{rows}</table>")


def page_html(questions: Sequence[Mapping[str, Any]], disputes: Sequence[Mapping[str, Any]], note: str) -> str:
    parts = [f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>Kay 抽查</title><style>{_CSS}</style></head><body>",
             f"<h1>Kay 抽查</h1><p class='mut'>{_e(note)}</p><p class='mut'>{_e(QUESTION_RULE)}</p>",
             f"<h2>一、已過的 {len(questions)} 題（accept／revise／drop）</h2>"]
    for q in questions:
        parts.append(f"<div class='card' data-q='{_e(q['sid'])}'>{_head_html(q)}{_item_html(q)}{_audit_html(q['audit'])}"
                     f"{_choices('Q', q['sid'], Q_DECISIONS)}</div>")
    parts.append(f"<h2>二、爭議區 {len(disputes)} 件（keep／drop）</h2>")
    for d in disputes:
        mech = "".join(f"<div class='v'>{_e(m.get('rule'))}：{_e(m.get('detail'))} {_e(m.get('quote'))}</div>"
                       for m in d["mech"] if m.get("level", "error") == "error")
        parts.append(f"<div class='card' data-d='{_e(d['sid'])}'>{_head_html(d)}<div><b>{_e(d['label'])}</b></div>"
                     f"<div>理由：{_e(d['reason'])}</div><div class='mut'>{_e(d['keep_means'])}</div>"
                     f"<div>三方的值：{_e(d['values'])}</div>{_item_html(d['candidate'], '要決定留或刪的稿')}"
                     f"{_item_html(d['audited'], '稽核者讀過、機械檢查通過的上一版') if d['audited'] else ''}"
                     f"{_audit_html(d['audit'])}{mech}{_trace_html(d['trace'])}"
                     f"{_choices('D', d['sid'], D_DECISIONS, () if d['keep_allowed'] else ('keep',))}</div>")
    parts.append("<button id='go'>產生決定 JSON</button><textarea id='out' readonly></textarea><script>"
                 "function pick(sel,key){var o={};document.querySelectorAll(sel).forEach(function(c){var s=c.dataset[key],"
                 "r=c.querySelector('input[type=radio]:checked');o[s]={decision:r?r.value:null,"
                 "gold_wrong:c.querySelector('input[type=checkbox]').checked,note:c.querySelector('textarea').value};});"
                 "return o;}document.getElementById('go').onclick=function(){document.getElementById('out').value="
                 "JSON.stringify({questions:pick('[data-q]','q'),disputes:pick('[data-d]','d')},null,1);};"
                 "</script></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------- draw
def draw(paths: S.Paths = S.Paths(), *, names: P.Names | None = None, verses: Verses = RU.verse_text) -> dict[str, Any]:
    """The page, once: after K-P let the line go on and every written slot is done."""
    with S.locked(paths):
        plan = S.load_plan(paths)
        state = S.load_state(paths, plan)
        if state.get("kay"):
            raise HoError("Kay's page was already drawn (prereg §3.7: once)")
        sids = plan.planned(S.kp_go(paths)["n_target"])
        if state.get("k_gold_cpu"):
            raise HoError("K-gold (CPU trace) stopped the line")
        if not S.done(state, sids):
            raise HoError(f"questions not finished: {S.summary(state, sids)['by_status']}")
        names = names or P.load_names(paths.names)
        passed, disputes = S.with_status(state, sids, S.PASSED), S.with_status(state, sids, S.DISPUTE)
        sampled = sample(passed)
        note = (f"題：random.Random({GC.KAY_SAMPLE_SEED}).sample(sorted(已過的 {len(passed)} 個題位), {len(sampled)})；"
                f"爭議 {len(disputes)} 件。產生時間 {now()}。")
        page = H.writable(paths.kay_dir / PAGE)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(page_html(question_rows(state, plan, names, sampled, verses),
                                  dispute_rows(state, plan, names, disputes, verses), note), encoding="utf-8")
        doc = {"schema": SCHEMA + ".sample", "seed": GC.KAY_SAMPLE_SEED, "k": GC.KAY_QUESTIONS, "candidates": sorted(passed),
               "sampled": sampled, "disputes": disputes, "page_sha256": GC.sha256_file(page), "t": now()}
        write_json(paths.kay_dir / SAMPLE, doc)
        S.save_state(paths, {**state, "kay": {"drawn": now(), "sampled": sampled, "disputes": disputes,
                                              "candidates": sorted(passed), "applied": False, "decisions": None}})
        return doc


# ---------------------------------------------------------------- apply
def _bool(v: Any, where: str) -> bool:
    if v in (None, False, True):
        return bool(v)
    raise HoError(f"{where}: gold_wrong must be true or false")


def check_decisions(kay: Mapping[str, Any], state: Mapping[str, Any], decisions: Mapping[str, Any]) -> dict[str, Any]:
    """Every sampled and disputed sid decided, and only those; a revise note memory-marker checked (it goes into a
    prompt); a row-3 dispute takes no keep. Returns the normalised decisions."""
    qs, ds = decisions.get("questions") or {}, decisions.get("disputes") or {}
    if set(qs) != set(kay["sampled"]) or set(ds) != set(kay["disputes"]):
        raise HoError("decide every sampled question and every dispute, and only those")
    out: dict[str, Any] = {"questions": {}, "disputes": {}}
    for sid, d in qs.items():
        if not isinstance(d, Mapping) or d.get("decision") not in Q_DECISIONS:
            raise HoError(f"{sid}: decision must be one of {Q_DECISIONS}")
        note = str(d.get("note") or "").strip()
        if d["decision"] == "revise":
            if not note:
                raise HoError(f"{sid}: revise needs a note")
            try:
                B.require(note, f"Kay note {sid}", "agent")
            except B.BlindingError as err:
                raise HoError(f"{sid}: reword the note ({err})") from None
        out["questions"][sid] = {"decision": d["decision"], "note": note, "gold_wrong": _bool(d.get("gold_wrong"), sid)}
    for sid, d in ds.items():
        if not isinstance(d, Mapping) or d.get("decision") not in D_DECISIONS:
            raise HoError(f"{sid}: dispute decision must be one of {D_DECISIONS}")
        if d["decision"] == "keep" and S.slot(state, sid)["dispute"]["kind"] == "program_differs":
            raise HoError(f"{sid}: §3.6 row 3 has no keep (gold wrong is K-gold, else the slot is deleted)")
        out["disputes"][sid] = {"decision": d["decision"], "note": str(d.get("note") or "").strip(),
                                "gold_wrong": _bool(d.get("gold_wrong"), sid)}
    return out


def _revise(state: Mapping[str, Any], sid: str, note: str) -> dict[str, Any]:
    att = S.current(S.slot(state, sid))
    return S.update_attempt(state, sid, S.KAY_FIX, "Kay 要求修改（§3.7，不算嘗試）", root="kay", post_kay=True,
                            fix_request={"source": "kay", "issues": [[["agent", note]]]},
                            fixes={**att["fixes"], "kay": att["fixes"]["kay"] + 1},
                            kay_revision={"note": note, "status": "pending", "t": now()})


def _keep(state: Mapping[str, Any], sid: str) -> dict[str, Any]:
    d = S.slot(state, sid)["dispute"]
    if keep_key(d) in ("no_change:mech", "audit_mech_conflict:audit"):
        errs = [m for m in d.get("mech") or () if m.get("level", "error") == "error"]
        return S.update_attempt(state, sid, S.AUDIT, "Kay 留：推翻機械檢查，接著稽核", root="kay", post_kay=True,
                                item=d["candidate"], kept_mech=errs, fix_request=None, audit_broke=None)
    v = d.get("values") or {}
    agree = all(isinstance(v.get(k), int) and not isinstance(v.get(k), bool) for k in ("writer", "auditor", "gold")) \
        and v["writer"] == v["auditor"] == v["gold"]
    if agree:
        return S.update_attempt(state, sid, S.STEP_PASSED, "Kay 留，三方值一致", root="kay", post_kay=True,
                                item=d["candidate"], kept_mech=[])
    return S.close(state, sid, S.FAILED, "Kay 留，但三方值不一致：以失敗收", "kept_dispute")


def apply(paths: S.Paths = S.Paths(), decisions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    with S.locked(paths):
        plan = S.load_plan(paths)
        state = S.load_state(paths, plan)
        kay = state.get("kay")
        if not kay:
            raise HoError("no Kay page drawn yet")
        if kay.get("applied"):
            raise HoError("Kay's decisions were already applied")
        dec = check_decisions(kay, state, decisions or {})
        for sid in sorted(dec["questions"], key=lambda s: plan.slots[s].position):
            q = dec["questions"][sid]
            if q["decision"] == "revise":
                state = _revise(state, sid, q["note"])
            elif q["decision"] == "drop":
                state = S.close(state, sid, S.KAY_DROPPED, f"Kay 刪除（§3.7）：{q['note']}")
        for sid in sorted(dec["disputes"], key=lambda s: plan.slots[s].position):
            d = dec["disputes"][sid]
            kind = S.slot(state, sid)["dispute"]["kind"]
            if d["decision"] == "keep":
                state = _keep(state, sid)
            else:
                state = S.close(state, sid, S.OTHER_QUANTITY if kind == "program_differs" else S.KAY_DROPPED,
                                f"Kay 刪除爭議（{kind}）：{d['note']}")
            state["slots"][sid]["dispute"]["decision"] = {**d, "t": now()}
        state = {**state, "kay": {**kay, "applied": True, "applied_t": now(), "decisions": dec}}
        S.save_state(paths, state)
        write_record(paths, state, plan)
        return state


# ---------------------------------------------------------------- K-Kay, K-gold and kay.json
def _revision(rec: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return next((a["kay_revision"] for a in reversed(rec["attempts"]) if a.get("kay_revision")), None)


def record(state: Mapping[str, Any], plan: S.Plan) -> dict[str, Any]:
    """kay.json's content: the decisions (no text but Kay's notes), K-Kay, K-gold, and whether everything settled."""
    kay = require_applied(state)
    dec = kay["decisions"]
    sampled = kay["sampled"]
    dropped = [s for s in sampled if dec["questions"][s]["decision"] == "drop"]
    revs = {s: (_revision(S.slot(state, s)) or {}).get("status") for s in sampled
            if dec["questions"][s]["decision"] == "revise"}
    failed = sorted(s for s, st in revs.items() if st in ("failed", "cap_stopped"))
    pending = sorted(s for s, st in revs.items() if st == "pending")
    live = [s for s in plan.order if S.slot(state, s)["status"] in S.LIVE or S.slot(state, s)["inflight"]]
    gold_wrong = sorted(s for part in ("questions", "disputes") for s, d in dec[part].items() if d["gold_wrong"])
    n_dropped = len(dropped) + len(failed)
    k_kay, k_gold = n_dropped >= K_KAY_STOP, bool(gold_wrong or state.get("k_gold_cpu"))
    rule = "K-gold" if k_gold else "K-Kay" if k_kay else None
    value = (f"Kay 判定程式 gold 錯（{len(gold_wrong)} 件）" if gold_wrong else "CPU 追查：程式 gold 錯") if k_gold else \
        f"{n_dropped}/{len(sampled)} 題刪除（含修改未過 {len(failed)} 題）"
    return {"schema": SCHEMA, "t": now(), "n_sampled": len(sampled), "sampled": sampled, "n_disputes": len(kay["disputes"]),
            "disputes": kay["disputes"], "decisions": {p: {s: d["decision"] for s, d in dec[p].items()} for p in dec},
            "notes": {s: d["note"] for p in dec for s, d in dec[p].items() if d["note"]},
            "dropped": dropped, "revisions": revs, "revisions_failed": failed, "revisions_pending": pending,
            "n_dropped": n_dropped, "k_kay_stop_at": K_KAY_STOP, "k_kay": k_kay, "gold_wrong": gold_wrong,
            "k_gold_cpu": sorted(state.get("k_gold_cpu") or ()), "k_gold": k_gold, "final": not pending and not live,
            "stop": rule is not None, "rule": rule, "sentence": AG.stop_sentence(rule, value, "未凍結") if rule else None}


def write_record(paths: S.Paths, state: Mapping[str, Any], plan: S.Plan) -> dict[str, Any]:
    doc = record(state, plan)
    write_json(paths.kay, doc)
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kay 抽查頁（§3.7）：十題已過的題＋爭議區")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draw")
    sub.add_parser("apply").add_argument("--decisions", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        doc = draw()
        print(f"kay_g.py draw: {len(doc['sampled'])} questions, {len(doc['disputes'])} disputes -> {S.Paths().kay_dir}")
        return 0
    state = apply(decisions=read_json(a.decisions))
    rec = record(state, S.load_plan())
    print(f"kay_g.py apply: dropped {rec['n_dropped']}/{rec['n_sampled']}, revisions pending "
          f"{len(rec['revisions_pending'])}" + (f"; {rec['sentence']}" if rec["stop"] else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HoError, OSError, ValueError) as err:
        print(f"kay_g.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
