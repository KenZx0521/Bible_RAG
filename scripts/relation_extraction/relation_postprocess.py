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
adds the sha256 of the inputs actually read). All mode's last rule,
stamp_provenance, adds run_id, model and confidence_raw, and removes
`confidence`.

Determinism: the output is a function of the input bytes and PP_FILES only.
Rows are sorted by (head_id, relation, tail_id), one
json.dumps(sort_keys=True, ensure_ascii=False) per line, with no timestamps;
the report has sorted keys and sorted lists. The jsonl is written first, then the
report, each through a temp file and os.replace. An input error (an endpoint
missing from entities.jsonl, a row with no known source, an unreadable
file) stops the run before anything is written, as does a key that all mode
leaves with two rows (6.1 makes one edge per key).

The report (relations_postprocess_report/v1) records pp_version,
schema_version, the rules, run_id ('6.05-' and 12 hex of sha256(pp_version +
the input sha256s in INPUTS order)), every input's {path, sha256, rows}, the
flow {input, drops {reason: {relation: n}}, drops_due_to_dan_filter
{relation: n}, anchored, flagged, collapsed_keys {sources: n}, output}, the
conflicts, the output {path, sha256, rows, by_source, by_relation} (rows
counted by their primary source) and expected_after_10_2: the edge set
the graph holds once 10.2 has DETACH DELETEd the generic Event nodes.
scripts/tools/check_edge_set.py compares staging with that section through
edge_set_sha256 and by_ee_key.

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

from . import anchored_rules, relation_policy
from .anchored_rules import AnchoredConfig
from .models import PHASE_OF_SOURCE, SOURCES
from .relation_policy import source_of
from .schema_loader import RelationSchema

try:  # imported as scripts.relation_extraction (run with -m from the repo root)
    from ..entity_extraction import entity_overrides, geo_rules
    from ..entity_extraction.stoplists import GENERIC_EVENT_STOPLIST
except ImportError:  # imported as relation_extraction (scripts/ on sys.path)
    from entity_extraction import entity_overrides, geo_rules
    from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST

ROOT = Path(__file__).resolve().parents[2]
REPORT_FORMAT = "relations_postprocess_report/v1"
MODES = ("all", "none")
# The rows whose parents the anchored same-name guard reads (rules_to_anchored).
GUARD_SOURCES = ("curated", "prior", "llm")
# The rows provenance_gate passes without co-mention support (G-3).
GATE_EXEMPT = ("curated", "prior")
# The rows of an id-order relation whose direction flag_id_order takes as verified.
DIRECTION_VERIFIED = ("curated", "prior")
# The rows Step 6's 2026-05 run wrote, and the run and model stamp_provenance gives them (D12).
LEGACY_SOURCES = ("prior", "llm")
LEGACY_RUN_ID = "legacy-re-2026-05"
LEGACY_MODEL = "unknown"
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
    dan_filter_drops: Counter = field(default_factory=Counter)  # gate drops the 「但」 filter caused
    anchored: dict = field(default_factory=dict)
    flagged: Counter = field(default_factory=Counter)          # relation counts
    collapsed: Counter = field(default_factory=Counter)        # 'llm+prior' -> keys made of 2+ rows
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


def rules_to_anchored(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-01: drop every phase-2 rule row and add the anchored kinship rows in their place.

    The rule rows took their direction from id order (羅得 FATHER_OF 他拉); all
    go, under drops.rule. With anchored_rules.yaml enabled, anchored_rules.run
    then reads the verses (lexicon and span map from the mentions under final
    types, the same-name guard's parents from the curated, prior and llm rows
    left; a rule or inverse row is never a parent), its hits collapse to one row
    per key (_anchored_rows), and its guard conflicts go to the report. With
    enabled: false, the pre-registered K9 fallback, no anchored row is added.
    """
    kept = []
    for row in rows:
        if row["source"] == "rule":
            flow.drop("rule", row)
        else:
            kept.append(row)
    if not cfg.anchored.enabled:
        flow.anchored = {"enabled": False}
        return kept
    hits, stats, conflicts = _anchored_hits(kept, inputs, cfg)
    made = [base_stamp(row, cfg) for row in _anchored_rows(hits, inputs.entities)]
    flow.anchored = _anchored_flow(stats, made)
    flow.conflicts.extend(conflicts)
    return kept + made


def _anchored_hits(rows: list[dict], inputs: Inputs, cfg: Config) -> tuple[list[dict], dict, list[dict]]:
    """anchored_rules.run over the pericopes: (hits, stats plus foreign_surface_skipped, conflicts)."""
    final_types = _final_types(inputs, cfg)
    lexicon = anchored_rules.build_lexicon(inputs.entities, final_types, inputs.mentions, cfg.anchored)
    span_map, skipped = anchored_rules.build_span_map(inputs.entities, final_types, inputs.mentions,
                                                      inputs.chunk_parent, cfg.anchored)
    parent_map = anchored_rules.parent_map_of((row["head_id"], row["relation"], row["tail_id"])
                                              for row in rows if row["source"] in GUARD_SOURCES)
    hits, stats, conflicts = anchored_rules.run(inputs.pericopes, span_map,
                                                anchored_rules.compile_tokenizer(lexicon), cfg.anchored,
                                                parent_map)
    return hits, {**stats, "foreign_surface_skipped": skipped}, conflicts


def _anchored_rows(hits: list[dict], entities: Mapping[str, Mapping]) -> list[dict]:
    """One anchored_rule row per (head, relation, tail), in key order.

    The primary hit, the smallest (source_pericope_id, verse), gives the
    pericope, verse, evidence_span and pattern (notes); support_pericopes keeps
    every hit's pericope and evidence_count counts the distinct (pericope, verse).
    """
    by_key: dict[tuple[str, str, str], list[dict]] = {}
    for hit in hits:
        by_key.setdefault((hit["head_id"], hit["relation"], hit["tail_id"]), []).append(hit)
    rows = []
    for (head, relation, tail), group in sorted(by_key.items()):
        primary = min(group, key=lambda hit: (hit["source_pericope_id"], hit["verse"]))
        rows.append({
            "head_id": head, "relation": relation, "tail_id": tail,
            "source": "anchored_rule", "extraction_phase": PHASE_OF_SOURCE["anchored_rule"],
            "notes": primary["pattern"], "source_pericope_id": primary["source_pericope_id"],
            "verse": primary["verse"], "evidence_span": primary["evidence_span"],
            "head_canonical": entities[head]["canonical_name"],
            "tail_canonical": entities[tail]["canonical_name"],
            "support_pericopes": sorted({hit["source_pericope_id"] for hit in group}),
            "evidence_count": len({(hit["source_pericope_id"], hit["verse"]) for hit in group}),
        })
    return rows


def _anchored_flow(stats: Mapping, rows: list[dict]) -> dict:
    """flow.anchored: run()'s stats, unique_keys and the sha256 of the sorted 'head\\trel\\ttail' lines."""
    lines = sorted(f"{row['head_id']}\t{row['relation']}\t{row['tail_id']}" for row in rows)
    return {
        "enabled": True,
        "pattern_hits": stats["pattern_hits"], "by_pattern": dict(stats["by_pattern"]),
        "guard_other_parent": stats["guard_other_parent"], "guard_homonym": stats["guard_homonym"],
        "disagreement_children": stats["anchored_disagreement_children"],
        "disagreement_abstain": stats["anchored_disagreement_abstain"],
        "emitted_hits": stats["emitted_hits"], "emitted_by_pattern": dict(stats["emitted_by_pattern"]),
        "unique_keys": len(rows), "foreign_surface_skipped": stats["foreign_surface_skipped"],
        "ambiguous_name": stats["ambiguous_name"],   # report-only
        "key_set_sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(),
    }


def drop_llm_event_event(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-08, EV-10: drop every llm row whose two endpoints both have final type Event.

    The LLM's Event–Event edges (PRECEDED_BY, CAUSED) come from pairs mined
    within one pericope and are mostly noise; the off-by-default entity_path
    walks them generically. Every Event–Event row Step 6 writes is the LLM's,
    so 6.05 emits none; a timeline, if one is ever wanted, is a curated file.
    A prior or curated row between two events is not the LLM's and stays.
    """
    final_types = _final_types(inputs, cfg)
    kept = []
    for row in rows:
        if row["source"] == "llm" and final_types[row["head_id"]] == final_types[row["tail_id"]] == "Event":
            flow.drop("llm_event_event", row)
        else:
            kept.append(row)
    return kept


def domain_range(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """G-2: drop every row the schema does not accept for its endpoints' final types.

    The types are those the graph holds once 10.2 has relabelled it: the
    entities.jsonl type through the curated overrides (耶和華 is extracted as a
    Group and kept as a Person, so a Person LEADER_OF it goes). Every source is
    checked, prior and curated included. accepts_pair reads an undirected
    relation both ways. A relation the schema does not know goes under its own
    key, unknown_relation; the two keys are H9's two metrics.
    """
    final_types = _final_types(inputs, cfg)
    kept = []
    for row in rows:
        entry = cfg.schema.get(row["relation"])
        if entry is None:
            flow.drop("unknown_relation", row)
        elif not entry.accepts_pair(final_types[row["head_id"]], final_types[row["tail_id"]]):
            flow.drop("domain_range", row)
        else:
            kept.append(row)
    return kept


def provenance_gate(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-05, M3: drop every row whose two endpoints are not both mentioned in its pericope.

    The support is the MENTIONS layer as it stands after 10.2: (pericope,
    entity_id) over entity_mentions.jsonl (_support). A row with no
    source_pericope_id has none. curated and prior rows are exempt (G-3): a
    prior cites a verse, not a pericope. A drop that only the 「但」 filter
    caused, one the unfiltered mentions would support, is also counted in
    flow.dan_filter_drops.
    """
    supported, unfiltered = _support(inputs)
    kept = []
    for row in rows:
        if row["source"] in GATE_EXEMPT or _supported(row, supported):
            kept.append(row)
            continue
        flow.drop("provenance_gate", row)
        if _supported(row, unfiltered):
            flow.dan_filter_drops[row["relation"]] += 1
    return kept


def _support(inputs: Inputs) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """({(pericope, entity_id)} after the 10.2 「但」 filter, the same without it).

    A mention counts for its pericope (anchored_rules.pericope_of: a verse row
    split at ':v:', a chunk row rolled up to its parent), as import_neo4j
    anchors it. The filter keys a row as action_dan compares s.id, by
    source_id split at ':v:', so a chunk row by its chunk id, not the parent.
    """
    keep = geo_rules.dan_keep_sources(inputs.mentions)
    supported, unfiltered = set(), set()
    for mention in inputs.mentions:
        pair = (anchored_rules.pericope_of(mention, inputs.chunk_parent), mention["entity_id"])
        unfiltered.add(pair)
        if geo_rules.keeps_dan_mention(mention["entity_id"], mention["source_id"].split(":v:")[0], keep):
            supported.add(pair)
    return supported, unfiltered


def _supported(row: Mapping, support: set[tuple[str, str]]) -> bool:
    pid = row.get("source_pericope_id")
    return bool(pid) and (pid, row["head_id"]) in support and (pid, row["tail_id"]) in support


def flag_id_order(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-03: mark the llm rows of id-order relations direction-unverified; drop those a prior reverses.

    An id-order relation (schema.id_order_relations(): CAUSED, LOCATED_IN,
    PRECEDED_BY, SUCCEEDED_BY) is directed with one type at both ends and in no
    direction pair, so only head/tail order says which way a row reads, and
    the LLM's rows have their ends in id order (head < tail on every one). An
    llm row whose reverse is a prior row goes, under contradicts_prior
    (加利利 LOCATED_IN 拿撒勒 against 路 1:26); every other gets
    direction_verified: false, counted in flow.flagged, and stays for
    undirected walks. The prior and curated rows of these relations get
    direction_verified: true. No other row gets the field.
    """
    id_order = cfg.schema.id_order_relations()
    prior_keys = {(row["head_id"], row["relation"], row["tail_id"]) for row in rows if row["source"] == "prior"}
    kept = []
    for row in rows:
        if row["relation"] in id_order and row["source"] in DIRECTION_VERIFIED:
            kept.append({**row, "direction_verified": True})
        elif row["relation"] not in id_order or row["source"] != "llm":
            kept.append(row)
        elif (row["tail_id"], row["relation"], row["head_id"]) in prior_keys:
            flow.drop("contradicts_prior", row)
        else:
            flow.flagged[row["relation"]] += 1
            kept.append({**row, "direction_verified": False})
    return kept


def resolve_kinship_direction(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-01/02, R6: keep one direction per parent/child pair, the best-ranked row's.

    FATHER_OF, MOTHER_OF, SON_OF and DAUGHTER_OF each say who is whose parent;
    two rows that say it both ways cannot both hold (R6's contradictions).
    relation_policy.resolve_kinship_direction picks the direction by source
    rank, curated > prior > llm > anchored_rule, then the smallest
    (source_pericope_id, verse, head_id), never by file order. Each row of the
    other direction goes under kin_direction_conflict and is logged in the
    report's conflicts with the row that won.
    """
    kept, conflicts = relation_policy.resolve_kinship_direction(rows)
    for conflict in conflicts:
        flow.drop(relation_policy.KIN_DIRECTION_CONFLICT, conflict)
    flow.conflicts.extend(conflicts)
    return kept


def dedup_undirected(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-01/02: keep one row per pair of an undirected relation (SPOUSE_OF, SIBLING_OF, NEAR…).

    A pair stated both ways, or twice one way by two sources, is one fact;
    relation_policy.dedup_undirected keeps the best-ranked row in its own
    orientation (the same order as resolve_kinship_direction) and the rest
    go under undirected_duplicate.
    """
    kept, dropped = relation_policy.dedup_undirected(rows, cfg.schema)
    for row in dropped:
        flow.drop("undirected_duplicate", row)
    return kept


def collapse_by_key(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-10 (SON_OF onCreate-only, part 1): leave one row per (head_id, relation, tail_id).

    6.1 merges one edge per key, so two rows of a key leave the edge with
    whichever row's properties the import kept (batch 0: 雅各 SON_OF 以撒 is
    phase 5 on prod, phase 4 on staging). relation_policy.collapse_by_key keeps
    the key's best-ranked row, in the order of the two rules before it, and
    folds every row of the key into sources, support_pericopes and
    evidence_count, which all rows get (W1: the anchored rule repeats 5 llm keys
    and 2 priors). 6.1 overwriting an edge's properties wholesale is part 2
    (1A-C5a). A key made of two or more rows is counted in flow.collapsed by its
    sources ('anchored_rule+llm').
    """
    collapsed, merged = relation_policy.collapse_by_key(rows)
    flow.collapsed.update("+".join(row["sources"]) for row in merged)
    return collapsed


def stamp_provenance(rows: list[dict], inputs: Inputs, cfg: Config, flow: Flow) -> list[dict]:
    """REL-04, REL-09: every row says which run wrote it; K5: `confidence` gives way to confidence_raw.

    extraction_phase becomes its source's (PHASE_OF_SOURCE; a curated row
    has none). The prior and llm rows are Step 6's 2026-05 run, which
    recorded neither run nor model: run_id LEGACY_RUN_ID and, on an llm row,
    model 'unknown' (D12). Every other row, an anchored one (or curated), is
    this run's, the report's run_id. A row that records its own run_id or
    model keeps it. confidence_raw is the confidence the row came with (the
    lookup constant of Step 6's phase), null on an anchored row; the
    `confidence` key goes, until 2A writes a calibrated one (D4). The rows are
    copies.
    """
    this_run = run_id(cfg.pp_version, inputs.files)
    return [_provenance(row, this_run) for row in rows]


def _provenance(row: Mapping, this_run: str) -> dict:
    source = row["source"]
    stamped = {key: value for key, value in row.items() if key != "confidence"}
    stamped.update(extraction_phase=PHASE_OF_SOURCE.get(source), confidence_raw=row.get("confidence"),
                   run_id=row.get("run_id") or (LEGACY_RUN_ID if source in LEGACY_SOURCES else this_run))
    if source == "llm":
        stamped["model"] = row.get("model") or LEGACY_MODEL
    return stamped


def _final_types(inputs: Inputs, cfg: Config) -> dict[str, str]:
    """entity_id -> final type: the entities.jsonl type through the curated overrides."""
    return {eid: entity_overrides.final_type(eid, entity["type"], cfg.overrides)
            for eid, entity in inputs.entities.items()}


RULES: tuple[tuple[str, Rule], ...] = (
    ("drop_inverse", drop_inverse),
    ("rules_to_anchored", rules_to_anchored),
    ("drop_llm_event_event", drop_llm_event_event),
    ("domain_range", domain_range),
    ("provenance_gate", provenance_gate),
    ("flag_id_order", flag_id_order),
    ("resolve_kinship_direction", resolve_kinship_direction),
    ("dedup_undirected", dedup_undirected),
    ("collapse_by_key", collapse_by_key),
    ("stamp_provenance", stamp_provenance),
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


def _check_unique_keys(rows: list[dict]) -> None:
    """All mode hands 6.1 one row per key (collapse_by_key); a key left twice is a bug, not a row to merge."""
    counts = Counter((row["head_id"], row["relation"], row["tail_id"]) for row in rows)
    dup = sorted(" ".join(key) for key, n in counts.items() if n > 1)
    if dup:
        raise ValueError(f"{len(dup)} key(s) have two or more rows after the rules: "
                         f"{', '.join(dup[:10])}{' ...' if len(dup) > 10 else ''}")


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
    if rules == "all":
        _check_unique_keys(rows)
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
                 "drops_due_to_dan_filter": dict(sorted(flow.dan_filter_drops.items())),
                 "anchored": dict(flow.anchored), "flagged": dict(sorted(flow.flagged.items())),
                 "collapsed_keys": dict(sorted(flow.collapsed.items())), "output": len(rows)},
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
