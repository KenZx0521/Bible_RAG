"""Step 6.05 relation post-processing (relation_postprocess): the skeleton.

6.05 sits between relation extraction (Step 6) and the relation import (6.1).
It reads output/relations.jsonl and the entity layer, runs the cleanup rules
offline (no database), and writes output/relations_clean.jsonl plus a report
that predicts the edge set the graph holds once 10.2 has deleted the generic
Event nodes. The rules land one commit each (1A-C4b..C4j); this file pins the
contract they plug into:

- `--rules none` runs no rule: every input row comes out with only the base
  stamp (source, schema_version, pp_version) added. It is the K8 staging-P1
  control, so it must project back onto the input rows exactly.
- The output is a pure function of the inputs: rows sorted by key, no
  timestamps, byte-identical across hash seeds.
- An endpoint missing from entities.jsonl stops the run before anything is
  written.
- pp_version hashes every file whose change could change the output, and the
  report records the sha256 of every input.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from relation_extraction import relation_postprocess as pp
from relation_extraction.relation_policy import SOURCE_RANK, parent_child, rank, source_of

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relation_postprocess"
FILES = {"relations": "relations.jsonl", "entities": "entities.jsonl",
         "mentions": "entity_mentions.jsonl", "chunks": "chunks.jsonl", "pericopes": "pericopes.jsonl"}
STAMP = {"source", "schema_version", "pp_version"}
SCHEMA_VERSION = str(yaml.safe_load((ROOT / "config/relations/biblical_relations.yaml")
                                    .read_text(encoding="utf-8"))["version"])


def _paths(directory: Path = FIXTURE) -> dict[str, Path]:
    return {**pp.default_paths(), **{name: directory / file for name, file in FILES.items()}}


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _run(rules: str = "none", paths: dict | None = None) -> tuple[list[dict], dict]:
    inputs, cfg = pp.load_inputs(paths or _paths())
    return pp.postprocess(inputs, cfg, rules)


def _cli(tmp_path: Path, *args: str, seed: str = "0", paths: dict | None = None):
    """Run 6.05 as the rebuild chain does (-m from the repo root); (process, out, report)."""
    out, report = tmp_path / "out" / "relations_clean.jsonl", tmp_path / "out" / "relations_clean.report.json"
    argv = [sys.executable, "-m", "scripts.relation_extraction.relation_postprocess"]
    for name, path in (paths or _paths()).items():
        argv += [f"--{name.replace('_', '-')}", str(path)]
    argv += ["--out", str(out), "--report", str(report), *args]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=300,
                          env={**os.environ, "PYTHONHASHSEED": seed})
    return proc, out, report


def _canon(row: dict, drop: set[str] = frozenset()) -> str:
    return json.dumps({k: v for k, v in row.items() if k not in drop}, sort_keys=True, ensure_ascii=False)


# --- none mode ----------------------------------------------------------------

def test_none_mode_projects_back_to_input_rows():
    rows, report = _run("none")
    source_rows = _jsonl(FIXTURE / "relations.jsonl")

    assert sorted(_canon(r, STAMP) for r in rows) == sorted(_canon(r, STAMP) for r in source_rows)
    assert all(set(r) - set(s) <= STAMP for r, s in zip(sorted(rows, key=_canon),
                                                        sorted(source_rows, key=_canon)))
    # source: the row's own, else derived from the phase (2 rule, 3 prior, 4 llm, 5 inverse)
    by_key = {(r["head_id"], r["relation"], r["tail_id"]): r["source"] for r in rows}
    assert by_key[("person:luode", "FATHER_OF", "person:tala")] == "rule"
    assert by_key[("person:tala", "FATHER_OF", "person:yabolahan")] == "prior"
    assert by_key[("person:yabolahan", "SON_OF", "person:tala")] == "inverse"
    assert by_key[("person:nahe", "SIBLING_OF", "person:yabolahan")] == "llm"
    assert {r["schema_version"] for r in rows} == {SCHEMA_VERSION}
    assert {r["pp_version"] for r in rows} == {pp.pp_version()}
    assert report["rules"] == {"mode": "none", "ran": []}
    assert report["flow"] == {"input": 9, "drops": {}, "anchored": {}, "flagged": {}, "output": 9}
    assert report["conflicts"] == []


def test_row_without_a_known_source_fails_hard(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    with (tmp_path / "in" / "relations.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"head_id": "person:tala", "relation": "FATHER_OF", "tail_id": "person:nahe",
                            "extraction_phase": 1}) + "\n")
    with pytest.raises(ValueError, match="person:tala FATHER_OF person:nahe"):
        _run("none", _paths(tmp_path / "in"))


# --- determinism ----------------------------------------------------------------

@pytest.mark.parametrize("rules", ["all", "none"])
def test_output_is_byte_identical_across_hash_seeds(tmp_path, rules):
    runs = []
    for seed in ("1", "987"):
        proc, out, report = _cli(tmp_path, "--rules", rules, seed=seed)
        assert proc.returncode == 0, proc.stderr
        runs.append((out.read_bytes(), report.read_bytes()))
    assert runs[0] == runs[1]

    lines = runs[0][0].decode("utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert lines == [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows]
    assert [(r["head_id"], r["relation"], r["tail_id"]) for r in rows] == \
        sorted((r["head_id"], r["relation"], r["tail_id"]) for r in rows)
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name, report.name]   # no temp files left


# --- hard failures ------------------------------------------------------------

def test_missing_endpoint_fails_hard(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    with (tmp_path / "in" / "relations.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"head_id": "person:liuer", "tail_id": "person:tala", "relation": "SON_OF",
                            "confidence": 0.65, "evidence_span": "", "source_pericope_id": "gen:11:1",
                            "extraction_phase": 4, "head_canonical": "流珥", "tail_canonical": "他拉",
                            "notes": ""}, ensure_ascii=False) + "\n")
    paths = _paths(tmp_path / "in")
    with pytest.raises(ValueError, match="person:liuer"):
        _run("none", paths)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "relations_clean.jsonl").write_text("previous run\n", encoding="utf-8")
    proc, out, report = _cli(tmp_path, paths=paths)
    assert proc.returncode == 1
    assert "person:liuer" in proc.stderr
    assert out.read_text(encoding="utf-8") == "previous run\n"   # nothing written, not even a temp file
    assert not report.exists()
    assert [p.name for p in out_dir.iterdir()] == [out.name]


# --- report -------------------------------------------------------------------

def test_report_counts_edges_on_generic_events():
    rows, report = _run("none")
    after = report["expected_after_10_2"]

    # Event nodes whose canonical_name is a 10.2 stoplist noun; theme:rizi (日子, Theme) is not one
    assert after["generic_event_ids"] == ["event:dahui", "event:rizi"]
    assert after["edges_on_generic_events"] == 2
    kept = [r for r in rows if "event:rizi" not in (r["head_id"], r["tail_id"])]
    assert after["edges"] == len(kept) == 7
    lines = sorted(f"{r['head_id']}\t{r['relation']}\t{r['tail_id']}\t{r['source']}" for r in kept)
    assert pp.edge_set_lines(kept) == lines
    assert after["edge_set_sha256"] == pp.edge_set_sha256(kept) == \
        hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    assert after["by_ee_key"] == {
        "DIED_IN phase=4 source=llm": 1, "FATHER_OF phase=2 source=rule": 1,
        "FATHER_OF phase=3 source=prior": 1, "LOCATED_IN phase=4 source=llm": 1,
        "OCCURRED_IN phase=4 source=llm": 1, "SIBLING_OF phase=4 source=llm": 1,
        "SON_OF phase=5 source=inverse": 1,
    }
    assert after["by_type"] == {"DIED_IN": 1, "FATHER_OF": 2, "LOCATED_IN": 1, "OCCURRED_IN": 1,
                                "SIBLING_OF": 1, "SON_OF": 1}


def test_report_records_input_sha256_and_pp_version(tmp_path):
    proc, out, report_path = _cli(tmp_path, "--rules", "none")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    paths = _paths()

    assert report["format"] == "relations_postprocess_report/v1"
    assert list(report["inputs"]) == sorted(pp.INPUTS)
    shas = {}
    for name, path in paths.items():
        shas[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        jsonl = path.suffix == ".jsonl"
        assert report["inputs"][name] == {
            "path": str(path.relative_to(ROOT)), "sha256": shas[name],
            "rows": len(_jsonl(path)) if jsonl else None}
    assert re.fullmatch(r"pp-[0-9a-f]{12}", report["pp_version"])
    assert report["pp_version"] == pp.pp_version()
    assert report["schema_version"] == SCHEMA_VERSION
    run_hash = hashlib.sha256((report["pp_version"] + "".join(shas[n] for n in pp.INPUTS)).encode())
    assert report["run_id"] == "6.05-" + run_hash.hexdigest()[:12]

    rows = _jsonl(out)
    assert report["output"] == {
        "path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "rows": 9,
        "by_source": {"inverse": 1, "llm": 6, "prior": 1, "rule": 1},
        "by_relation": {"DIED_IN": 1, "FATHER_OF": 2, "LOCATED_IN": 1, "OCCURRED_IN": 2,
                        "PARTICIPATED_IN": 1, "SIBLING_OF": 1, "SON_OF": 1}}
    assert {(r["pp_version"], r["schema_version"]) for r in rows} == \
        {(report["pp_version"], report["schema_version"])}


# --- pp_version -----------------------------------------------------------------

def test_pp_version_hashes_the_code_and_config_6_05_depends_on():
    assert sorted(pp.PP_FILES) == [
        "config/curated/entity_overrides.yaml",
        "config/relations/anchored_rules.yaml",
        "config/relations/biblical_relations.yaml",
        "scripts/entity_extraction/entity_overrides.py",
        "scripts/entity_extraction/geo_rules.py",
        "scripts/entity_extraction/stoplists.py",
        "scripts/relation_extraction/anchored_rules.py",
        "scripts/relation_extraction/models.py",
        "scripts/relation_extraction/relation_policy.py",
        "scripts/relation_extraction/relation_postprocess.py",
        "scripts/relation_extraction/schema_loader.py",
    ]


@pytest.mark.parametrize("changed", ["scripts/relation_extraction/models.py",
                                     "scripts/relation_extraction/schema_loader.py"])
def test_pp_version_changes_when_models_or_schema_loader_change(tmp_path, changed):
    for rel in pp.PP_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    assert pp.pp_version(tmp_path) == pp.pp_version()

    with (tmp_path / changed).open("a", encoding="utf-8") as f:
        f.write("# changed\n")
    assert pp.pp_version(tmp_path) != pp.pp_version()


# --- relation_policy ------------------------------------------------------------

def test_source_rank_orders_curated_prior_llm_anchored():
    assert SOURCE_RANK == {"curated": 0, "prior": 1, "llm": 2, "anchored_rule": 3}
    assert rank({"source": "prior"}) < rank({"extraction_phase": 4}) < rank({"source": "anchored_rule"})


@pytest.mark.parametrize("row", [{"source": "inverse"}, {"extraction_phase": 2}, {"extraction_phase": 1},
                                 {"extraction_phase": 5, "notes": "cooccurrence-backfill"}])
def test_rank_fails_fast_on_an_unranked_source(row):
    with pytest.raises(ValueError, match="rank"):
        rank(row)


def test_source_of_and_parent_child_read_a_row():
    assert source_of({"extraction_phase": 5, "notes": "derived_from=SON_OF"}) == "inverse"
    assert source_of({"source": "curated", "extraction_phase": 3}) == "curated"
    assert parent_child({"head_id": "a", "relation": "SON_OF", "tail_id": "b"}) == ("b", "a")
    assert parent_child({"head_id": "a", "relation": "MOTHER_OF", "tail_id": "b"}) == ("a", "b")
    assert parent_child({"head_id": "a", "relation": "SPOUSE_OF", "tail_id": "b"}) is None
