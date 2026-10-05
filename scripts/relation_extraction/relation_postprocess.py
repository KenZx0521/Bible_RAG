"""Step 6.05: post-process relations.jsonl into relations_clean.jsonl (batch 1A).

Step 6 (extract_relations) writes every row its phases produce: id-order rule
rows (phase 2), priors (3), LLM rows (4) and materialised inverses (5), and
6.1 imported them as they were. 6.05 sits in between. It runs offline (no
database, no kg_target): an ordered list of cleanup rules over the rows,
written to output/relations_clean.jsonl, the file 6.1 imports, plus a report.

RULES run in this order, one commit each (1A-C4b..C4j); the order is that of
docs/records/2026-10-04_kg_fix/batch1/planner_1A/sim_1a.py:59-196, where
domain_range and provenance_gate commute on real data:

    drop_inverse, rules_to_anchored, drop_llm_event_event, domain_range,
    provenance_gate, flag_id_order, resolve_kinship_direction,
    dedup_undirected, collapse_by_key, stamp_provenance

`--rules none` runs none of them: every input row comes out with the base
stamp and nothing else changed, the input of the K8 staging-P1 control. The
base stamp (both modes) is source (the row's own, else derived from its
phase), schema_version (the relation schema's version) and pp_version ('pp-'
and 12 hex of the sha256 of the code and repo config in PP_FILES; run_id
adds the sha256 of the inputs actually read).

Determinism: the output is a function of the input bytes and PP_FILES only.
Rows are sorted by (head_id, relation, tail_id), one
json.dumps(sort_keys=True, ensure_ascii=False) per line, with no timestamps;
the report has sorted keys and sorted lists. The jsonl is written first, then the
report, each through a temp file and os.replace. An input error (an endpoint
missing from entities.jsonl, a row with no known source, an unreadable
file) stops the run before anything is written.

The report (relations_postprocess_report/v1) records pp_version,
schema_version, the rules, run_id ('6.05-' and 12 hex of sha256(pp_version +
the input sha256s in INPUTS order)), every input's {path, sha256, rows}, the
flow {input, drops {reason: {relation: n}}, anchored, flagged, output}, the
conflicts, the output {path, sha256, rows, by_source, by_relation} and
expected_after_10_2: the edge set the graph holds once 10.2 has DETACH
DELETEd the generic Event nodes. scripts/tools/check_edge_set.py compares
staging with that section through edge_set_sha256 and by_ee_key.

Usage (from the project root):
    scripts/.venv/bin/python -m scripts.relation_extraction.relation_postprocess
    scripts/.venv/bin/python -m scripts.relation_extraction.relation_postprocess --rules none

Exit codes: 0 written; 1 an input error, nothing written; 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import anchored_rules
from .anchored_rules import AnchoredConfig
from .models import SOURCES
from .relation_policy import source_of
from .schema_loader import RelationSchema

try:  # imported as scripts.relation_extraction (run with -m from the repo root)
    from ..entity_extraction import entity_overrides
    from ..entity_extraction.stoplists import GENERIC_EVENT_STOPLIST
except ImportError:  # imported as relation_extraction (scripts/ on sys.path)
    from entity_extraction import entity_overrides
    from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST

ROOT = Path(__file__).resolve().parents[2]
REPORT_FORMAT = "relations_postprocess_report/v1"
MODES = ("all", "none")
# The input files, in the order their sha256s enter run_id.
INPUTS = ("relations", "entities", "mentions", "chunks", "pericopes", "overrides", "anchored_config", "schema")
_DEFAULT_PATHS = {
    "relations": ROOT / "output" / "relations.jsonl",
    "entities": ROOT / "output" / "entities.jsonl",
    "mentions": ROOT / "output" / "entity_mentions.jsonl",
    "chunks": ROOT / "output" / "chunks.jsonl",
    "pericopes": ROOT / "output" / "pericopes.jsonl",
    "overrides": entity_overrides.OVERRIDES_PATH,
    "anchored_config": anchored_rules.CONFIG_PATH,
    "schema": ROOT / "config" / "relations" / "biblical_relations.yaml",
}
DEFAULT_OUT = ROOT / "output" / "relations_clean.jsonl"
DEFAULT_REPORT = ROOT / "output" / "relations_clean.report.json"
# Everything whose change can change the output, relative to ROOT (pp_version).
PP_FILES = (
    "scripts/relation_extraction/relation_postprocess.py",
    "scripts/relation_extraction/relation_policy.py",
    "scripts/relation_extraction/anchored_rules.py",
    "scripts/relation_extraction/models.py",
    "scripts/relation_extraction/schema_loader.py",
    "scripts/entity_extraction/geo_rules.py",
    "scripts/entity_extraction/stoplists.py",
    "scripts/entity_extraction/entity_overrides.py",
    "config/relations/anchored_rules.yaml",
    "config/relations/biblical_relations.yaml",
    "config/curated/entity_overrides.yaml",
)


@dataclass(frozen=True)
class Inputs:
    """The parsed JSONL inputs, plus every input file's {path, sha256, rows}."""

    relations: list[dict]
    entities: dict[str, dict]          # entity_id -> entities.jsonl row
    mentions: list[dict]               # entity_mentions.jsonl rows, file order
    chunk_parent: dict[str, str]       # chunk id -> pericope id
    pericopes: list[dict]              # pericopes.jsonl rows, file order
    files: dict[str, dict]


@dataclass(frozen=True)
class Config:
    schema: RelationSchema
    overrides: dict[str, dict[str, str]]
    anchored: AnchoredConfig
    pp_version: str


@dataclass
class Flow:
    """What the rules did, for the report's flow and conflicts."""

    drops: dict[str, Counter] = field(default_factory=dict)   # reason -> relation counts
    anchored: dict = field(default_factory=dict)
    flagged: Counter = field(default_factory=Counter)          # relation counts
    conflicts: list[dict] = field(default_factory=list)

    def drop(self, reason: str, row: Mapping) -> None:
        self.drops.setdefault(reason, Counter())[row["relation"]] += 1


# A rule takes the rows and returns the rows it keeps or makes; it records what
# it dropped, flagged or logged in the Flow. Rows it makes go through base_stamp.
Rule = Callable[[list[dict], Inputs, Config, Flow], list[dict]]


# --- rules --------------------------------------------------------------------

def drop_inverse(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-02: drop every row whose source is inverse, R5's materialised reverse of a directed row.

    Each restates its forward row with head and tail swapped. entity_path walks
    edges undirected (entity_path_retriever's -[r*1..N]-), so the pair stays
    connected and the drop only frees LIMIT slots. A phase-5 cooccurrence
    backfill (10.3) is not an inverse and is not this rule's.
    """
    kept = []
    for row in rows:
        if row["source"] == "inverse":
            flow.drop("inverse", row)
        else:
            kept.append(row)
    return kept


RULES: tuple[tuple[str, Rule], ...] = (
    ("drop_inverse", drop_inverse),
)


def default_paths() -> dict[str, Path]:
    return dict(_DEFAULT_PATHS)


def pp_version(root: Path = ROOT) -> str:
    """'pp-' and 12 hex of the sha256 over each PP_FILES path and its bytes, by path."""
    digest = hashlib.sha256()
    for rel in sorted(PP_FILES):
        data = (root / rel).read_bytes()
        digest.update(f"{rel}\n{len(data)}\n".encode("utf-8"))
        digest.update(data)
    return "pp-" + digest.hexdigest()[:12]


# --- inputs -------------------------------------------------------------------

def _display(path: Path) -> str:
    """The path relative to ROOT when inside it, so a report does not depend on the checkout."""
    absolute = Path(os.path.abspath(path))
    try:
        return absolute.relative_to(ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _file_meta(path: Path, data: bytes, rows: int | None) -> dict:
    return {"path": _display(path), "sha256": hashlib.sha256(data).hexdigest(), "rows": rows}


def _read_jsonl(path: Path) -> tuple[list[dict], dict]:
    data = Path(path).read_bytes()
    rows = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return rows, _file_meta(path, data, len(rows))


def _load_schema(path: Path) -> RelationSchema:
    schema = RelationSchema.load(Path(path))
    if schema.version is None:
        raise ValueError(f"{path}: the relation schema has no top-level version")
    return schema


def load_inputs(paths: Mapping[str, Path]) -> tuple[Inputs, Config]:
    """Read and validate every input; ValueError or OSError on a malformed or missing one."""
    files: dict[str, dict] = {}
    parsed: dict[str, list[dict]] = {}
    for name in ("relations", "entities", "mentions", "chunks", "pericopes"):
        parsed[name], files[name] = _read_jsonl(paths[name])
    for name in ("overrides", "anchored_config", "schema"):
        files[name] = _file_meta(paths[name], Path(paths[name]).read_bytes(), None)
    cfg = Config(schema=_load_schema(paths["schema"]),
                 overrides=entity_overrides.load_overrides(paths["overrides"]),
                 anchored=anchored_rules.load_config(paths["anchored_config"]),
                 pp_version=pp_version())
    inputs = Inputs(relations=parsed["relations"],
                    entities={row["entity_id"]: row for row in parsed["entities"]},
                    mentions=parsed["mentions"],
                    chunk_parent={row["id"]: row["parent_id"] for row in parsed["chunks"]},
                    pericopes=parsed["pericopes"], files=files)
    return inputs, cfg


# --- core ---------------------------------------------------------------------

def _key(row: Mapping) -> str:
    return f"{row['head_id']} {row['relation']} {row['tail_id']}"


def base_stamp(row: Mapping, cfg: Config) -> dict:
    """A copy of the row with source, schema_version and pp_version set (both modes)."""
    source = source_of(row)
    if source not in SOURCES:
        raise ValueError(f"{_key(row)}: no known source (source {row.get('source')!r}, "
                         f"extraction_phase {row.get('extraction_phase')!r})")
    return {**row, "source": source, "schema_version": cfg.schema.version, "pp_version": cfg.pp_version}


def _check_endpoints(rows: list[dict], entities: Mapping[str, dict], what: str) -> None:
    bad = [row for row in rows if row["head_id"] not in entities or row["tail_id"] not in entities]
    if bad:
        missing = sorted({eid for row in bad for eid in (row["head_id"], row["tail_id"])
                          if eid not in entities})
        raise ValueError(f"{len(bad)} {what} row(s) have an endpoint missing from entities.jsonl: "
                         f"{', '.join(missing[:10])}{' ...' if len(missing) > 10 else ''}")


def _line(row: Mapping) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def serialize(rows: Iterable[Mapping]) -> bytes:
    """The relations_clean.jsonl bytes of rows already in output order."""
    return "".join(_line(row) + "\n" for row in rows).encode("utf-8")


def postprocess(inputs: Inputs, cfg: Config, rules: str = "all") -> tuple[list[dict], dict]:
    """(rows in output order, report without output.path); ValueError on an input error."""
    if rules not in MODES:
        raise ValueError(f"rules must be one of {list(MODES)}, got {rules!r}")
    _check_endpoints(inputs.relations, inputs.entities, "input")
    rows = [base_stamp(row, cfg) for row in inputs.relations]
    selected = RULES if rules == "all" else ()
    flow = Flow()
    for _, rule in selected:
        rows = rule(rows, inputs, cfg, flow)
    _check_endpoints(rows, inputs.entities, "output")
    rows = sorted(rows, key=lambda row: (row["head_id"], row["relation"], row["tail_id"], _line(row)))
    return rows, build_report(rows, inputs, cfg, rules, [name for name, _ in selected], flow)


# --- report -------------------------------------------------------------------

def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _v(value) -> str:
    """A property as diff_kg prints it in keys: unset is '-'."""
    return "-" if value is None else str(value)


def edge_set_lines(rows: Iterable[Mapping]) -> list[str]:
    """Sorted 'head\\trelation\\ttail\\tsource' lines (rows keyed head_id, relation, tail_id, source)."""
    return sorted(f"{r['head_id']}\t{r['relation']}\t{r['tail_id']}\t{_v(r.get('source'))}" for r in rows)


def edge_set_sha256(rows: Iterable[Mapping]) -> str:
    """sha256 of the edge_set_lines joined by '\\n', no trailing newline."""
    return hashlib.sha256("\n".join(edge_set_lines(rows)).encode("utf-8")).hexdigest()


def by_ee_key(rows: Iterable[Mapping]) -> dict[str, int]:
    """Edge counts per diff_kg ee_edges key, 'TYPE phase=P source=S'."""
    return _counts(f"{r['relation']} phase={_v(r.get('extraction_phase'))} source={_v(r.get('source'))}"
                   for r in rows)


def generic_event_ids(entities: Mapping[str, Mapping]) -> list[str]:
    """The Event ids 10.2 deletes: canonical_name in GENERIC_EVENT_STOPLIST.

    The entities.jsonl type, not the final one: 10.2 runs generic-events
    before the yehehua relabel, so the Event label is still the imported one.
    """
    stop = set(GENERIC_EVENT_STOPLIST)
    return sorted(eid for eid, entity in entities.items()
                  if entity.get("type") == "Event" and entity.get("canonical_name") in stop)


def expected_after_10_2(rows: list[dict], entities: Mapping[str, Mapping]) -> dict:
    generic = generic_event_ids(entities)
    gone = set(generic)
    after = [row for row in rows if row["head_id"] not in gone and row["tail_id"] not in gone]
    return {"generic_event_ids": generic, "edges_on_generic_events": len(rows) - len(after),
            "edges": len(after), "edge_set_sha256": edge_set_sha256(after),
            "by_ee_key": by_ee_key(after), "by_type": _counts(row["relation"] for row in after)}


def run_id(pp: str, files: Mapping[str, Mapping]) -> str:
    material = pp + "".join(files[name]["sha256"] for name in INPUTS)
    return "6.05-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def build_report(rows: list[dict], inputs: Inputs, cfg: Config, mode: str, ran: list[str],
                 flow: Flow) -> dict:
    return {
        "format": REPORT_FORMAT,
        "pp_version": cfg.pp_version,
        "schema_version": cfg.schema.version,
        "rules": {"mode": mode, "ran": ran},
        "run_id": run_id(cfg.pp_version, inputs.files),
        "inputs": {name: dict(meta) for name, meta in inputs.files.items()},
        "flow": {"input": len(inputs.relations),
                 "drops": {reason: dict(sorted(n.items())) for reason, n in flow.drops.items()},
                 "anchored": dict(flow.anchored), "flagged": dict(sorted(flow.flagged.items())),
                 "output": len(rows)},
        "conflicts": sorted(flow.conflicts, key=_line),
        "output": {"path": None, "sha256": hashlib.sha256(serialize(rows)).hexdigest(), "rows": len(rows),
                   "by_source": _counts(row["source"] for row in rows),
                   "by_relation": _counts(row["relation"] for row in rows)},
        "expected_after_10_2": expected_after_10_2(rows, inputs.entities),
    }


# --- output -------------------------------------------------------------------

def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_outputs(rows: list[dict], report: dict, out: Path, report_path: Path) -> dict:
    """Write the jsonl, then the report with output.path set; the report as written."""
    data = serialize(rows)
    if hashlib.sha256(data).hexdigest() != report["output"]["sha256"]:
        raise RuntimeError("rows changed after the report was built")
    report = {**report, "output": {**report["output"], "path": _display(out)}}
    _write_atomic(Path(out), data)
    text = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    _write_atomic(Path(report_path), text.encode("utf-8"))
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 6.05: post-process relations.jsonl into relations_clean.jsonl "
                    "(offline, no database).")
    for name, path in _DEFAULT_PATHS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=Path, default=path,
                            help=f"default: {_display(path)}")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default: {_display(DEFAULT_OUT)}")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                        help=f"default: {_display(DEFAULT_REPORT)}")
    parser.add_argument("--rules", choices=MODES, default="all",
                        help="all (default): every rule in order; none: the base stamp only "
                             "(the K8 staging-P1 control)")
    return parser


def _summary(report: dict) -> str:
    flow, out, after = report["flow"], report["output"], report["expected_after_10_2"]
    return (f"6.05 --rules {report['rules']['mode']}: {flow['input']:,} -> {out['rows']:,} rows "
            f"{out['by_source']}\n"
            f"  after 10.2: {after['edges']:,} edges ({after['edges_on_generic_events']:,} on "
            f"{len(after['generic_event_ids'])} generic events), edge set {after['edge_set_sha256'][:12]}\n"
            f"  {report['run_id']} {report['pp_version']} -> {out['path']}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inputs, cfg = load_inputs({name: getattr(args, name) for name in INPUTS})
        rows, report = postprocess(inputs, cfg, args.rules)
    except (OSError, ValueError) as e:
        print(f"relation_postprocess: {e}; nothing written", file=sys.stderr)
        return 1
    print(_summary(write_outputs(rows, report, args.out, args.report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
