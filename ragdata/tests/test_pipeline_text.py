"""The pipeline's text step on six real PDFs: src and text stored, every text gate green."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragdata import stages
from ragdata.gates.runner import REQUIRED_GATES, GateInputs
from ragdata.pipeline.steps import Sources, layer_step
from ragdata.stages.errors import StageError

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FILES = ("路得記", "約拿書", "哈巴谷書", "西番雅書", "以斯拉記", "馬可福音")


def _pdf_dir(root: Path) -> Path:
    root.mkdir()
    for name in FILES:
        (root / f"{name}.pdf").symlink_to(REPO / "bible_pdf" / f"{name}.pdf")
    return root


def test_the_text_step_stores_src_and_text_and_passes_every_text_gate(tmp_path):
    gate = GateInputs(pdf_dir=_pdf_dir(tmp_path / "pdf"),
                      source_expect=HERE / "fixture_source_expect.yaml")
    sources = Sources(gate=gate, counts=HERE / "fixture_counts.yaml",
                      text=stages.TextInputs(diff_expect=HERE / "fixture_diff_expect.yaml"),
                      workers=2)
    step = layer_step("text", tmp_path / "store", sources)
    result = step.build({})
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert set(result.layers) == {"src", "text"}
    report = step.gate(dict(result.layers))
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    assert [g.name for g in report.gates] == list(REQUIRED_GATES["text"])


def test_the_text_step_needs_the_pdfs(tmp_path):
    step = layer_step("text", tmp_path / "store", Sources(gate=GateInputs()))
    with pytest.raises(StageError, match="PDFs"):
        step.build({})
