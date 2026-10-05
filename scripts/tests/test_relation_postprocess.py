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
from collections import Counter
from pathlib import Path

import pytest
import yaml

from relation_extraction import anchored_rules
from relation_extraction import relation_postprocess as pp
from relation_extraction.relation_policy import parent_child

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
    assert report["flow"] == {"input": 9, "drops": {}, "drops_due_to_dan_filter": {}, "anchored": {},
                              "flagged": {}, "collapsed_keys": {}, "output": 9}
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
            "support_pericopes": support, "evidence_count": evidence_count, "sources": ["anchored_rule"],
            "confidence_raw": None}


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
    assert [{k: v for k, v in r.items() if k not in STAMP - {"source"} | {"run_id"}} for r in anchored] == [
        _anchored_row("person:anlan", "FATHER_OF", "person:moxi", P3, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:anlan", "FATHER_OF", "person:yalun", P3, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:anlan", "SPOUSE_OF", "person:yuejibie", P4, "num:26:0", 59, AMRAM, ["num:26:0"]),
        _anchored_row("person:geshun", "SON_OF", "person:liwei", P1, *levi),
        _anchored_row("person:gexia", "SON_OF", "person:liwei", P1, *levi),
        _anchored_row("person:milali", "SON_OF", "person:liwei", P1, *levi),
    ]
    assert {(r["schema_version"], r["pp_version"], r["run_id"]) for r in anchored} == {
        (SCHEMA_VERSION, pp.pp_version(), report["run_id"])}
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
    # as does an llm edge with one Event endpoint (日子 OCCURRED_IN 吾珥)
    keys = {(r["head_id"], r["relation"], r["tail_id"], r["source"]) for r in rows}
    assert not {("event:hongshui", "PRECEDED_BY", "event:dahui", "llm"),
                ("event:dahui", "CAUSED", "event:hongshui", "llm")} & keys
    assert {("event:rizi", "PRECEDED_BY", "event:hongshui", "prior"),
            ("event:rizi", "OCCURRED_IN", "place:wuer", "llm")} <= keys
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

    # only the llm's row goes: a curated, anchored_rule or cooccurrence one between two events stays
    stamped = [pp.base_stamp(_row("event:hongshui", "PRECEDED_BY", "event:dahui", 4, source=source), cfg)
               for source in ("llm", "curated", "anchored_rule", "cooccurrence")]
    flow = pp.Flow()
    assert pp.drop_llm_event_event(stamped, inputs, cfg, flow) == stamped[1:]
    assert flow.drops == {"llm_event_event": {"PRECEDED_BY": 1}}


# --- provenance_gate (REL-05, M3) -----------------------------------------------

SALADAN = "在約旦平原、疏割和撒拉但中間"   # 1ki 7:46: the 但 of 撒拉但 is no place
DAN_TO_BEERSHEBA = "從但到別是巴所有的以色列人"   # 1sa 3:20
GATE_PLACES = {"place:dan": "但", "place:yuedan": "約旦", "place:yiselie": "以色列"}


def _place(entity_id: str) -> dict:
    return {"entity_id": entity_id, "type": "Place", "canonical_name": GATE_PLACES[entity_id], "aliases": [],
            "description": "", "extraction_method": "fixture", "mention_count": 1}


def _mention(entity_id: str, source_id: str, source_type: str, context: str) -> dict:
    return {"mention_id": f"m:{source_id}:{entity_id}", "entity_id": entity_id, "source_id": source_id,
            "source_type": source_type, "text_span": GATE_PLACES[entity_id], "context": context}


def _append_jsonl(path: Path, rows) -> None:
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_gate_drops_dan_orphan_and_exempts_prior(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    _append_jsonl(tmp_path / "in" / "entities.jsonl", [_place(eid) for eid in GATE_PLACES])
    _append_jsonl(tmp_path / "in" / "entity_mentions.jsonl", [
        _mention("place:yuedan", "1ki:7:5:v:46", "verse", SALADAN),
        _mention("place:dan", "1ki:7:5:v:46", "verse", SALADAN),
        _mention("place:dan", "1sa:3:0:v:20", "verse", DAN_TO_BEERSHEBA),
        _mention("place:yiselie", "1sa:3:0:v:20", "verse", DAN_TO_BEERSHEBA)])
    _append_jsonl(tmp_path / "in" / "relations.jsonl", [
        _row("place:dan", "NEAR", "place:yuedan", 4, source_pericope_id="1ki:7:5"),
        _row("place:dan", "LOCATED_IN", "place:yiselie", 4, source_pericope_id="1sa:3:0"),
        _row("place:yuedan", "NEAR", "place:yiselie", 4, source_pericope_id=""),
        _row("place:yiselie", "NEAR", "place:yuedan", None, source="curated", source_pericope_id="1ki:7:5")])
    rows, report = _run("all", _paths(tmp_path / "in"))
    keys = {(r["head_id"], r["relation"], r["tail_id"], r["source"]) for r in rows}

    # 但 NEAR 約旦 rests on 「撒拉但」 alone, whose MENTIONS edge 10.2 deletes: it goes, the one
    # drop the 「但」 filter causes. 「從但到別是巴」 is the place, so 但 LOCATED_IN 以色列 stays
    assert ("place:dan", "NEAR", "place:yuedan", "llm") not in keys
    assert ("place:dan", "LOCATED_IN", "place:yiselie", "llm") in keys
    # unsupported without the filter: no pericope at all; 洪水 is never mentioned in gen:11:1
    assert ("place:yuedan", "NEAR", "place:yiselie", "llm") not in keys
    assert ("event:hongshui", "OCCURRED_IN", "place:wuer", "llm") not in keys
    assert report["flow"]["drops"]["provenance_gate"] == {"NEAR": 2, "OCCURRED_IN": 1}
    assert report["flow"]["drops_due_to_dan_filter"] == {"NEAR": 1}

    # G-3: prior and curated rows pass ungated (創 11:26 names no pericope; 以色列 is not
    # mentioned in 1ki:7:5); the anchored rows are gated, and all six are supported
    assert {("person:tala", "FATHER_OF", "person:yabolahan", "prior"),
            ("place:yiselie", "NEAR", "place:yuedan", "curated")} <= keys
    assert sum(r["source"] == "anchored_rule" for r in rows) == 6
    ran = report["rules"]["ran"]
    assert ran.index("drop_llm_event_event") < ran.index("provenance_gate")


def test_chunk_mentions_roll_up_to_parent():
    inputs, cfg = pp.load_inputs(_paths())
    # 吾珥 is mentioned only in chunk gen:11:1:0; that MENTIONS edge supports its parent pericope
    assert [(m["source_id"], m["source_type"]) for m in inputs.mentions
            if m["entity_id"] == "place:wuer"] == [("gen:11:1:0", "chunk")]
    # 10.2 keys a chunk's 「但」 edge by the chunk id: the place name in chunk 1ki:12:2:0 keeps
    # its edge although no verse of 1ki:12:2 names the place; 撒拉但 in chunk 1ki:7:5:0 loses it
    inputs = dataclasses.replace(
        inputs,
        entities={**inputs.entities, **{eid: _place(eid) for eid in GATE_PLACES}},
        mentions=[*inputs.mentions,
                  _mention("place:dan", "1ki:12:2:0", "chunk", "一隻安在但"),
                  _mention("place:yuedan", "1ki:12:2:v:30", "verse", "約旦"),
                  _mention("place:dan", "1ki:7:5:0", "chunk", SALADAN),
                  _mention("place:yuedan", "1ki:7:5:v:46", "verse", SALADAN)],
        chunk_parent={**inputs.chunk_parent, "1ki:12:2:0": "1ki:12:2", "1ki:7:5:0": "1ki:7:5"})
    stamped = [pp.base_stamp(r, cfg) for r in (
        _row("person:tala", "DIED_IN", "place:wuer", 4, source_pericope_id="gen:11:1"),
        _row("person:tala", "DIED_IN", "place:wuer", 4, source_pericope_id="gen:11:1:0"),
        _row("place:dan", "NEAR", "place:yuedan", 4, source_pericope_id="1ki:12:2"),
        _row("place:dan", "NEAR", "place:yuedan", 4, source_pericope_id="1ki:7:5"),
        # an anchored row is gated like an llm one: 羅得 and 他拉 are not in num:26:0
        _row("person:luode", "SON_OF", "person:tala", 6, source="anchored_rule", source_pericope_id="num:26:0"),
    )]
    flow = pp.Flow()

    # support is keyed by pericope: the chunk id itself names none
    assert pp.provenance_gate(stamped, inputs, cfg, flow) == [stamped[0], stamped[2]]
    assert flow.drops == {"provenance_gate": {"DIED_IN": 1, "NEAR": 1, "SON_OF": 1}}
    assert flow.dan_filter_drops == {"NEAR": 1}


# --- domain_range (G-2) ---------------------------------------------------------

def test_domain_range_uses_override_labels(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    # 耶和華 is a Group in entities.jsonl and a Person in config/curated/entity_overrides.yaml (D9)
    _append_jsonl(tmp_path / "in" / "entity_mentions.jsonl", [{
        "mention_id": "m:num:26:0:v:59:group:yehehua", "entity_id": "group:yehehua",
        "source_id": "num:26:0:v:59", "source_type": "verse", "text_span": "耶和華", "context": AMRAM}])
    _append_jsonl(tmp_path / "in" / "relations.jsonl", [
        _row("person:moxi", "LEADER_OF", "group:yehehua", 4, source_pericope_id="num:26:0"),
        _row("group:yehehua", "SETTLED_IN", "place:wuer", 4, source_pericope_id="gen:11:1"),
        _row("group:yehehua", "TEACHER_OF", "person:moxi", 4, source_pericope_id="num:26:0"),
        _row("person:tala", "DIED_IN", "person:nahe", 3, source_pericope_id=""),
        _row("person:moxi", "KNEW", "person:yalun", 4, source_pericope_id="num:26:0")])
    rows, report = _run("all", _paths(tmp_path / "in"))
    keys = {(r["head_id"], r["relation"], r["tail_id"], r["source"]) for r in rows}

    # the endpoint types are the final ones: a Person is no Group to lead or to settle, but
    # can teach; a prior is checked too (DIED_IN takes a Place), and a relation the schema
    # does not know goes under its own key, as H9 counts unknown_relation_types apart
    assert ("person:moxi", "LEADER_OF", "group:yehehua", "llm") not in keys
    assert ("group:yehehua", "TEACHER_OF", "person:moxi", "llm") in keys
    assert not {("person:tala", "DIED_IN", "person:nahe", "prior"),
                ("person:moxi", "KNEW", "person:yalun", "llm")} & keys
    drops = report["flow"]["drops"]
    assert drops["domain_range"] == {"DIED_IN": 1, "LEADER_OF": 1, "SETTLED_IN": 1}
    assert drops["unknown_relation"] == {"KNEW": 1}
    # it runs before the gate: 耶和華 SETTLED_IN 吾珥 has no support in gen:11:1 either, but
    # is domain_range's drop
    assert "SETTLED_IN" not in drops.get("provenance_gate", {})
    ran = report["rules"]["ran"]
    assert ran.index("drop_llm_event_event") < ran.index("domain_range") < ran.index("provenance_gate")

    # without the override 耶和華 is the extracted Group again: led yes, teaching no
    inputs, cfg = pp.load_inputs(_paths())
    stamped = [pp.base_stamp(r, cfg) for r in (_row("person:moxi", "LEADER_OF", "group:yehehua", 4),
                                                _row("group:yehehua", "TEACHER_OF", "person:moxi", 4))]
    flow = pp.Flow()
    assert pp.domain_range(stamped, inputs, dataclasses.replace(cfg, overrides={}), flow) == stamped[:1]
    assert flow.drops == {"domain_range": {"TEACHER_OF": 1}}


# --- flag_id_order (REL-03) -----------------------------------------------------

def test_llm_id_order_rows_are_flagged_and_prior_contradiction_dropped(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    _append_jsonl(tmp_path / "in" / "relations.jsonl", [
        _row("place:nasalei", "LOCATED_IN", "place:jialili", 3, source_pericope_id="", evidence_span="路 1:26"),
        _row("place:jialili", "LOCATED_IN", "place:nasalei", 4, source_pericope_id="mat:2:3"),
        _row("person:tala", "SUCCEEDED_BY", "person:nahe", 4, source_pericope_id="gen:11:1"),
        _row("person:nahe", "SUCCEEDED_BY", "person:tala", 4, source_pericope_id="gen:11:1"),
        _row("person:moxi", "SUCCEEDED_BY", "person:yalun", None, source="curated", source_pericope_id="")])
    rows, report = _run("all", _paths(tmp_path / "in"))
    flags = {(r["head_id"], r["relation"], r["tail_id"], r["source"]): r["direction_verified"]
             for r in rows if "direction_verified" in r}

    # an id-order relation (directed, one type at both ends, no direction pair) reads only by
    # head/tail order, and the LLM's rows have their ends in id order: 加利利 LOCATED_IN 拿撒勒
    # reverses the prior (路 1:26) and goes; every other llm row is kept unverified, and an llm
    # pair in both orders stays whole. The fixture's own 拿撒勒 LOCATED_IN 加利利 (llm, flagged)
    # states the prior's key, so it folds into that row and the prior's verified direction stands
    assert flags == {
        ("place:nasalei", "LOCATED_IN", "place:jialili", "prior"): True,
        ("person:tala", "SUCCEEDED_BY", "person:nahe", "llm"): False,
        ("person:nahe", "SUCCEEDED_BY", "person:tala", "llm"): False,
        ("person:moxi", "SUCCEEDED_BY", "person:yalun", "curated"): True}
    assert ("place:jialili", "LOCATED_IN", "place:nasalei") not in {(r["head_id"], r["relation"], r["tail_id"])
                                                                    for r in rows}
    assert report["flow"]["drops"]["contradicts_prior"] == {"LOCATED_IN": 1}
    assert report["flow"]["flagged"] == {"LOCATED_IN": 1, "SUCCEEDED_BY": 2}
    assert [r["sources"] for r in rows if r["head_id"] == "place:nasalei"] == [["llm", "prior"]]
    ran = report["rules"]["ran"]
    assert ran.index("provenance_gate") < ran.index("flag_id_order")

    # called directly: a paired relation (SON_OF, FATHER_OF) or an undirected one (NEAR) gets
    # no field, a prior's neither, nor an id-order row that is neither llm nor prior/curated
    # (anchored_rule, cooccurrence); the rule copies the rows it marks, True or False, it does
    # not mutate them
    inputs, cfg = pp.load_inputs(_paths())
    stamped = [pp.base_stamp(r, cfg) for r in (
        _row("place:nasalei", "LOCATED_IN", "place:jialili", 3),
        _row("place:jialili", "LOCATED_IN", "place:nasalei", 4),
        _row("place:jialili", "NEAR", "place:nasalei", 4),
        _row("person:yabolahan", "SON_OF", "person:tala", 4),
        _row("person:tala", "FATHER_OF", "person:yabolahan", 3),
        _row("person:tala", "SUCCEEDED_BY", "person:nahe", 4),
        _row("place:nasalei", "LOCATED_IN", "place:jialili", 6, source="anchored_rule"),
        _row("person:nahe", "SUCCEEDED_BY", "person:tala", 7, source="cooccurrence"))]
    flow = pp.Flow()
    assert pp.flag_id_order(stamped, inputs, cfg, flow) == [
        {**stamped[0], "direction_verified": True}, *stamped[2:5], {**stamped[5], "direction_verified": False},
        *stamped[6:]]
    assert not any("direction_verified" in r for r in stamped)
    assert flow.drops == {"contradicts_prior": {"LOCATED_IN": 1}}
    assert flow.flagged == {"SUCCEEDED_BY": 1}


# --- resolve_kinship_direction, dedup_undirected (REL-01/02, R6) ----------------

# the first and third reverse a parent/child pair the fixture's all-mode run holds; the second
# agrees with the prior 他拉 FATHER_OF 亞伯拉罕 and stays (a row in the winning direction)
KIN_ROWS = (
    _row("person:yabolahan", "FATHER_OF", "person:tala", 4, source_pericope_id="gen:11:1"),
    _row("person:yabolahan", "SON_OF", "person:tala", 4, source_pericope_id="gen:11:1"),
    _row("person:moxi", "FATHER_OF", "person:anlan", 4, source_pericope_id="num:26:0"))
UNDIRECTED_ROWS = (   # each restates an undirected pair, the fixture's own or another of these
    _row("person:yabolahan", "SIBLING_OF", "person:nahe", 3, source_pericope_id="", evidence_span="創 11:26"),
    _row("person:yuejibie", "SPOUSE_OF", "person:anlan", 4, source_pericope_id="num:26:0"),
    _row("place:nasalei", "NEAR", "place:jialili", 4, source_pericope_id="mat:2:3"),
    _row("place:jialili", "NEAR", "place:nasalei", 4, source_pericope_id="mat:2:3"))


def _keys(rows) -> set[tuple[str, str, str, str]]:
    return {(r["head_id"], r["relation"], r["tail_id"], r["source"]) for r in rows}


def _brief(head: str, relation: str, tail: str, source: str, pid: str, verse: int | None) -> dict:
    return {"head_id": head, "relation": relation, "tail_id": tail, "source": source,
            "source_pericope_id": pid, "verse": verse}


def test_father_of_contradictions_resolve_by_source_rank(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    _append_jsonl(tmp_path / "in" / "relations.jsonl", KIN_ROWS)
    rows, report = _run("all", _paths(tmp_path / "in"))
    keys = _keys(rows)

    # one direction per parent/child pair, the best-ranked row's (curated > prior > llm >
    # anchored_rule): the prior 他拉 FATHER_OF 亞伯拉罕 (創 11:26) outranks the llm row that
    # reverses it, the llm 摩西 FATHER_OF 暗蘭 the anchored row it reverses; a row in the
    # winning direction stays whatever its rank
    assert {("person:tala", "FATHER_OF", "person:yabolahan", "prior"),
            ("person:yabolahan", "SON_OF", "person:tala", "llm"),
            ("person:moxi", "FATHER_OF", "person:anlan", "llm")} <= keys
    assert not {("person:yabolahan", "FATHER_OF", "person:tala", "llm"),
                ("person:anlan", "FATHER_OF", "person:moxi", "anchored_rule")} & keys
    assert report["flow"]["drops"]["kin_direction_conflict"] == {"FATHER_OF": 2}
    assert [c for c in report["conflicts"] if c["reason"] == "kin_direction_conflict"] == [
        {**_brief("person:anlan", "FATHER_OF", "person:moxi", "anchored_rule", "num:26:0", 59),
         "reason": "kin_direction_conflict",
         "kept": _brief("person:moxi", "FATHER_OF", "person:anlan", "llm", "num:26:0", None)},
        {**_brief("person:yabolahan", "FATHER_OF", "person:tala", "llm", "gen:11:1", None),
         "reason": "kin_direction_conflict",
         "kept": _brief("person:tala", "FATHER_OF", "person:yabolahan", "prior", "", None)}]
    fathers = {(r["head_id"], r["tail_id"]) for r in rows if r["relation"] == "FATHER_OF"}
    assert not {(t, h) for h, t in fathers} & {parent_child(r) for r in rows if parent_child(r)}   # R6
    ran = report["rules"]["ran"]
    assert ran.index("flag_id_order") < ran.index("resolve_kinship_direction")
    # the policy called directly, on hand-made rows: test_relation_policy.py


def test_undirected_pair_keeps_best_ranked_orientation(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    _append_jsonl(tmp_path / "in" / "relations.jsonl", UNDIRECTED_ROWS)
    rows, report = _run("all", _paths(tmp_path / "in"))
    keys = _keys(rows)

    # one row per unordered pair and undirected relation, the best-ranked one in its own
    # orientation: the prior 亞伯拉罕 SIBLING_OF 拿鶴 over the fixture's llm 拿鶴 SIBLING_OF
    # 亞伯拉罕, the llm 約基別 SPOUSE_OF 暗蘭 over the anchored 暗蘭 SPOUSE_OF 約基別 (P4); of
    # two llm rows in one pericope the smaller head_id (加利利 NEAR 拿撒勒)
    assert {("person:yabolahan", "SIBLING_OF", "person:nahe", "prior"),
            ("person:yuejibie", "SPOUSE_OF", "person:anlan", "llm"),
            ("place:jialili", "NEAR", "place:nasalei", "llm")} <= keys
    assert not {("person:nahe", "SIBLING_OF", "person:yabolahan", "llm"),
                ("person:anlan", "SPOUSE_OF", "person:yuejibie", "anchored_rule"),
                ("place:nasalei", "NEAR", "place:jialili", "llm")} & keys
    assert report["flow"]["drops"]["undirected_duplicate"] == {"NEAR": 1, "SIBLING_OF": 1, "SPOUSE_OF": 1}
    undirected = [r for r in rows if r["relation"] in ("NEAR", "SIBLING_OF", "SPOUSE_OF")]
    assert len(undirected) == len({(frozenset((r["head_id"], r["tail_id"])), r["relation"]) for r in undirected})
    ran = report["rules"]["ran"]
    assert ran.index("resolve_kinship_direction") < ran.index("dedup_undirected")


def test_conflict_log_is_deterministic(tmp_path):
    # the winner of a pair is the smallest by an explicit key, never the first row read: the
    # input lines in reverse give the same rows, drops and conflicts
    runs = []
    for name, order in (("forward", 1), ("reversed", -1)):
        shutil.copytree(FIXTURE, tmp_path / name)
        path = tmp_path / name / "relations.jsonl"
        lines = [*path.read_text(encoding="utf-8").splitlines(),
                 *(json.dumps(r, ensure_ascii=False) for r in KIN_ROWS + UNDIRECTED_ROWS)]
        path.write_text("".join(line + "\n" for line in lines[::order]), encoding="utf-8")
        runs.append(_run("all", _paths(tmp_path / name)))
    (rows, report), (rows_reversed, report_reversed) = runs
    # but for run_id: it hashes the input bytes, which the order changes (stamp_provenance)
    assert [_canon(r, {"run_id"}) for r in rows] == [_canon(r, {"run_id"}) for r in rows_reversed]
    assert report["flow"] == report_reversed["flow"]
    assert report["conflicts"] == report_reversed["conflicts"]
    assert [c["reason"] for c in report["conflicts"]] == ["kin_direction_conflict"] * 2


# --- collapse_by_key (REL-10, SON_OF onCreate-only part 1) ----------------------

def _triple(row: dict) -> tuple[str, str, str]:
    return row["head_id"], row["relation"], row["tail_id"]


def test_duplicate_key_raises(tmp_path, monkeypatch):
    shutil.copytree(FIXTURE, tmp_path / "in")
    # the llm also gives 革順 SON_OF 利未 (gen:46:0), a key the anchored rule makes from 1ch 6:1 and gen 46:11
    _append_jsonl(tmp_path / "in" / "relations.jsonl",
                  [_row("person:geshun", "SON_OF", "person:liwei", 4, source_pericope_id="gen:46:0")])
    paths = _paths(tmp_path / "in")
    # 6.1 makes one edge per key: a key the rules leave twice stops the run before anything is written
    with monkeypatch.context() as patch:
        patch.setattr(pp, "RULES", tuple(rule for rule in pp.RULES if rule[0] != "collapse_by_key"))
        with pytest.raises(ValueError, match="person:geshun SON_OF person:liwei"):
            _run("all", paths)

    # collapse_by_key leaves one row per key: the llm row is primary (it outranks the anchored rule)
    # with its own fields, and the support is every row's: 1 llm item and the 2 anchored hits
    rows, report = _run("all", paths)
    assert len(rows) == len({_triple(r) for r in rows})
    [row] = [r for r in rows if _triple(r) == ("person:geshun", "SON_OF", "person:liwei")]
    assert (row["source"], row["source_pericope_id"], row.get("verse")) == ("llm", "gen:46:0", None)
    assert (row["sources"], row["support_pericopes"], row["evidence_count"]) == (
        ["anchored_rule", "llm"], ["1ch:6:0", "gen:46:0"], 3)
    assert report["flow"]["collapsed_keys"] == {"anchored_rule+llm": 1}
    ran = report["rules"]["ran"]
    assert ran.index("dedup_undirected") < ran.index("collapse_by_key")


def _anchored(head: str, relation: str, tail: str, pid: str, verse: int, support: list[str], count: int) -> dict:
    return _row(head, relation, tail, 6, source="anchored_rule", source_pericope_id=pid, verse=verse,
                support_pericopes=support, evidence_count=count)


def test_batch0_son_of_rows_have_fixed_primary():
    # batch 0: prod held these four SON_OF edges as an older run's R5 copy (phase 5, no pericope) that
    # 6.1's onCreate-only SET never refreshed, staging as relations.jsonl has them now (REL-10). 6.05
    # hands 6.1 one row per key, the same in any input order: drop_inverse removes an R5 copy and
    # collapse_by_key keeps a key's best-ranked row, W1's multi-source keys too (a prior or the llm
    # outranks the anchored row of its key)
    inputs, cfg = pp.load_inputs(_paths())
    given = [pp.base_stamp(r, cfg) for r in (
        _row("person:yage", "SON_OF", "person:yisa", 4, source_pericope_id="gen:28:1"),
        _row("person:yage", "SON_OF", "person:yisa", 5, source_pericope_id="", notes="derived_from=FATHER_OF"),
        _row("person:bianyamin", "SON_OF", "person:yage", 4, source_pericope_id="gen:35:1"),
        _row("person:bianyamin", "SON_OF", "person:lajie", 4, source_pericope_id="gen:35:1"),
        _anchored("person:dawei", "SON_OF", "person:yexi", "1ch:29:2", 26, ["1ch:29:2", "luk:3:2"], 2),
        _row("person:yexi", "FATHER_OF", "person:dawei", 3, source_pericope_id=""),
        _row("person:anlan", "FATHER_OF", "person:moxi", 3, source_pericope_id=""),
        _anchored("person:anlan", "FATHER_OF", "person:moxi", "num:26:0", 59, ["num:26:0"], 1),
        _row("person:anan", "SON_OF", "person:shuoba", 4, source_pericope_id="1ch:1:3"),
        _anchored("person:anan", "SON_OF", "person:shuoba", "1ch:1:3", 40, ["1ch:1:3", "gen:36:1"], 2))]
    results = []
    for shift in range(len(given)):
        flow = pp.Flow()
        kept = pp.drop_inverse(given[shift:] + given[:shift], inputs, cfg, flow)
        results.append((pp.collapse_by_key(kept, inputs, cfg, flow), flow.collapsed))
    assert all(result == results[0] for result in results)
    rows, collapsed = results[0]
    assert [(*_triple(r), r["source"], r["extraction_phase"], r["source_pericope_id"], r.get("verse"))
            for r in rows] == [
        ("person:anan", "SON_OF", "person:shuoba", "llm", 4, "1ch:1:3", None),
        ("person:anlan", "FATHER_OF", "person:moxi", "prior", 3, "", None),
        ("person:bianyamin", "SON_OF", "person:lajie", "llm", 4, "gen:35:1", None),
        ("person:bianyamin", "SON_OF", "person:yage", "llm", 4, "gen:35:1", None),
        ("person:dawei", "SON_OF", "person:yexi", "anchored_rule", 6, "1ch:29:2", 26),
        ("person:yage", "SON_OF", "person:yisa", "llm", 4, "gen:28:1", None),
        ("person:yexi", "FATHER_OF", "person:dawei", "prior", 3, "", None)]   # the other encoding: its own key
    assert [(r["sources"], r["support_pericopes"], r["evidence_count"]) for r in rows] == [
        (["anchored_rule", "llm"], ["1ch:1:3", "gen:36:1"], 3), (["anchored_rule", "prior"], ["num:26:0"], 2),
        (["llm"], ["gen:35:1"], 1), (["llm"], ["gen:35:1"], 1), (["anchored_rule"], ["1ch:29:2", "luk:3:2"], 2),
        (["llm"], ["gen:28:1"], 1), (["prior"], [], 1)]
    assert collapsed == {"anchored_rule+llm": 1, "anchored_rule+prior": 1}


# --- stamp_provenance (REL-04, REL-09; K5/D4, D12) ------------------------------

def test_rows_carry_provenance_and_no_confidence(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "in")
    _append_jsonl(tmp_path / "in" / "relations.jsonl", [
        _row("person:moxi", "SUCCEEDED_BY", "person:yalun", None, source="curated", source_pericope_id=""),
        _row("person:nahe", "DIED_IN", "place:wuer", 4, source_pericope_id="gen:11:1", confidence=0.7,
             run_id="re-test", model="test-model")])
    rows, report = _run("all", _paths(tmp_path / "in"))
    assert report["rules"]["ran"][-1] == "stamp_provenance"

    # K5: no row keeps `confidence`, Step 6's lookup constant; the value a row came with is its
    # confidence_raw, null on an anchored row (the rule has none) until 2A calibrates (D4)
    assert not any("confidence" in r for r in rows)
    assert all({"source", "pp_version", "schema_version", "run_id", "confidence_raw"} <= set(r) for r in rows)
    # the phase is the source's; Step 6's 2026-05 rows (prior, llm) carry its legacy run and the
    # llm ones model 'unknown' (D12), a row whose run recorded itself keeps that; every other row
    # (anchored, curated) is this 6.05 run's, the report's run_id
    legacy, this_run = "legacy-re-2026-05", report["run_id"]
    assert Counter((r["source"], r["extraction_phase"], r["run_id"], r.get("model"), r["confidence_raw"])
                   for r in rows) == {
        ("prior", 3, legacy, None, 0.99): 1, ("llm", 4, legacy, "unknown", 0.65): 5,
        ("llm", 4, "re-test", "test-model", 0.7): 1, ("anchored_rule", 6, this_run, None, None): 6,
        ("curated", None, this_run, None, None): 1}

    # none mode stamps nothing more: the K8 control keeps confidence and gains no run_id
    none_rows, _ = _run("none")
    assert all("confidence" in r and "run_id" not in r for r in none_rows)
