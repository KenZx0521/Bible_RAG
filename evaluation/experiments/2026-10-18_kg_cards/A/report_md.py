"""Markdown rendering of the experiment A stage-0 report (store A/report.md)."""
from __future__ import annotations

from pathlib import Path


def f3(x) -> str:
    return "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def fs(x) -> str:
    return "—" if x is None else f"{x:+.3f}"


def pair_rows(pairs: dict) -> list[str]:
    out = ["| 比較 | n | 平均差 | 95% CI | sign-flip p | W:L:T |", "|---|---|---|---|---|---|"]
    for name, c in pairs.items():
        ci = "—" if c["ci95"][0] is None else f"[{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]"
        out.append(f"| {name} | {c['n']} | {fs(c['mean'])} | {ci} | {'—' if c['p_signflip'] is None else f"{c['p_signflip']:.4f}"} | {c['W']}:{c['L']}:{c['T']} |")
    return out


def write_md(rep: dict, path: Path) -> None:
    g, v = rep["gate"], rep["verdict"]
    lines = [f"# 實驗 A stage-0 報告（{rep['label']}）", "",
             f"**結果：{v['result']}**" + (f"（{'；'.join(v.get('stopped_by', []))}）" if v.get("stopped_by") else ""), "",
             *([f"> 作廢原因：{v['why']}", ""] if v.get("why") else []),
             "## K-S0", "",
             f"- G-auto−T-rows 平均 {fs(g['mean_G_auto_minus_T_rows'])}（門檻 +{g['threshold']}）",
             f"- 實測 a={f3(g['a'])}、h={f3(g['h'])}、pR={f3(g['pR'])}、pC={f3(g['pC'])}、gap={fs(g['gap_raw'])}；"
             f"代入（夾到 [0.01, 0.99]）h={f3(g['clamped']['h'])}、pR={f3(g['clamped']['pR'])}、"
             f"pC={f3(g['clamped']['pC'])}、gap={fs(g['clamped']['gap'])}",
             f"- powerA_strong.cell(C=12, m=3, nsim=500)：pow_H1={g['power_cell']['pow_H1']}、"
             f"pow_H1_and_H2={g['power_cell']['pow_H1_and_H2']}（門檻 {g['power_threshold']}）", "",
             "## 各臂平均（題層）", "", "| 子集 | " + " | ".join(rep["arm_means"]["all"]) + " |",
             "|---|" + "---|" * len(rep["arm_means"]["all"])]
    for s, m in rep["arm_means"].items():
        lines.append(f"| {s} | " + " | ".join(f3(x) for x in m.values()) + " |")
    for s, pairs in rep["pairs"].items():
        lines += ["", f"## 配對差（{s}，描述）", ""] + pair_rows(pairs)
    lines += ["", "## 呼叫層", "", "| 臂 | 呼叫數 | 格式失敗 | 截斷 | 陷阱 | 錯答 | 部分 | 附加字數平均 | 最大 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for arm, c in rep["calls"].items():
        a = rep["aux_chars"][arm]
        lines.append(f"| {arm} | {c['n_calls']} | {c['format_fail']} | {c['truncated']} | {c['trap']} | {c['wrong']} | "
                     f"{c['partial']} | {'—' if a['mean'] is None else f"{a['mean']:.1f}"} | {a['max']} |")
    ds = rep["descriptive"]
    lines += ["", "## 描述（不進判定）", "",
              f"- a_strict（只看題目所問那一行）={f3(ds['a_strict'])}，h_strict={f3(ds['h_strict'])}",
              f"- T-canon 窗含全部依據公式節的題 {len(ds['tcanon_basis_covered_items'])}/{rep['n_items']}；"
              f"這些題上 pC={f3(ds['pC_covered'])}、pR={f3(ds['pR_on_tcanon_covered'])}",
              f"- 種子截斷：{ds['seed_truncated'] or '無'}；種子解析不到：{ds['seed_no_parse'] or '無'}"]
    lines += ["", f"- G-auto 棄權題：{rep['g_auto_abstain'] or '無'}；G-ref 棄權題：{rep['g_ref_abstain'] or '無'}",
              f"- 缺漏 job：{len(rep['missing_jobs'])}；num_ctx：{rep['num_ctx']}",
              "- 措辭依 prereg §4：不寫「圖譜有效」或「圖譜無效」。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
