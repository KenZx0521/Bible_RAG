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

import dataclasses
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

from relation_extraction import anchored_rules
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


# --- drop_inverse (REL-02) ------------------------------------------------------

def _row(head: str, relation: str, tail: str, phase: int, **extra) -> dict:
    return {"head_id": head, "relation": relation, "tail_id": tail, "extraction_phase": phase,
            "notes": "", **extra}


def test_drop_inverse_removes_every_inverse_row():
    rows, report = _run("all")

    # R5 restated every directed edge backwards (phase 5, derived_from=...); none survives
    assert [r for r in rows if r["source"] == "inverse"] == []
    assert report["flow"]["drops"]["inverse"] == {"SON_OF": 1}
    assert report["rules"]["ran"][0] == "drop_inverse"

    # inverse by the row's own source or, lacking one, by phase 5; a phase-5
    # cooccurrence backfill is not an inverse, and the forward row stays
    inputs, cfg = pp.load_inputs(_paths())
    stamped = [pp.base_stamp(r, cfg) for r in (
        _row("person:yabolahan", "SON_OF", "person:tala", 5, notes="derived_from=FATHER_OF"),
        _row("person:nahe", "DESCENDANT_OF", "person:tala", 5, source="inverse"),
        _row("person:nahe", "PARTICIPATED_IN", "event:hongshui", 5, notes="cooccurrence-backfill"),
        _row("person:tala", "FATHER_OF", "person:yabolahan", 3),
    )]
    flow = pp.Flow()
    assert pp.drop_inverse(stamped, inputs, cfg, flow) == stamped[2:]
    assert flow.drops == {"inverse": {"SON_OF": 1, "DESCENDANT_OF": 1}}
    assert [r["source"] for r in stamped] == ["inverse", "inverse", "cooccurrence", "prior"]


# --- rules_to_anchored (REL-01) -------------------------------------------------

P1, P2, P3, P4 = "P1_child_of", "P2_is_child_of", "P3_begot", "P4_wife"
LEVI_SONS = "利未的兒子是革順、哥轄、米拉利。"   # gen 46:11 and 1ch 6:1
AMRAM = "暗蘭的妻名叫約基別，是利未女子，生在埃及。她給暗蘭生了亞倫、摩西，並他們的姊姊米利暗。"   # num 26:59


def _anchored_row(head: str, relation: str, tail: str, pattern: str, pid: str, verse: int, text: str,
                  support: list[str], evidence_count: int = 1) -> dict:
    names = {r["entity_id"]: r["canonical_name"] for r in _jsonl(FIXTURE / "entities.jsonl")}
    return {"head_id": head, "relation": relation, "tail_id": tail, "source": "anchored_rule",
            "extraction_phase": 6, "notes": pattern, "source_pericope_id": pid, "verse": verse,
            "evidence_span": text, "head_canonical": names[head], "tail_canonical": names[tail],
            "support_pericopes": support, "evidence_count": evidence_count}


def _key_set_sha256(rows) -> str:
    lines = sorted(f"{r['head_id']}\t{r['relation']}\t{r['tail_id']}" for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def test_rule_rows_are_replaced_by_anchored_rows():
    rows, report = _run("all")

    # the id-order rule row 羅得 FATHER_OF 他拉 (from 「哈蘭生羅得」) goes, and nothing takes its
    # place: 「他拉生亞伯蘭」 has no 給, so under begot: gei it names no father (K1)
    assert [r for r in rows if r["source"] == "rule"] == []
    assert report["flow"]["drops"]["rule"] == {"FATHER_OF": 1}
    assert report["rules"]["ran"][:2] == ["drop_inverse", "rules_to_anchored"]

    # one row per key; its primary hit is the smallest (pericope id, verse), 1ch:6:0 v1 although
    # gen:46:0 v11 comes first in the file, and every hit's pericope stays as support
    levi = ("1ch:6:0", 1, LEVI_SONS, ["1ch:6:0", "gen:46:0"], 2)
    anchored = [r for r in rows if r["source"] == "anchored_rule"]
    assert [{k: v for k, v in r.items() if k not in STAMP - {"source"}} for r in anchored] == [
        _anchored_row("person:anlan", "FATHER_OF", "person:moxi", P3, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:anlan", "FATHER_OF", "person:yalun", P3, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:anlan", "SPOUSE_OF", "person:yuejibie", P4, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:geshun", "SON_OF", "person:liwei", P1, *levi),
        _anchored_row("person:gexia", "SON_OF", "person:liwei", P1, *levi),
        _anchored_row("person:milali", "SON_OF", "person:liwei", P1, *levi),
    ]
    assert {(r["schema_version"], r["pp_version"]) for r in anchored} == {(SCHEMA_VERSION, pp.pp_version())}
    by_pattern = {P1: 6, P2: 0, P3: 2, P4: 1}
    assert report["flow"]["anchored"] == {
        "enabled": True, "pattern_hits": 9, "by_pattern": by_pattern,
        "guard_other_parent": 0, "guard_homonym": 0, "disagreement_children": 0, "disagreement_abstain": 0,
        "emitted_hits": 9, "emitted_by_pattern": by_pattern, "unique_keys": 6,
        "foreign_surface_skipped": 0, "ambiguous_name": 0, "key_set_sha256": _key_set_sha256(anchored)}
    assert report["conflicts"] == []


def test_anchored_guard_reads_curated_prior_and_llm_parents_only(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    with (tmp_path / "in" / "relations.jsonl").open("a", encoding="utf-8") as f:
        for row in (_row("person:moxi", "SON_OF", "person:yuejibie", 4, source_pericope_id="num:26:0"),
                    _row("person:yalun", "SON_OF", "person:moxi", 2, source_pericope_id="num:26:0")):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows, report = _run("all", _paths(tmp_path / "in"))

    # the llm row gives 摩西 a parent (a mother counts), so 「給暗蘭生了…摩西」 abstains and is
    # logged; the id-order rule row is dropped first and gives 亞倫 no parent
    keys = {(r["head_id"], r["relation"], r["tail_id"]) for r in rows if r["source"] == "anchored_rule"}
    assert ("person:anlan", "FATHER_OF", "person:moxi") not in keys
    assert ("person:anlan", "FATHER_OF", "person:yalun") in keys
    assert report["conflicts"] == [{
        "head_id": "person:anlan", "relation": "FATHER_OF", "tail_id": "person:moxi",
        "source_pericope_id": "num:26:0", "verse": 59, "pattern": P3,
        "reason": "other_parent", "other_parents": ["person:yuejibie"]}]
    assert report["flow"]["drops"]["rule"] == {"FATHER_OF": 1, "SON_OF": 1}
    anchored = report["flow"]["anchored"]
    assert (anchored["guard_other_parent"], anchored["emitted_hits"], anchored["unique_keys"]) == (1, 8, 5)


def test_anchored_disabled_drops_rule_rows_and_adds_none(tmp_path):
    # the pre-registered K9 fallback: a config switch, no code change
    doc = yaml.safe_load(anchored_rules.CONFIG_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "anchored_rules.yaml"
    path.write_text(yaml.safe_dump({**doc, "enabled": False}, allow_unicode=True), encoding="utf-8")
    rows, report = _run("all", {**_paths(), "anchored_config": path})
    enabled_rows, _ = _run("all")

    assert not any(r["source"] in ("rule", "anchored_rule") for r in rows)
    assert report["flow"]["drops"]["rule"] == {"FATHER_OF": 1}
    assert report["flow"]["anchored"] == {"enabled": False}
    assert report["conflicts"] == []
    assert rows == [r for r in enabled_rows if r["source"] != "anchored_rule"]


# --- drop_llm_event_event (REL-08, EV-10) ---------------------------------------

def test_llm_event_event_rows_are_dropped(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    with (tmp_path / "in" / "relations.jsonl").open("a", encoding="utf-8") as f:
        for row in (_row("event:hongshui", "PRECEDED_BY", "event:dahui", 4, source_pericope_id="gen:11:1"),
                    _row("event:dahui", "CAUSED", "event:hongshui", 4, source_pericope_id="gen:11:1"),
                    _row("event:rizi", "PRECEDED_BY", "event:hongshui", 3)):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows, report = _run("all", _paths(tmp_path / "in"))

    # the LLM's Event–Event edges go; a prior between two events is not the LLM's and stays,
    # as does an llm edge with one Event endpoint (洪水 OCCURRED_IN 吾珥)
    keys = {(r["head_id"], r["relation"], r["tail_id"], r["source"]) for r in rows}
    assert not {("event:hongshui", "PRECEDED_BY", "event:dahui", "llm"),
                ("event:dahui", "CAUSED", "event:hongshui", "llm")} & keys
    assert {("event:rizi", "PRECEDED_BY", "event:hongshui", "prior"),
            ("event:hongshui", "OCCURRED_IN", "place:wuer", "llm")} <= keys
    assert report["flow"]["drops"]["llm_event_event"] == {"CAUSED": 1, "PRECEDED_BY": 1}
    assert report["rules"]["ran"][:3] == ["drop_inverse", "rules_to_anchored", "drop_llm_event_event"]

    # the endpoint types are the final ones: an Event relabelled away keeps its edge, a
    # Theme relabelled to Event loses it
    inputs, cfg = pp.load_inputs(_paths())
    relabel = {**cfg.overrides, "event:dahui": {"label": "Theme"}, "theme:rizi": {"label": "Event"}}
    stamped = [pp.base_stamp(r, cfg) for r in (_row("event:hongshui", "PRECEDED_BY", "event:dahui", 4),
                                                _row("event:hongshui", "CAUSED", "theme:rizi", 4))]
    flow = pp.Flow()
    assert pp.drop_llm_event_event(stamped, inputs, dataclasses.replace(cfg, overrides=relabel),
                                   flow) == stamped[:1]
    assert flow.drops == {"llm_event_event": {"CAUSED": 1}}


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
