"""Writes the repo's appendix.md of the ordered-chain arithmetic stage-0 (prereg §1 輸出, §11-3) from the store build.

Public, like experiment A's appendix A.3: item ids, family, question type, kingdom or chapter, L / k, the
segments touched and nested, seed ids, gold values (numbers; SYNC: the two kings' reference ids and names),
the SYNC answer-king distribution, the F3 echo table (keys_x's made-up lines), the K0 summary and sha256
values (store files, the K0-4 test files as k0.json records them, prompts, harness and test files,
experiment A's and the backend's files, the input pins). Never
a question, an answer, card text or a verse: ``leak_problems`` refuses any 8-character window of a question
or of a verse of the text layer, and any whole card line. ``check`` says whether the file on disk is what
``render`` gives for the store build now (run_x's gate before Ollama). Only this module writes into the repo,
and only appendix.md. Nothing here calls an LLM.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_x as R  # noqa: E402
import x_common as X  # noqa: E402

APPENDIX = X.HERE / "appendix.md"
WINDOW = 8
FAMILY_ORDER = ("DYN", "S6", "SYNC", "GEN")


# ---------------------------------------------------------------- cells
def _yn(v) -> str:
    return "—" if v is None else ("是" if v else "否")


def gold_cell(it: dict) -> str:
    if isinstance(it["gold"], dict):
        ref = {k["role"]: k.get("gold_ref") for k in it["keys"] if k["type"] == "name"}
        return "；".join(f"{r}＝{ref.get(r)} {it['gold'][r]}" for r in ("Y", "Z"))
    return str(it["gold"])


def seeds_cell(it: dict) -> str:
    names = [nm for _kd, nm in it["seed_names"]]
    out = " / ".join(f"{s} {nm}" for s, nm in zip(it["seeds"], names))
    return out + (f"（參照層 {' / '.join(it['seeds_ref'])}）" if it.get("seeds_ref") else "")


def item_rows(items: list[dict], meta: dict) -> list[str]:
    out = ["| 題號 | 族 | 題型 | 國／章 | L | k | 種子 id | gold | 碰到的段 | nested | 推導行含 gold | T-canon 窗含齊依據節 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        where = it["kingdom"] if it["family"] != "GEN" else f"創 {it['chapter']}"
        m = meta[it["id"]]
        out.append(f"| {it['id']} | {it['family']} | {it['qtype']} | {where} | {it.get('L') or '—'} | {it.get('k') or '—'} | "
                   f"{seeds_cell(it)} | {gold_cell(it)} | {' / '.join(it['units_touched']) or '—'} | {_yn(it['nested'])} | "
                   f"{_yn(m['covered'])} | {_yn(it.get('tcanon_complete'))} |")
    return out


def sync_rows(items: list[dict]) -> list[str]:
    sync = [it for it in items if it["family"] == "SYNC"]
    out = []
    for role, label in (("Z", "答案王（Z，配額依層 id 計，每位至多 2 題）"), ("Y", "第 k 位王（Y）")):
        cnt = Counter(next(f"{k['gold_ref']} {it['gold'][role]}" for k in it["keys"] if k.get("role") == role) for it in sync)
        out += [f"- {label}：" + "；".join(f"{k} ×{v}" for k, v in sorted(cnt.items())) + f"（{len(cnt)} 位）"]
    ks = Counter(it["k"] for it in sync)
    return out + [f"- k：" + "；".join(f"k＝{k} {v} 題" for k, v in sorted(ks.items()))]


def flag_text(flag: str) -> str:
    """An item flag; a Genesis homonym flag without the question's wording (it names the person as the question does)."""
    if flag.startswith("homonym shown as "):
        return "同名人物，題目以不在路徑上的親屬名辨識（§3.4）"
    return flag


def counts_lines(doc: dict) -> list[str]:
    items = doc["items"]
    by = Counter((it["family"], it["qtype"]) for it in items)
    out = ["- 題數：" + "；".join(f"{f} {q} {n}" for (f, q), n in sorted(by.items(), key=lambda x: (FAMILY_ORDER.index(x[0][0]), x[0][1])))
           + f"；共 {len(items)} 題。"]
    for fam, floor in (("DYN", 10), ("GEN", 7)):
        its = [it for it in items if it["family"] == fam]
        out.append(f"- {fam} 跨段 {sum(not it['nested'] for it in its)}/{len(its)} 題（§3.5 下限 {floor}），"
                   f"nested {sum(bool(it['nested']) for it in its)} 題。")
    out.append(f"- 候選池（排除後）：{doc['pools']}；抽樣 seed {doc['seed']}。")
    flags = [f"  - {it['id']}：{'；'.join(flag_text(f) for f in it['flags'])}" for it in items if it.get("flags")]
    return out + (["- 題目旗標："] + flags if flags else ["- 題目旗標：無"])


def k0_lines(k0: dict) -> list[str]:
    k3, k4, k6 = k0["K0_3"], k0["K0_4"], k0["K0_6"]
    reg, ck = k4["regress_a"], k0["K0_2"]["layer_checks"]
    return [f"- 整體：{'通過' if k0['pass'] else '未過'}；輸入釘值問題 {k0['pins'] or '無'}；實驗 A 凍結檔問題 {k0['frozen'] or '無'}；"
            f"出題檢查 {'通過' if k0['items']['pass'] else k0['items']['problems']}。",
            f"- K0-1（ref_v2 與 r4 欄位一致、王朝 gold 雙路）：{_yn(k0['K0_1']['pass'])}，{k0['K0_1']['n_items']} 題，"
            f"問題 {len(k0['K0_1']['problems'])} 題。",
            f"- K0-2（創世記層、創世記 gold 雙路）：{_yn(k0['K0_2']['pass'])}；beget＋remain＝total {ck['total_eq'][0]}/{ck['total_eq'][1]}、"
            f"子名 {ck['son_match'][0]}/{ck['son_match'][1]}、挪亞無 remain {_yn(ck['noah_no_remain'])}；列數 {ck['counts']}；"
            f"gold 問題 {len(k0['K0_2']['gold_problems'])} 題。",
            f"- K0-3（推導行）：王朝 a＝{k3['dynasty']['a']}、矛盾 {len(k3['dynasty']['line_problems'])} 題；"
            f"創世記 a＝{k3['genesis']['a']}、矛盾 {len(k3['genesis']['line_problems'])} 題（含壽數上限）。",
            f"- K0-4（計分器）：合成測試 {k4['tests']['summary']}（{', '.join(Path(f).name for f in k4['tests']['files'])}）；"
            f"各題 G 推導行照抄 {k4['copy_cases']['n']} 例、不符 {len(k4['copy_cases']['mismatch'])}；"
            f"A／A_confirm 記錄重算 {reg['n_records']} 筆、{reg['n_keys']} 鍵，原本對的變錯 {reg['lost']}、記錄分數下降 "
            f"{reg['score_down']}、變對 {reg['gained']}（{reg['gained_items']}）。",
            "- K0-5（截斷 smoke）：harness、本附錄與 K0 commit 之後才跑，是第一次叫 Ollama；結果在 store smoke/smoke.json。",
            f"- K0-6（字數與列）：{_yn(k6['pass'])}；各臂附加字數最大 {k6['block_chars_max']}（上限 {k6['cap']}）；"
            f"問題 {len(k6['problems'])} 題、job 問題 {k6['job_problems'] or '無'}。"]


def echo_rows(k0: dict) -> list[str]:
    out = ["| 案例 | 答案行（自造，甲、丁是假名） | 取到的值 | 分數 |", "|---|---|---|---|"]
    return out + [f"| {r['case']} | {r['line']} | {r['value']} | {r['score']} |" for r in k0["K0_4"]["f3_echo"]]


def arm_lines(meta_doc: dict) -> list[str]:
    meta, sm = meta_doc["meta"], meta_doc["summary"]
    out = [f"- job：{sm['n_jobs']} 次；{sm['by_family_arm']}。"]
    for a in ("G", "T-rows", "T-canon"):
        xs = [m["block_chars"][a] for m in meta.values() if a in m["block_chars"]]
        out.append(f"- {a} 附加字數：平均 {sum(xs) / len(xs):.1f}、最大 {max(xs)}（{len(xs)} 題）。")
    out.append(f"- user prompt 最大 {max(max(m['user_chars'].values()) for m in meta.values())} 字；"
               f"刪列 {sum(m['dropped_rows'] for m in meta.values())}、刪行 {sum(m['dropped_lines'] for m in meta.values())}。")
    tc = Counter((m["family"], m["tcanon_complete"]) for m in meta.values() if m["tcanon_complete"] is not None)
    out.append("- T-canon 窗含齊依據節：" + "；".join(f"{f} {tc[(f, True)]}/{tc[(f, True)] + tc[(f, False)]}"
                                               for f in ("DYN", "S6", "SYNC")) + "（GEN 不跑 T-canon，§4）。")
    return out


def sha_lines(inp: dict) -> list[str]:
    k0 = inp[R.K0_FILE]
    sm = inp["arms_meta.json"]["summary"]
    out = ["| 檔 | sha256 |", "|---|---|"]
    out += [f"| store {n} | `{k0['sha256'][n]}` |" for n in R.DATA_FILES]
    out += [f"| store {R.K0_FILE} | `{X.sha256_file(R.store(R.K0_FILE))}` |"]
    out += [f"| K0-4 合成測試 {Path(f).name}（k0.json） | `{v}` |"
            for f, v in sorted((k0["K0_4"]["tests"].get("files_sha256") or {}).items())]
    out += [f"| 全部 prompt（job_id, system, user 依序） | `{sm['prompts_sha256']}` |",
            f"| SYSTEM_PROMPT | `{sm['system_prompt_sha256']}` |", f"| USER_TEMPLATE | `{sm['user_template_sha256']}` |",
            f"| ref_layer_v2.json | `{X.REF_V2_SHA256}` |", f"| r4 regnal_layer.json | `{X.R4_LAYER_SHA256}` |",
            f"| 文字層 digest | `{X.TEXT_DIGEST}` |", f"| powerA_strong.py | `{X.POWER_SRC_SHA256}` |"]
    out += [f"| harness {n} | `{v}` |" for n, v in sorted(R.code_sha256().items())]
    out += [f"| 實驗 A {n} | `{v}` |" for n, v in X.experiment_files_sha256().items()]
    out += [f"| backend {n} | `{v}` |" for n, v in X.backend().files_sha256.items()]
    return out


def render(inp: dict) -> str:
    doc, k0, meta = inp["items.json"], inp[R.K0_FILE], inp["arms_meta.json"]["meta"]
    items = doc["items"]
    lines = ["# 附錄：有序鏈算術 stage-0（harness 建置時寫入，尚無任何臂的生成）", "",
             "規格：`prereg.md`。資料只在 store `reports/arith_stage0_20261020/`；本檔不含題目原文、經文、卡片文字或答案。"
             "王朝的種子 id 是 r4 層 id（括號內是參照層 ref_v2 id），創世記是 store gen_layer.json 的 id。", "",
             "## 1. 題與 gold", ""] + item_rows(items, meta)
    lines += ["", "## 2. 題數、段與旗標", ""] + counts_lines(doc)
    lines += ["", "## 3. SYNC 入選題的答案王分佈", ""] + sync_rows(items)
    lines += ["", "## 4. K0（CPU，叫 Ollama 前）", ""] + k0_lines(k0)
    lines += ["", "F3 回聲案例（K0-4，照 §5 計，不改規則）：", ""] + echo_rows(k0)
    lines += ["", "## 5. 臂與 prompt", ""] + arm_lines(inp["arms_meta.json"])
    lines += ["", "## 6. sha256", ""] + sha_lines(inp) + [""]
    return "\n".join(lines)


# ---------------------------------------------------------------- leak check
def verse_texts(text_dir: Path = X.TEXT):
    for r in X.jsonl(Path(text_dir) / "verse_units.jsonl"):
        yield r["text"]


def windows(s: str, n: int = WINDOW) -> set[str]:
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def leak_problems(text: str, questions: dict[str, str], card_lines, verses, n: int = WINDOW) -> list[str]:
    """Any n-character window of a question or a verse in text, or a whole card line (≥ n chars) in it."""
    w = windows(text, n)
    out = [f"question text of {i}" for i, q in questions.items() if windows(q, n) & w]
    out += [f"card line {ln[:4]}…" for ln in dict.fromkeys(card_lines) if len(ln) >= n and ln in text]
    hits = 0
    for v in verses:
        hits += any(v[i:i + n] in w for i in range(len(v) - n + 1))
    return out + ([f"{hits} verses share an {n}-character window with the appendix"] if hits else [])


def card_lines(cards: dict) -> list[str]:
    out = []
    for cd in cards.values():
        out += cd["g_block"].splitlines() + cd["t_block"].splitlines()
        out += ((cd.get("tcanon") or {}).get("block") or "").splitlines()
    return out


def problems_of(text: str, inp: dict) -> list[str]:
    qs = {it["id"]: it["question"] for it in inp["items.json"]["items"]}
    return leak_problems(text, qs, card_lines(inp["cards.json"]["cards"]), verse_texts())


def write(path: Path = APPENDIX) -> Path:
    """Render from the store build, refuse a leak, write (appendix.md in the repo, or a path outside it)."""
    path = Path(path).resolve()
    if path != APPENDIX.resolve():
        path = X.writable(path)
    inp = R.load_inputs()
    text = render(inp)
    bad = problems_of(text, inp)
    if bad:
        raise SystemExit(f"appendix not written: {bad}")
    path.write_text(text, encoding="utf-8")
    return path


def check(path: Path = APPENDIX) -> list[str]:
    """Problems of the appendix on disk (empty = it is render() of the store build and leaks nothing)."""
    path = Path(path)
    if not path.is_file():
        return [f"{path.name} missing"]
    text, inp = path.read_text(encoding="utf-8"), R.load_inputs()
    out = [] if text == render(inp) else [f"{path.name} is not what appendix_x renders for the store build"]
    return out + problems_of(text, inp)


def main() -> None:
    print(write())


if __name__ == "__main__":
    main()
