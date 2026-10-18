"""Writes repo A/appendix_A.md from the store files (items, layer check, dry run). The appendix holds
item ids, template texts, keys and verse ids only: no verse text, no natural-question text, no TIPNR."""
from __future__ import annotations

from a_common import HERE, ITEMS, LAYER_AUTO, LAYER_REF, MANIFEST, OUT, read_json, sha256_file
from appendix_text import ALIAS_RULE, ARMS_SPEC, CORRECTIONS, GUARDS, READINGS, SCORE_SPEC


def keys_cell(k: dict) -> str:
    if k["type"] == "number":
        return f"數字 {k['value']}（單位 {k['unit'].replace('|', '／')}）"
    s = f"{'名' if k['type'] == 'name' else '詞'} {'／'.join(k['accept'])}"
    return s + ("（排除方向相反或否定）" if k.get("reject") else "")


def item_rows(items) -> list[str]:
    out = ["| 題號 | 類 | 題目（模板題才列） | 國別 | 種子（參照層） | 鍵（可接受寫法） | 依據經節 | 基底 context |",
           "|---|---|---|---|---|---|---|---|"]
    for it in items:
        q = it["question"] if it["kind"] != "natural" else "（自然題，原題見 store items.json）"
        keys = "；".join(keys_cell(k) for k in it["keys"])
        basis = "；".join(",".join(k["basis"]) for k in it["keys"])
        ctx = ",".join(s["id"] for s in it["sources"])
        out.append(f"| {it['id']} | {it['kind']} | {q} | {it['kingdom']} | {','.join(it['seeds'])} | {keys} | {basis} | {ctx} |")
    return out


def layer_lines(chk: dict) -> list[str]:
    a = chk["alias_vs_ref"]
    return ["## A.1 層", "",
            f"- G-auto：`layer_auto.json` sha256 `{sha256_file(LAYER_AUTO)}`（`layer_check.py`）。",
            f"- G-ref：`ref_layer.json` sha256 `{sha256_file(LAYER_REF)}`（K/probe_C5/ref_layer.json 原檔複製）。",
            "- fn_rule=probe 重建與 K/probe_C5/auto_layer_occ.json 逐欄相同："
            f"{'是' if not chk['probe_rule_vs_probe_file']['differing_keys'] else chk['probe_rule_vs_probe_file']['differing_keys']}。",
            f"- 改用下列別名規則後，只有 nodes（別名）、log、occ_alias 不同；邊、同步、欄位衝突相同："
            f"{chk['slot_rule_vs_probe_file']['same_edges_syncs_fields']}；別名變動 {chk['slot_rule_vs_probe_file']['node_alias_changes']}。",
            "", "## A.2 別名修正規則（K0-2，寫死，不看題目）", "", ALIAS_RULE, "",
            f"- 對照參照層：探針 occ 綁定 {a['probe_file']['n_bind']} 筆、錯綁 {a['probe_file']['n_wrong_bind']}；"
            f"本規則綁定 {a['slot_rule']['n_bind']} 筆、錯綁 {a['slot_rule']['n_wrong_bind']}、拒絕 {len(a['slot_rule']['rejected'])} 筆"
            f"（{', '.join(r[0] for r in a['slot_rule']['rejected'])}）；節點別名 {a['slot_rule']['n_node_alias']} 個、"
            f"錯 {a['slot_rule']['n_wrong_node_alias']} 個。",
            "- 這條規則是在看過探針 7 筆綁定之後寫的（prereg 要求以寫死的規則修到 0）；寫成後才建題與 prompt。", ""]


def item_lines(doc: dict) -> list[str]:
    items = doc["items"]
    notes = [f"- {it['id']}：{it['note']}；豁免（walk 路徑）{','.join(it['path'])}" for it in items if it["kind"] == "natural"]
    flagged = [f"- {it['id']}：{'；'.join(it['flags'])}" for it in items if it.get("flags")]
    return (["## A.3 題與答案鍵（dev 30）", "",
             f"抽樣：random.Random({doc['seed']})；S1 候選 {doc['draw']['n_s1']}、S4 候選（steps_back≥2、"
             f"決定）{doc['draw']['n_s4']}；S1 補題 {doc['draw']['s1_topup']}。", ""] + item_rows(items)
            + ["", "自然題鍵的依據（dev_eval Q 表，K0 更正後）：", ""] + notes
            + ["", "模板題旗標：" + ("無" if not flagged else ""), ""] + flagged
            + ["", "- 基底 context：OLD31 用 MH/realkg/inputs_nogold.json 的 dk_sources（prod 回傳的 context 去標頭）；"
               "NEW82 用 graph_qd lanes.json 的 C5＋QD rep1 pid，模板題用參照層登基節（主同步節，否則登基歲數、繼位、"
               "開國、在位節）所在的 struct passage（pc:2ki.23.35 跨章有 2 個 passage，取含登基節的那個）。"
               "struct passages 與 realkg dk_sources 的 prod 內容逐字相同（314/316，另 2 個只差 title None／空字串）。",
               "- 提比尼（王上 16:21–22）不算王：參照鏈心利→暗利；K0 gold 核對逐題確認（T_S1_13）。", ""])


def dry_lines(dry: dict) -> list[str]:
    st = dry["scorer_selftest"]
    return ["## A.7 Prompt 與 job（dry-run，gold 種子，未呼叫 Ollama）", "",
            f"- 種子 system sha256 `{dry['sha256']['seed_system']}`；種子 user 模板 `{dry['sha256']['seed_user_template']}`。",
            f"- 生成 system（cards_common.SYSTEM_PROMPT）`{dry['sha256']['system_prompt']}`；user 模板 `{dry['sha256']['user_template']}`。",
            f"- 全部 seed prompt 合併 sha256 `{dry['sha256']['seed_prompts']}`；全部 stage-2 prompt "
            f"`{dry['sha256']['arm_prompts']}`（逐 job 見 store dry_run/prompt_sha256.tsv）。正式跑的 seed prompt 與 dry-run 相同；"
            "stage-2 prompt 取決於 gemma 的種子輸出，B0 與 dry-run 相同。",
            f"- job 數：seed {dry['n_seed_jobs']}；stage-2 {dry['n_arm_jobs']}（{dry['arm_jobs_by_arm']}，gold 種子下無棄權），"
            f"共 {dry['n_jobs_total']}。正式跑的 stage-2 數＝270 減棄權。",
            f"- 附加字數（平均, 最大）：{ {k: (v['mean'], v['max']) for k, v in dry['aux_chars'].items()} }；"
            f"user prompt 最大 {dry['user_chars_max_all']} 字。",
            f"- gold 種子下 a_hit {len(dry['a_hit_gold_seeds'])}/30、a_strict {len(dry['a_strict_gold_seeds'])}/30；"
            f"T-canon 窗缺依據公式節 {len(dry['tcanon_basis_missing'])}/30 題（{', '.join(dry['tcanon_basis_missing'])}）。",
            f"- 計分自測（selftest_a.py，合成答案）：{st['ok']}/{st['n']} 符合本附錄規則；各類 {st['by_case']}。",
            f"- code sha256 見 store `{MANIFEST.name}`。", ""]


def main() -> None:
    doc, chk = read_json(ITEMS), read_json(OUT / "layer_check.json")
    dry = read_json(OUT / "dry_run/summary.json")
    lines = ["# 附錄 A：王朝年表推導卡 stage-0（2026-10-18，harness 建置時寫入，尚無任何臂的生成）", "",
             "規格：`../prereg.md` §1、§2。資料只在 store `reports/kg_cards_20261018/A/`；本檔不含經文與自然題原文。", ""]
    lines += layer_lines(chk) + item_lines(doc)
    lines += ["## A.4 臂", "", ARMS_SPEC, "", "## A.5 計分與 K-S0 輸入", "", SCORE_SPEC, "",
              "## A.6 執行防呆", "", GUARDS, ""] + dry_lines(dry)
    lines += ["## A.8 K0 檔（store A/）", "",
              "- `k0_fields_sample.json`：G-auto 40 欄（Random(20261018)，母體＝臂上顯示的欄），附出處節與經文；門檻精確率 ≥0.95。",
              "- `k0_gold_check.json`：30 題的鍵、gold、依據節與經文（自然題附原題答案或 key_points）。",
              "- `layer_check.json`：K0-2 別名核對；`dry_run/summary.json`：附加字數、prompt 字數、job 數、計分自測。", "",
              "## A.9 對 prereg 字面的解讀與補充（生成前寫定，請 Kay 確認）", "", READINGS, "",
              "## A.10 更正紀錄（harness 建置後、任何生成前）", "", CORRECTIONS, ""]
    (HERE / "appendix_A.md").write_text("\n".join(lines), encoding="utf-8")
    print(HERE / "appendix_A.md")


if __name__ == "__main__":
    main()
