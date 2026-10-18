"""Markdown rendering of the confirmation-set report (store A_confirm/report.md). Numbers only, no text of
questions, answers or scripture; the verdict sentence is report.json verdict.wording verbatim."""
from __future__ import annotations

from pathlib import Path


def f3(x) -> str:
    return "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def fs(x) -> str:
    return "—" if x is None else f"{x:+.3f}"


def ci(c) -> str:
    return "—" if not c or c[0] is None else f"[{c[0]:+.3f}, {c[1]:+.3f}]"


def fp(t: dict) -> str:
    if "p" not in t:
        return "未檢定"
    return "—" if t["p"] is None else f"{t['p']:.5f}" + ("（精確）" if t.get("exact") else "")


def test_rows(tests: dict) -> list[str]:
    out = ["| 比較 | 單位 n | Δ̄ | 95% CI | sign-flip p | W:L:T |", "|---|---|---|---|---|---|"]
    for nm, t in tests.items():
        if not isinstance(t, dict) or "delta" not in t:
            continue
        out.append(f"| {nm} | {t['n_units']} | {fs(t['delta'])} | {ci(t['ci95'])} | {fp(t)} | {t['W']}:{t['L']}:{t['T']} |")
    return out


def verdict_lines(rep: dict) -> list[str]:
    v = rep["verdict"]
    lines = [f"**判定：{v['result']}**", "", f"> {v['wording']}", ""]
    if v.get("why"):
        lines += [f"- 作廢原因：{v['why']}", ""]
    if v.get("all_stops"):
        lines += [f"- 停止條目：{'、'.join(s['rule'] for s in v['all_stops'])}", ""]
    lines += [f"- 記錄：{n}" for n in v.get("notes") or []]
    if v.get("k3_wording"):
        lines.append(f"- K3：{v['k3_wording']}")
    return lines + [""]


def seq_lines(rep: dict) -> list[str]:
    s = rep["sequence"]
    lines = ["## 主檢定（固定序列，FWER 0.05；過關＝p<0.05 且 Δ̄≥+0.10）", ""] + test_rows(
        {f"H1 {s['H1']['pair']}": s["H1"], f"H2 {s['H2']['pair']}": s["H2"]})
    lines += ["", f"- H1 過關：{s['H1']['pass']}；H2 {'過關：' + str(s['H2']['pass']) if s['H2']['tested'] else '未檢定（H1 未過，不報 p）'}"]
    k = rep["k3"]
    lines += ["", "## K3（傷害）", "",
              f"- 錯答率 G-auto（含替補）{f3(k['rate']['G-auto'])}、T-canon {f3(k['rate']['T-canon'])}；差 {fs(k['diff'])}"
              f"（門檻 +{k['threshold']}）；單位 Δ̄ {fs(k['unit_delta'])}、95% CI {ci(k['unit_ci95'])}"]
    return lines


def desc_lines(rep: dict) -> list[str]:
    ds = rep["descriptive"]
    lines = ["", "## 描述（不進判定；p 只當描述）", "", "### 單位層配對差", ""] + test_rows(ds["pairs_desc"])
    lines += ["", "### 題層級（不群聚）", "", "| 比較 | n | 平均差 | 95% CI | sign-flip p | W:L:T |", "|---|---|---|---|---|---|"]
    for nm, c in rep["item_level"].items():
        p = "未檢定" if "p_signflip" not in c else "—" if c["p_signflip"] is None else f"{c['p_signflip']:.4f}"
        lines.append(f"| {nm} | {c['n']} | {fs(c['mean'])} | {ci(c['ci95'])} | {p} | {c['W']}:{c['L']}:{c['T']} |")
    lines += ["", "### 分層（H1、H2 配對）", ""]
    for label, t in ds["strata"].items():
        lines += [f"- {label}（{t['n_items']} 題）"] + ["  " + x for x in test_rows({k: v for k, v in t.items()
                                                                                  if k != "n_items"})]
    lines += ["", "### 陷阱規則敏感度", ""]
    for rule, t in ds["trap_rule_sensitivity"].items():
        lines += [f"- {rule}（陷阱次數 {t['trap_calls']}）"] + ["  " + x for x in test_rows(
            {k: v for k, v in t.items() if k != "trap_calls"})]
    return lines


def call_lines(rep: dict) -> list[str]:
    lines = ["", "## 呼叫層", "", "| 臂 | 呼叫數 | 格式失敗 | 截斷 | 陷阱 | 錯答 | 錯答率 | 猶豫答案 | 附加字數平均 | 最大 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    hes = rep["descriptive"]["hesitation"]
    for arm, c in rep["calls"].items():
        a = rep["aux_chars"][arm]
        lines.append(f"| {arm} | {c['n_calls']} | {c['format_fail']} | {c['truncated']} | {c['trap']} | {c['wrong']} | "
                     f"{f3(c['wrong_rate'])} | {hes[arm]['hesitant']}/{hes[arm]['calls']} | "
                     f"{'—' if a['mean'] is None else f'{a['mean']:.1f}'} | {a['max']} |")
    return lines


def misc_lines(rep: dict) -> list[str]:
    ds, sd, pw = rep["descriptive"], rep["descriptive"]["seeds_desc"], rep["power_disclosure"]
    lines = ["", "## 其他描述", "",
             f"- 各臂題層平均：{'、'.join(f'{a} {f3(x)}' for a, x in rep['arm_means'].items())}",
             f"- 種子：gemma 與 gold 解析一致率 {f3(sd['gemma_gold_agree'])}；a＝{f3(sd['a'])}；"
             f"K1 型 a（gold 種子）＝{f3(sd['a_gold_seeds'])}；h＝{f3(sd['h'])}；pR＝{f3(sd['pR'])}；pC＝{f3(sd['pC'])}",
             f"- 種子解析不到（G-auto）：{sd['seed_unresolved_auto'] or '無'}；種子截斷：{ds['seed_truncated'] or '無'}",
             f"- a_strict＝{f3(ds['a_strict'])}；T-canon 窗含齊依據公式節 {len(ds['tcanon_basis_covered_items'])}/{rep['n_items']} 題，"
             f"其上 pC＝{f3(ds['pC_covered'])}、pR＝{f3(ds['pR_on_tcanon_covered'])}",
             f"- G-auto 棄權題：{rep['g_auto_abstain'] or '無'}；G-ref 棄權題：{rep['g_ref_abstain'] or '無'}",
             f"- 交界王題 {len(ds['boundary_king_items'])}；與開發題（種子, 答案）重疊 {len(ds['stage0_overlap_items'])}",
             f"- 檢定力揭露：FP 表 {pw['fp_table']}；本案 C＝{pw['C']}、m 平均 {pw['m_mean']}；3 次生成不獨立，檢定以單位為準",
             f"- K1：{rep['k1'].get('wording') or '—'}；缺漏 job：{len(rep['missing_jobs'])}；num_ctx：{rep['num_ctx']}",
             f"- prepare 後的程式修改（只限基礎設施；inputs_manifest.json code_changes）：{len(rep.get('code_changes') or [])} 次"]
    lines += [f"  - {c['t']}：{'、'.join(c['files'])}；{c['note']}" for c in rep.get("code_changes") or []]
    return lines + ["- 不寫「圖譜有效」或「圖譜無效」；論文不動。", ""]


def write_md(rep: dict, path: Path) -> None:
    lines = [f"# 實驗 A 確認集報告（{rep['label']}，{rep['n_items']} 題、{rep['n_units']} 單位）", ""]
    lines += verdict_lines(rep) + seq_lines(rep) + desc_lines(rep) + call_lines(rep) + misc_lines(rep)
    Path(path).write_text("\n".join(lines), encoding="utf-8")
