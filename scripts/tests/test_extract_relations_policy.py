"""Step 6 has no R2 rule path (REL-01, C6b).

R2 looked for a yaml `prompt_signals` keyword within 25 characters of both
names and, at confidence ≥ RE_RULE_CONFIDENCE_FLOOR, wrote the triple without
asking the LLM, its direction being the pair's id order (phase 2: 772 rows in
relations.jsonl, 771 on the prod graph; kinship 3/22 correct on a sample, e.g.
羅得 FATHER_OF 他拉). 6.05's anchored slot rules replace it, so Step 6 sends
every mined candidate to R4. Nothing else read `prompt_signals`, and the floor
only gated R2, so both are gone.
Legacy phase-2 rows in an old relations.jsonl still load (ExtractionPhase
keeps RULE_MATCH) and 6.05 replaces them with anchored rows.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import yaml

from relation_extraction import extract_relations
from relation_extraction.config import REPipelineConfig
from relation_extraction.models import RelationCandidate, RelationSchemaEntry
from relation_extraction.schema_loader import RelationSchema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "config" / "relations" / "biblical_relations.yaml"
PERICOPE = "gen:21:1"


class _Closable:
    def close(self) -> None:
        pass


def _candidate(head: str, tail: str, text: str) -> RelationCandidate:
    return RelationCandidate(
        head_id=f"person:{head}", tail_id=f"person:{tail}", head_type="Person",
        tail_type="Person", head_canonical=head, tail_canonical=tail,
        source_pericope_id=PERICOPE, grounding_text=text)


def _run_step6(monkeypatch, tmp_path, candidates) -> list[list[str]]:
    """main() over `candidates` with no database or LLM; returns the LLM's batches."""
    batches: list[list[str]] = []

    class FakeLLM:
        def __init__(self, cfg):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def classify_batch(self, cands, schema):
            batches.append([c.pair_key for c in cands])
            return []

    for name in ("output", "checkpoint", "unclassified"):
        monkeypatch.setenv(f"RE_{name.upper()}_PATH", str(tmp_path / f"{name}.jsonl"))
    monkeypatch.setenv("RE_SCHEMA_PATH", str(SCHEMA_PATH))
    monkeypatch.setenv("RE_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(extract_relations.GraphDatabase, "driver", lambda *a, **k: _Closable())
    monkeypatch.setattr(extract_relations, "_build_pg_connection", lambda: _Closable())
    monkeypatch.setattr(extract_relations, "mine_pairs", lambda *a, **k: iter(candidates))
    monkeypatch.setattr(extract_relations, "GroundedREClassifier", FakeLLM)
    monkeypatch.setattr(sys, "argv", ["extract_relations", "--no-priors", "--pericope-id", PERICOPE])
    assert extract_relations.main() == 0
    return batches


def test_no_r2_path(monkeypatch, tmp_path):
    for name in ("scripts.relation_extraction.rule_classifier", "relation_extraction.rule_classifier"):
        assert importlib.util.find_spec(name) is None, name
    assert not hasattr(extract_relations, "classify_by_rules")
    # the entity-extraction classifier of the same file name is a different module and stays
    assert importlib.util.find_spec("entity_extraction.rule_classifier") is not None

    # 「亞伯拉罕生以撒」 carries FATHER_OF's old signal 「生」, which R2 took at 0.95
    candidates = [_candidate("亞伯拉罕", "以撒", "亞伯拉罕生以撒"),
                  _candidate("亞比米勒", "非各", "亞比米勒和非各說話")]
    batches = _run_step6(monkeypatch, tmp_path, candidates)

    assert batches == [[c.pair_key for c in candidates]]
    assert (tmp_path / "output.jsonl").read_text(encoding="utf-8") == ""
    unclassified = (tmp_path / "unclassified.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["head_id"] for line in unclassified] == ["person:亞伯拉罕", "person:亞比米勒"]


def test_schema_has_no_prompt_signals():
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "prompt_signals" not in text
    assert "R2" not in text
    data = yaml.safe_load(text)
    assert all("prompt_signals" not in body for body in data["relations"].values())
    assert "prompt_signals" not in {f.name for f in dataclasses.fields(RelationSchemaEntry)}
    schema = RelationSchema.load(SCHEMA_PATH)
    assert len(schema) == 37
    assert not any(hasattr(e, "prompt_signals") for e in schema.iter_entries())


def test_config_has_no_rule_confidence_floor(monkeypatch):
    assert "rule_confidence_floor" not in {f.name for f in dataclasses.fields(REPipelineConfig)}
    monkeypatch.setenv("RE_RULE_CONFIDENCE_FLOOR", "0.85")   # a stale .env line is ignored
    assert not hasattr(REPipelineConfig.from_env(), "rule_confidence_floor")
    assert "RE_RULE_CONFIDENCE_FLOOR" not in (ROOT / ".env.example").read_text(encoding="utf-8")
