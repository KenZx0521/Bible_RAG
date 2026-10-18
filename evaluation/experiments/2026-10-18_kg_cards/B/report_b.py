"""report.md for experiment B stage-0 (store only; wording fixed by prereg §4)."""
from __future__ import annotations

ARM_NAME = {"G": "G", "T1C": "T-1hop+CoT", "TLLM": "T-LLM", "B0": "B0", "GO": "G-oracle（理想上限）"}


def _f(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def _cmp_rows(block: dict) -> list[str]:
    rows = ["| 比較 | n | 平均差 | 題層 95% CI | 題層 p | 群聚 95% CI | 群聚 p | 勝:負 |",
            "|---|---|---|---|---|---|---|---|"]
    for name, c in block.items():
        if c.get("mean") is None:
            rows.append(f"| {name} | {c['n']} | — | — | — | — | — | — |")
            continue
        rows.append(f"| {name} | {c['n']} | {_f(c['mean'])} | [{_f(c['ci_item'][0])}, {_f(c['ci_item'][1])}] | "
                    f"{_f(c['p_item'])} | [{_f(c['ci_cluster'][0])}, {_f(c['ci_cluster'][1])}] | "
                    f"{_f(c['p_cluster'])} | {c['wins']}:{c['losses']} |")
    return rows


def render(rep: dict) -> str:
    k, d = rep["ks0"], rep["describe"]
    lines = [f"# 實驗 B stage-0 報告（{rep['label']}）", "",
             f"**判定：{rep['verdict']}**" + (f"（{rep['verdict_detail']}）" if rep["verdict_detail"] else ""), "",
             "## K-S0（prereg §3，任一成立就停）", "",
             "| 條 | 實測 | 門檻 | 成立 |", "|---|---|---|---|",
             f"| 1 pT（T-LLM 平均） | {_f(k['pT'])} | ≥0.65 | {k['rules']['1_pT_ge_0.65']} |",
             f"| 2 分散題 T-1hop+CoT 平均 vs 卡片答對率（n={k['n_dispersed']}） | {_f(k['T1C_dispersed'])} vs "
             f"{_f(k['card_rate_dispersed'])} | T ≥ 卡−0.05 | {k['rules']['2_dispersed_T1C_ge_card_minus_0.05']} |",
             f"| 3 G（棄權取 B0）vs B0 | {_f(k['G_vs_B0'])} vs {_f(k['B0'])} | G ≤ B0 | {k['rules']['3_G_le_B0']} |",
             f"| 4 IUT 檢定力 | {_f(k['power_iut'])} | <0.7 | {k['rules']['4_power_lt_0.7']} |", "",
             f"代入值：pT={_f(k['pT'])}、出手率={_f(k['fire_rate'])}（{k['n_fired']}/48）、a={_f(k['a'], 4)}、"
             f"prec={_f(k['prec'])}、adh={_f(k['adh'])}、r={_f(k['r'])}；gen(32, 4, pT, a, adh, r, prec, 3)，300 次。", "",
             "## 描述（不進判定）", "", "### 全部 48 題（G 棄權題取比較臂自己的分數）", ""]
    lines += _cmp_rows(d["all"]) + ["", "### 只看出手題", ""] + _cmp_rows(d["fired"])
    lines += ["", f"### 同鏈去重（每條 gold 鏈留一題；群聚數 {d['n_clusters']}）", ""] + _cmp_rows(d["chain_dedup"])
    lines += ["", "### 分散題的其他讀法（K-S0 第 2 條，只描述）", "", "| 集合 | n | T-1hop+CoT | 卡片答對率 |",
              "|---|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {_f(v['T1C'])} | {_f(v['card_ok'])} |" for k, v in d["dispersed_variants"].items()]
    lines += ["", "### 計分變體（只描述，不進判定）", "", "| 臂 | n | 答對（prereg） | 陷阱只看第一子句 | 只靠括號內詞答對 |",
              "|---|---|---|---|---|"]
    lines += [f"| {ARM_NAME[a]} | {v['n']} | {_f(v['ok'])} | {_f(v['ok_first_clause'])} | {v['ok_only_in_parens']} |"
              for a, v in d["score_variants"].items()]
    lines += ["", "### 兩段式臂的階段 1 槽位", "", "| 臂 | n | 平均非空行 | 平均字數 | 超過 6 行 | 超過字數上限 |",
              "|---|---|---|---|---|---|"]
    lines += [f"| {ARM_NAME[a]} | {v['n']} | {_f(v['lines_mean'], 1)} | {_f(v['chars_mean'], 0)} | {v['cut_lines']} | "
              f"{v['cut_chars']} |" for a, v in d["slots"].items()]
    lines += ["", "### G-oracle − G（兩張卡都出手的題）", ""]
    lines += _cmp_rows({"GO-G": d["oracle_minus_G_both_fired"]})
    lines += ["", "### 依題型", "", "| 題型 | n | " + " | ".join(ARM_NAME[a] for a in ARM_NAME) + " |",
              "|---|---|" + "---|" * len(ARM_NAME)]
    for s, row in d["by_stratum"].items():
        lines.append(f"| {s} | {row['n']} | " + " | ".join(
            f"{_f(row[a]['mean'], 2)} (n={row[a]['n']})" for a in ARM_NAME) + " |")
    lines += ["", "### 各臂附加字數（user prompt 減 B0）", "", "| 臂 | n | 平均 | 最大 |", "|---|---|---|---|"]
    for a, x in d["aux_chars"].items():
        lines.append(f"| {ARM_NAME[a]} | {x['n']} | {_f(x['mean'], 0)} | {x['max'] if x['max'] is not None else '—'} |")
    lines += ["", f"- 卡片棄權原因：{d['abstain_reasons']}", f"- gold 鏈版面：{d['layout']}",
              f"- 查表層（卡片路徑只有 1 條邊）：{d['lookup_layer_items'] or '無'}",
              f"- 各臂失敗原因：{d['fail_why']}", f"- 沒有結果的 job：{rep['n_missing']}；ctx_len={rep['ctx_len']}",
              "", "措辭依 prereg §4：不寫「圖譜有效」，也不寫「圖譜無效」。"]
    return "\n".join(lines) + "\n"
