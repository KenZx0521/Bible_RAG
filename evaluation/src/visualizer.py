"""
Generate an interactive HTML dashboard from evaluation results.

Uses Plotly for charts and Jinja2 for templating.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from jinja2 import Environment, FileSystemLoader
from rich.console import Console

from .config import settings
from .models import AggregatedReport

console = Console()

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

# Metric groupings for display
RETRIEVAL_METRICS = [
    "precision_at_k", "recall_at_k", "f1_at_k", "mrr", "map_at_k", "ndcg_at_k", "hit_rate"
]
LLM_JUDGE_METRICS = [
    "ragas_faithfulness", "ragas_answer_relevancy",
    "ragas_context_recall", "ragas_answer_correctness",
]
SEMANTIC_METRICS = ["semantic_similarity"]

QUESTION_TYPES = [
    "VERSE_LOOKUP", "TOPIC_QUESTION", "PERSON_QUESTION",
    "EVENT_QUESTION", "GENERAL_BIBLE_QUESTION",
]

QUESTION_TYPE_LABELS = {
    "VERSE_LOOKUP": "經文查詢",
    "TOPIC_QUESTION": "主題問題",
    "PERSON_QUESTION": "人物問題",
    "EVENT_QUESTION": "事件問題",
    "GENERAL_BIBLE_QUESTION": "綜合問題",
}


def _make_radar_chart(report: AggregatedReport) -> str:
    """Create a radar chart showing 3 category averages."""
    categories = ["檢索效能", "LLM 評估", "語意相似度"]

    def _avg(names: list[str]) -> float:
        vals = [report.overall.get(n, 0.0) for n in names if n in report.overall]
        return sum(vals) / len(vals) if vals else 0.0

    values = [
        _avg(RETRIEVAL_METRICS),
        _avg(LLM_JUDGE_METRICS),
        _avg(SEMANTIC_METRICS),
    ]
    values.append(values[0])  # close the radar
    cats = categories + [categories[0]]

    fig = go.Figure(go.Scatterpolar(
        r=values, theta=cats, fill="toself",
        name="Overall", line=dict(color="#636EFA"),
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        title="總覽：四大類指標平均",
        height=450,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _make_retrieval_bar(report: AggregatedReport) -> str:
    """Grouped bar chart: retrieval metrics by question type."""
    rows = []
    for qtype in QUESTION_TYPES:
        if qtype not in report.by_type:
            continue
        label = QUESTION_TYPE_LABELS.get(qtype, qtype)
        for metric in RETRIEVAL_METRICS:
            val = report.by_type[qtype].get(metric, 0.0)
            rows.append({"Question Type": label, "Metric": metric, "Value": val})
    # Overall
    for metric in RETRIEVAL_METRICS:
        rows.append({
            "Question Type": "總體",
            "Metric": metric,
            "Value": report.overall.get(metric, 0.0),
        })

    df = pd.DataFrame(rows)
    fig = px.bar(
        df, x="Metric", y="Value", color="Question Type",
        barmode="group", title="檢索效能指標 (by Question Type)",
        height=500,
    )
    fig.update_yaxes(range=[0, 1])
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _make_generation_bar(report: AggregatedReport) -> str:
    """Bar chart for generation quality metrics."""
    gen_metrics = [
        "ragas_faithfulness", "ragas_answer_relevancy", "ragas_answer_correctness",
        "semantic_similarity",
    ]
    rows = []
    for qtype in QUESTION_TYPES:
        if qtype not in report.by_type:
            continue
        label = QUESTION_TYPE_LABELS.get(qtype, qtype)
        for metric in gen_metrics:
            val = report.by_type[qtype].get(metric, 0.0)
            rows.append({"Question Type": label, "Metric": metric, "Value": val})
    # Overall
    for metric in gen_metrics:
        rows.append({
            "Question Type": "總體",
            "Metric": metric,
            "Value": report.overall.get(metric, 0.0),
        })

    df = pd.DataFrame(rows)
    fig = px.bar(
        df, x="Metric", y="Value", color="Question Type",
        barmode="group", title="生成品質指標",
        height=500,
    )
    fig.update_yaxes(range=[0, 1])
    fig.update_xaxes(tickangle=45)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _make_context_bar(report: AggregatedReport) -> str:
    """Bar chart for context-related metrics."""
    ctx_metrics = [
        "ragas_context_recall",
    ]
    rows = []
    for qtype in QUESTION_TYPES:
        if qtype not in report.by_type:
            continue
        label = QUESTION_TYPE_LABELS.get(qtype, qtype)
        for metric in ctx_metrics:
            val = report.by_type[qtype].get(metric, 0.0)
            rows.append({"Question Type": label, "Metric": metric, "Value": val})
    # Overall
    for metric in ctx_metrics:
        rows.append({
            "Question Type": "總體",
            "Metric": metric,
            "Value": report.overall.get(metric, 0.0),
        })

    df = pd.DataFrame(rows)
    fig = px.bar(
        df, x="Metric", y="Value", color="Question Type",
        barmode="group", title="Context 相關指標",
        height=450,
    )
    fig.update_yaxes(range=[0, 1])
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _make_heatmap(report: AggregatedReport) -> str:
    """Heatmap: question types vs all metrics."""
    all_metrics = sorted(report.overall.keys())
    qtypes = [qt for qt in QUESTION_TYPES if qt in report.by_type]
    labels = [QUESTION_TYPE_LABELS.get(qt, qt) for qt in qtypes]

    z = []
    for qt in qtypes:
        row = [report.by_type[qt].get(m, 0.0) for m in all_metrics]
        z.append(row)

    fig = go.Figure(go.Heatmap(
        z=z, x=all_metrics, y=labels,
        colorscale="RdYlGn", zmin=0, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in z],
        texttemplate="%{text}",
    ))
    fig.update_layout(
        title="問題類型 × 指標 熱力圖",
        height=400,
        xaxis=dict(tickangle=45),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _make_question_detail_table(report: AggregatedReport) -> list[dict]:
    """Build a detail row for every question, sorted by avg_score ascending."""
    KEY_COLS = [
        "hit_rate", "ragas_faithfulness", "ragas_answer_relevancy",
        "ragas_context_recall", "semantic_similarity",
    ]
    rows = []
    for sample in report.samples:
        metric_map = {m.name: m.value for m in sample.metrics}
        has_answer = any(m.name == "hit_rate" for m in sample.metrics)
        avg = (
            round(sum(m.value for m in sample.metrics) / len(sample.metrics), 4)
            if sample.metrics else 0.0
        )
        row = {
            "question_id": sample.question_id,
            "question_type": sample.question_type,
            "route_used": sample.route_used or "-",
            "strategies_used": ", ".join(sample.strategies_used) if sample.strategies_used else "-",
            "status": "success" if has_answer else "fail",
            "avg_score": avg,
        }
        for col in KEY_COLS:
            row[col] = metric_map.get(col)
        rows.append(row)

    type_order = {qt: i for i, qt in enumerate(QUESTION_TYPES)}
    rows.sort(key=lambda x: (type_order.get(x["question_type"], 999), x["question_id"]))
    return rows


def _make_metric_cards(report: AggregatedReport) -> list[dict]:
    """Build key metric cards for the summary section."""
    key_metrics = [
        ("hit_rate", "Hit Rate", "檢索命中率"),
        ("mrr", "MRR", "平均倒數排名"),
        ("ndcg_at_k", "NDCG@k", "歸一化折損累積增益"),
        ("ragas_faithfulness", "Faithfulness", "回答忠實度"),
        ("ragas_answer_relevancy", "Answer Relevancy", "回答相關性"),
        ("ragas_context_recall", "Context Recall", "Context 召回率"),
        ("ragas_answer_correctness", "Answer Correctness", "綜合正確性"),
        ("semantic_similarity", "Similarity", "語意相似度"),
    ]
    cards = []
    for key, title, desc in key_metrics:
        val = report.overall.get(key, 0.0)
        cards.append({"title": title, "desc": desc, "value": f"{val:.2%}"})
    return cards


def generate_dashboard(report: AggregatedReport) -> Path:
    """Generate the interactive HTML dashboard."""
    console.print("[bold]Generating dashboard...[/bold]")

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("dashboard.html.j2")

    # Generate all chart HTML
    charts = {
        "radar": _make_radar_chart(report),
        "retrieval_bar": _make_retrieval_bar(report),
        "generation_bar": _make_generation_bar(report),
        "context_bar": _make_context_bar(report),
        "heatmap": _make_heatmap(report),
    }

    cards = _make_metric_cards(report)
    question_details = _make_question_detail_table(report)

    html = template.render(
        charts=charts,
        cards=cards,
        question_details=question_details,
        overall=report.overall,
        by_type=report.by_type,
        type_labels=QUESTION_TYPE_LABELS,
    )

    results_dir = settings.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")

    console.print(f"[bold green]Dashboard saved to {out_path}[/bold green]")
    return out_path
