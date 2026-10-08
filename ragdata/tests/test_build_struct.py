"""``build_struct``: S5 over a stored text layer, its gates, the store, and G-DET."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_build
from ragdata import stages, store
from ragdata.gates import check_det
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct.build import StructInputs, build_struct
from ragdata.stages.s05_struct.tokens import TokenCounter

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
MINI = TokenCounter(mini_build.count_tokens, {"tokenizer": "mini"})


def _legacy(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in (("pericopes.jsonl", mini_build.legacy_pericopes()),
                       ("chunks.jsonl", mini_build.legacy_chunks())):
        (directory / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                              for r in rows), encoding="utf-8")
    return directory


def _build(tmp: Path, text_dir: Path, store_dir: str = "store", counts: Path = MINI_COUNTS):
    inputs = StructInputs(legacy_dir=_legacy(tmp / "legacy"), counter=MINI)
    return build_struct(text_dir, tmp / store_dir, counts_path=counts, inputs=inputs)


def test_build_stores_the_hand_built_struct_layer_on_its_text_layer(tmp_path):
    text, _ = mini_build.write_layers(tmp_path / "given")
    result = _build(tmp_path, text.path)
    assert result.passed, [g.to_json() for g in result.gates if not g.passed]
    assert [g.name for g in result.gates] == ["G-SCHEMA", "G-COUNT", "G-REFINT", "G-STRUCT"]
    built = store.read_layer(result.layers["struct"].path)
    assert built.depends_on == {"text": text.version}
    assert {name: list(rows) for name, rows in built.rows.items()} == mini_build.files("struct")
    report = json.loads((built.path / "struct_report.json").read_text(encoding="utf-8"))
    assert report["text_layer"] == text.version and report["template_id"] == "v1c"
    assert report["legacy_relations"]["pericope"] == {"contained": 1, "exact": 6}
    assert set(report["legacy_inputs"]) == {"pericopes.jsonl", "chunks.jsonl"}


def test_two_builds_write_identical_files(tmp_path):
    text, _ = mini_build.write_layers(tmp_path / "given")
    first, second = _build(tmp_path, text.path, "a"), _build(tmp_path, text.path, "b")
    result = check_det(first.layers["struct"].path, second.layers["struct"].path)
    assert result.passed and first.layers["struct"].version == second.layers["struct"].version


def test_a_red_build_stores_nothing(tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text(MINI_COUNTS.read_text(encoding="utf-8").replace(
        "pericopes: {value: 6,", "pericopes: {value: 7,"), encoding="utf-8")
    text, _ = mini_build.write_layers(tmp_path / "given")
    result = _build(tmp_path, text.path, counts=counts)
    assert not result.passed and result.layers == {}
    assert not (tmp_path / "store").exists()


def test_the_text_dependency_must_be_a_sound_text_layer(tmp_path):
    text, struct = mini_build.write_layers(tmp_path / "given")
    with pytest.raises(StageError, match="struct layer"):
        _build(tmp_path, struct.path)
    rows = mini_build.text_layer()
    rows["verse_units"][0]["label"] = "9"
    broken, _ = mini_build.write_layers(tmp_path / "broken", text=rows)
    with pytest.raises(StageError, match="G-SCHEMA"):
        _build(tmp_path, broken.path)


def test_build_refuses_any_layer_but_text(tmp_path):
    with pytest.raises(ValueError, match="build_struct"):
        stages.build("struct", tmp_path, tmp_path / "store")
