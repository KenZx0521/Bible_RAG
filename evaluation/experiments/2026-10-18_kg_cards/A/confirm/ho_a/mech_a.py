"""Mechanical checks of the drafted questions (confirm_A.md §2.2, §2.9; §1.4 through support.py).

Every rule is checked (not just the first); level error sends the draft back for one fix, warn is
only recorded. Details are neutral Chinese with king names from the question, never reference ids,
because they are shown to the writer as fix requests.

  schema             §2.8 fields and types; chain starts with role seed and ends with role answer
  slot_mismatch      id, segment, qtype, kingdom of the slot; S1a_rev: k differs from the slot-1 question
  seeds_named        the question names every seed; a same-kingdom namesake needs 「（父的兒子）」
  seeds_chain        S1a/S1c/S4: exactly one seed = chain[0]; S1b: exactly two seeds = chain[0] and chain[-1]
  extra_king         a king name other than the seeds and a namesake seed's required father tag (both
                     kingdoms); a required father tag that names another king of the chain is an error too
  has_ref            a citation (\\d+:\\d+, 章, 節, 列王紀 / 歷代志, 王上8 / 代下3 ...)
  forbidden_form     S2 / S3 / single-attribute wording (第幾年, 在位期間, 幾年, 幾歲 ...) or a second question
  chain_len          ≥3 kings; S1a |k|∈{2,3} = chain steps; S1c ≥2 steps; S4 ≥2 steps, seed not 亞哈謝/約雅斤
  s4_convention      S4 states the convention (登基年齡, 在位年數) and fills `convention`
  s1b_short_seg      S1b in a 2-edge segment
  seg_cross, name_unresolved   support.support_record (§1.4)
  basis_exists, basis_in_range every chain step has basis keys; each exists and is a Kings verse in range
  genealogy_shortcut support.genealogy_shortcut on the chain (S1a, S1b)
  key_form           one key: a name key whose text names the answer king, accept without another
                     same-kingdom king's main name; or a count key (S1b) = chain steps, unit 次|代|任|位
  dup_in_segment     same (qtype, seeds, answer) as another live question of the segment

Hidden flags (support_record: ref_disagree, gen_passage, answer_is_father) are returned apart and never shown.

    mech_a.py questions   [--root R]     # recheck every passed question → <root>/mech/
    mech_a.py transcripts [--root R]     # every run of every record → <root>/mech/
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import ROOT, C, HoError, Violation, meta, write_json  # first: sets sys.path

import prompts_a as P  # noqa: E402
import state_a as S  # noqa: E402
import support as SU  # noqa: E402
import transcript_a as TR  # noqa: E402

RULES = ("schema", "slot_mismatch", "seeds_named", "seeds_chain", "extra_king", "has_ref", "forbidden_form", "chain_len",
         "s4_convention", "s1b_short_seg", "seg_cross", "name_unresolved", "basis_exists", "basis_in_range",
         "genealogy_shortcut", "key_form", "dup_in_segment")
HAS_REF = re.compile(r"\d+\s*[:：]\s*\d+|[章節]|列王紀|歷代志|(?:王上|王下|代上|代下)\s*\d")
FORBIDDEN = re.compile(r"第幾年|哪一年|在位第|在位期間|同時代|同一時期|同時|幾年|幾歲|多少年|多少歲|多久|母親")
COUNT_UNITS = tuple(C.S1B_UNIT.split("|"))


def _v(rule: str, detail: str, level: str = "error") -> Violation:
    return Violation(rule, detail, level)


def _schema(q: Mapping[str, Any]) -> list[Violation]:
    out = [_v("schema", f"缺欄位 {k}") for k in P.ITEM_KEYS if k not in q]
    if out:
        return out
    if not (isinstance(q["question"], str) and q["question"].strip()):
        out.append(_v("schema", "question 必須是非空字串"))
    if q["qtype"] not in P.QTYPES or q["kingdom"] not in P.KINGDOMS:
        out.append(_v("schema", "qtype 或 kingdom 不在允許值內"))
    seeds, chain, ans = q["seeds"], q["chain"], q["answer"]
    if not (isinstance(seeds, list) and 1 <= len(seeds) <= 2 and all(isinstance(s, dict) and isinstance(s.get("name"), str)
                                                                     for s in seeds)):
        out.append(_v("schema", "seeds 必須是 1 到 2 個 {name, father}"))
    if not (isinstance(chain, list) and len(chain) >= 2 and all(
            isinstance(c, dict) and isinstance(c.get("king"), str) and c.get("role") in P.ROLES
            and isinstance(c.get("basis"), list) for c in chain)):
        return out + [_v("schema", "chain 必須是 {king, father, role, fact, basis} 的清單（至少 2 列）")]
    roles = [c["role"] for c in chain]
    if roles[0] != "seed" or roles[-1] != "answer" or any(r != "step" for r in roles[1:-1]):
        out.append(_v("schema", "chain 第一列 role 必須是 seed、最後一列是 answer、其餘是 step"))
    if not (isinstance(ans, dict) and ans.get("kind") in ("name", "count") and isinstance(ans.get("text"), str)
            and isinstance(ans.get("accept"), list)):
        out.append(_v("schema", "answer 必須是 {kind: name|count, text, accept, value, unit}"))
    for k in ("k", "n"):
        if q[k] is not None and not isinstance(q[k], int):
            out.append(_v("schema", f"{k} 必須是整數或 null"))
    return out


def _slot(q: Mapping[str, Any], qid: str, seg: Mapping[str, Any], slot_type: str,
          reverse_of: Mapping[str, Any] | None) -> list[Violation]:
    want = "S1a" if slot_type == "S1a_rev" else slot_type
    out = []
    if q.get("id") != qid or q.get("segment") != seg["id"]:
        out.append(_v("slot_mismatch", f"id 必須是 {qid}、segment 必須是 {seg['id']}"))
    if q.get("qtype") != want or q.get("kingdom") != seg["kingdom_name"]:
        out.append(_v("slot_mismatch", f"本題必須是 {want}，國別 {seg['kingdom_name']}"))
    if slot_type == "S1a_rev" and reverse_of is not None and q.get("k") == reverse_of.get("k"):
        out.append(_v("slot_mismatch", f"方向與 k 都和本段已出的 S1a 題相同（k＝{q.get('k')}）：要改成相反方向或不同的 k"))
    return out


def _seeds(q: Mapping[str, Any], seed_ids: Sequence[str | None]) -> list[Violation]:
    out, text = [], q["question"]
    for s, x in zip(q["seeds"], seed_ids):
        nm = SU.parse_name(s["name"])[0]
        f = SU.required_tag(x) if x else None
        if nm not in text:
            out.append(_v("seeds_named", f"題目沒有點名起點王「{nm}」"))
        elif f and f"（{f}的兒子）" not in text and f"{f}的兒子{nm}" not in text:
            out.append(_v("seeds_named", f"同國有同名的王：「{nm}」要寫成「{nm}（{f}的兒子）」"))
    return out


def _seeds_chain(q: Mapping[str, Any], seed_ids: Sequence[str | None], chain_ids: Sequence[str | None]) -> list[Violation]:
    """seeds = the chain's first king (S1b: its first and last king); ids when resolved, else written names."""
    if all(seed_ids) and chain_ids and chain_ids[0] and chain_ids[-1]:
        seeds, ends = list(seed_ids), [chain_ids[0], chain_ids[-1]]
    else:
        seeds = [SU.parse_name(s["name"])[0] for s in q["seeds"]]
        ends = [SU.parse_name(q["chain"][0]["king"])[0], SU.parse_name(q["chain"][-1]["king"])[0]]
    if q["qtype"] == "S1b":
        ok = len(seeds) == 2 and set(seeds) == set(ends) and ends[0] != ends[1]
        detail = "seeds 必須正好是推算鏈的第一位與最後一位王（兩位）"
    else:
        ok = seeds == ends[:1]
        detail = "seeds 必須正好是一位，而且就是推算鏈第一列（role seed）的王"
    return [] if ok else [_v("seeds_chain", detail)]


def _tag_leak(q: Mapping[str, Any], seed_ids: Sequence[str | None], chain_ids: Sequence[str | None]) -> list[Violation]:
    out = []
    for s, x in zip(q["seeds"], seed_ids):
        if x and SU.tag_leak(x, chain_ids):
            nm = SU.parse_name(s["name"])[0]
            out.append(_v("extra_king", f"「{nm}（{SU.required_tag(x)}的兒子）」的父名是推算鏈上的另一位王："
                                        "換一個起點王或方向"))
    return out


def _wording(q: Mapping[str, Any], seed_ids: Sequence[str | None]) -> list[Violation]:
    text, out = q["question"], []
    extra = SU.extra_kings(text, [x for x in seed_ids if x])
    if extra:
        out.append(_v("extra_king", f"題目寫出了起點王以外的王名：{'、'.join(extra)}"))
    refs = sorted(set(HAS_REF.findall(text)))
    if refs:
        out.append(_v("has_ref", f"題目含經文出處：{'、'.join(refs)}"))
    bad = sorted(set(FORBIDDEN.findall(text)))
    if bad or text.count("？") + text.count("?") > 1:
        out.append(_v("forbidden_form", "題目像同步紀年、同時代、單一記載或附加問題（"
                      + "、".join(bad or ["兩個問號"]) + "）：只問一個推算答案"))
    if q["qtype"] == "S4" and not ("登基年齡" in text and "在位年數" in text and str(q.get("convention") or "").strip()):
        out.append(_v("s4_convention", "S4 題目要寫明依登基年齡與在位年數前後相接推算，convention 要寫兩種算法的數字"))
    return out


def _chain_len(q: Mapping[str, Any], chain_ids: Sequence[str | None], seg: Mapping[str, Any]) -> list[Violation]:
    steps, qt, out = len(q["chain"]) - 1, q["qtype"], []
    if steps < 2:
        out.append(_v("chain_len", "推算鏈至少要有 3 位王（2 次交接）"))
    if qt == "S1a" and (q.get("k") not in (-3, -2, 2, 3) or abs(q.get("k") or 0) != steps):
        out.append(_v("chain_len", f"S1a 的 k 必須是 ±2 或 ±3，而且等於推算鏈的交接次數（現為 {steps}）"))
    if qt == "S1c" and not (isinstance(q.get("n"), int) and q["n"] >= 1):
        out.append(_v("chain_len", "S1c 的 n 必須是正整數"))
    if qt == "S4" and chain_ids and chain_ids[0] in C.S4_SEED_BANNED:
        out.append(_v("chain_len", "S4 的起點王不可是亞哈謝或約雅斤"))
    if qt == "S1b" and seg["n_edges"] < 3:
        out.append(_v("s1b_short_seg", "本段只有 2 次交接，不出交接次數題"))
    return out


def _basis(q: Mapping[str, Any], seg: Mapping[str, Any]) -> list[Violation]:
    out, order = [], SU.verse_ord()
    for i, c in enumerate(q["chain"]):
        keys = [k for k in c["basis"] if isinstance(k, str)]
        if not keys and (c["role"] != "seed" or q["qtype"] == "S4"):
            out.append(_v("basis_exists", f"推算鏈第 {i + 1} 列（{c['king']}）沒有依據經節"))
        for k in keys:
            if k not in order:
                out.append(_v("basis_exists", f"推算鏈第 {i + 1} 列的經節 {k} 不存在（用整節或合併節鍵）"))
            elif not SU.in_range(seg, k):
                out.append(_v("basis_in_range", f"推算鏈第 {i + 1} 列的經節 {k} 不在本段範圍的列王紀經文內"))
    return out


def _key(q: Mapping[str, Any], answer: str | None, kd: str) -> list[Violation]:
    ans, out = q["answer"], []
    steps = len(q["chain"]) - 1
    if q["qtype"] == "S1b":
        if ans["kind"] != "count" or not isinstance(ans.get("value"), int) or ans["value"] < 2:
            out.append(_v("key_form", "交接次數題的答案鍵是 count，value 是至少 2 的整數"))
        elif ans["value"] != steps:
            out.append(_v("key_form", f"答案次數 {ans['value']} 和推算鏈的交接次數 {steps} 不一致"))
        if ans.get("unit") not in COUNT_UNITS:
            out.append(_v("key_form", "交接次數的 unit 要填「次」"))
        return out
    if ans["kind"] != "name":
        return [_v("key_form", "本題型的答案鍵是王名（kind name）")]
    if answer is None:
        return out
    nm = SU.parse_name(ans["text"])[0]
    accept = [SU.parse_name(a)[0] for a in ans["accept"] if isinstance(a, str)]
    if nm not in SU.names(answer) and nm not in accept:
        out.append(_v("key_form", f"答案「{nm}」和推算鏈的答案王不一致"))
    mains = {SU.ref()[y]["name"] for y in SU.ref() if y != answer and SU.kingdom(y) == kd}
    clash = sorted({a for a in [nm, *accept] if a in mains and a not in SU.names(answer)[:1]})
    if clash:
        out.append(_v("key_form", f"可接受寫法收了同國另一位王的名字：{'、'.join(clash)}"))
    return out


def signature(q: Mapping[str, Any], rec: Mapping[str, Any]) -> tuple:
    ans = q.get("answer") or {}
    tail = ans.get("value") if q.get("qtype") == "S1b" else rec.get("answer")
    return q.get("qtype"), tuple(rec.get("seeds") or ()), tail


def check_item(q: Mapping[str, Any], qid: str, seg: Mapping[str, Any], slot_type: str,
               segments: Sequence[Mapping[str, Any]], others: Sequence[Mapping[str, Any]] = (),
               reverse_of: Mapping[str, Any] | None = None) -> tuple[list[Violation], dict[str, Any]]:
    """(violations, hidden flags) of one draft; `others` = the segment's other live questions."""
    out = _schema(q)
    if any(v.detail.startswith(("缺欄位", "chain 必須")) for v in out):
        return out, {}
    rec = SU.support_record(dict(q), list(segments))
    out += _slot(q, qid, seg, slot_type, reverse_of)
    out += [_v("name_unresolved", "鏈上或起點有王名對不到本國的王（用和合本修訂版拼法；同名王寫「名（父的兒子）」）")
            ] if "name_unresolved" in rec["errors"] else []
    out += [_v("seg_cross", "鏈上有王不在本段範圍")] if "seg_cross" in rec["errors"] else []
    out += _seeds(q, rec["seeds"]) + _seeds_chain(q, rec["seeds"], rec["chain"]) + _tag_leak(q, rec["seeds"], rec["chain"])
    out += _wording(q, rec["seeds"]) + _chain_len(q, rec["chain"], seg)
    out += _basis(q, seg) + _key(q, rec["answer"], C.KD[q["kingdom"]] if q["kingdom"] in C.KD else "")
    if rec["genealogy_shortcut"]:
        out.append(_v("genealogy_shortcut", "歷代志上或馬太福音的家譜中，有一節經文單獨寫出整條父子鏈（"
                      + "、".join(rec["genealogy_shortcut"]) + "），單看那一節就能讀出答案"))
    sig = signature(q, rec)
    for o in others:
        if signature(o, SU.support_record(dict(o), list(segments))) == sig:
            out.append(_v("dup_in_segment", f"和本段已出的題重複（同題型、同起點、同答案）：{o.get('id')}"))
    return out, dict(rec["hidden"])


def errors_of(found: Sequence[Violation]) -> list[Violation]:
    return [v for v in found if v.level == "error"]


def fix_issues(found: Sequence[Violation]) -> list[str]:
    """Neutral fix request lines for the writer (§1.4: 中性提示)."""
    return list(dict.fromkeys(v.detail for v in errors_of(found)))


def recheck(state: Mapping[str, Any], seg_doc: Mapping[str, Any], slots: Sequence[S.Slot]) -> dict[str, list]:
    """Every passed question again, against the segment's other passed questions (freeze gate)."""
    rows, by_key = S.segment_rows(seg_doc), {s.key: s for s in slots}
    out = {}
    for r in S.records(state, (S.PASSED,)):
        others = [o for o in S.segment_passed(state, r["segment"], exclude=r["id"])]
        ref = S.reverse_reference(state, by_key[r["slot"]]) if r["slot_number"] != 1 else None
        found, _ = check_item(r["item"], r["id"], rows[r["segment"]], r["slot_type"], seg_doc["segments"], others, ref)
        out[r["id"]] = [v.as_dict() for v in found]
    return out


def transcripts(root: Path, state: Mapping[str, Any]) -> dict[str, list]:
    return {run: [v.as_dict() for v in TR.check_run(root, run)] for r in state["records"] for run in r["runs"]}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="機械檢查（§2.9）：通過題重驗或 transcript 全檢")
    ap.add_argument("cmd", choices=("questions", "transcripts"))
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    state, seg_doc = S.load_state(a.root), S.load_segments()
    found = recheck(state, seg_doc, S.slot_plan(seg_doc)) if a.cmd == "questions" else transcripts(a.root, state)
    bad = sorted(k for k, vs in found.items() if any(v["level"] == "error" for v in vs))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = write_json(Path(a.root) / "mech" / f"{a.cmd}_{stamp}.json",
                     {"meta": meta(f"mech_a.py {a.cmd}"), "checked": len(found), "with_errors": bad, "violations": found})
    print(f"mech_a.py {a.cmd}: {len(found)} checked, {len(bad)} with errors -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HoError, OSError, ValueError) as err:
        print(f"mech_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
