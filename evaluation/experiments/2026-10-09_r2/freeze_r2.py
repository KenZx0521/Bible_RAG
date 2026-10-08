"""Freeze the R2 evaluation's route-change slice before any R2 result exists (prereg.md).

An offline route simulation of every GT v2 question, never a retrieval metric:

* **R1** runs the R1 commit's code (``git show e7b1173:…``: ragcommon.routing v1,
  signal_detector, event_registry) on the R1 build's contracts;
* **R2** runs this checkout's code (ragcommon.routing v2, the R2 signal_detector
  and event_registry, the code the R2 image is built from) on the R2 build's;
* both read the question with the one verse parser (unchanged since R1: checked).

The intent LLM's outputs were never stored, so, as in reports/r2prep/sim_routes.py,
its contribution is inferred from the route the R1 arm actually took (the
``route`` of the given R1 runs; no metric is read) and carried over to R2 (RULES).
A question whose retrieval can change goes into one sub-slice per cause: its
route handler, its detected books, or its event lane's anchor preference. Their
union minus the two questions R1's verse parser already moved is C3's slice; the
disambiguation family is listed beside it (report only); the G-ANS subset is
frozen_r1.json's. ``frozen_r2.json`` is byte-deterministic (sorted keys and lists,
no timestamps) and records the sha256 of every input, this script included.
After writing it, pin its sha256 in src/r2_frozen.py FROZEN_R2_SHA256.

    python experiments/2026-10-09_r2/freeze_r2.py --r2-contracts <store>/contracts/<R2 build> \\
        --observed results_quick/<R1 L1>.json [results_quick/<R1 L2>.json]   (from evaluation/)
    … --check    exit 1 if frozen_r2.json differs from the re-derivation
"""
import argparse
import hashlib
import json
import subprocess
import sys
import types
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
HERE = SCRIPT.parent
EVAL_ROOT = HERE.parents[1]
REPO = EVAL_ROOT.parent
for _path in (EVAL_ROOT, REPO / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from src.config import settings  # noqa: E402
from src.gt_v2 import FREEZE_PATH, GT_V2_PATH, GtV2Error, load_ground_truth_v2  # noqa: E402
from src.heldout import HeldoutError, IdMap, id_map  # noqa: E402
from src.r1_frozen import FROZEN_R1_PATH, FrozenR1Error, load_frozen  # noqa: E402
from src.r2_frozen import SCHEMA, SLICE_KEY, SUB_SLICES  # noqa: E402

R1_COMMIT = "e7b117305003c25d6eff04d0022790c7e4a33e12"
R1_BUILD = "b20261008_6daa4f31"
OUT = HERE / "frozen_r2.json"
CODE = {"routing": "packages/ragcommon/routing.py",
        "signal_detector": "backend/utils/signal_detector.py",
        "event_registry": "backend/utils/retrieval/event_registry.py",
        "verse_parser": "backend/utils/verse_parser.py"}
EXCLUDED = ("TOPIC_QUESTION_034", "VERSE_LOOKUP_035")
REPORT_FAMILY = "disambiguation"
DENSE = ("R3", "R4", "R6")            # one handler, one set of weights (routes._dense_route)
LANE_ROUTES = ("R4", "R5")            # router._EVENT_REGISTRY_ROUTES
# What the intent LLM can add to the query-only signals, by the route it leads to.
LLM_ROUTE = {"R5": "xref", "R3": "persons", "R4": "event", "R6": "place"}
LLM_FLAG = {"persons": "has_multi_person", "event": "has_event_keyword", "place": "has_place"}

RULES = {
    "simulation": "per GT v2 question, query-only signals (intent '', no entities, no keywords) "
                  "under each arm's lexicon and router; R1's route is the modal route of the "
                  "observed R1 runs (ties: the earlier run) when one intent-LLM contribution "
                  "(cross_reference intent -> R5, persons -> R3, event -> R4, place -> R6) turns "
                  "R1's query-only route into it, and R2's is R2's query-only signals plus that "
                  "contribution; otherwise (unexplained, unobserved) both are query-only",
    "route": "the route handler differs: R1, R2, R5 and fallback each have their own; R3, R4 "
             "and R6 share one (routes._dense_route, one set of weights)",
    "books": "the detected book ids differ (book anchors, the multi-book pin)",
    "lane": "the event lane's anchor preference differs: on R4/R5 the triggered events in "
            "match_events order, their anchors concatenated, first occurrence kept (what one "
            "slot, rag_event_registry_slots=1, appends first that the top-k lacks); empty "
            "elsewhere",
    "union": "route ∪ books ∪ lane minus the excluded ids; the only set C3 scores",
    "excluded": "TOPIC_QUESTION_034, VERSE_LOOKUP_035: R1's verse parser already changed their "
                "routes (DOC 1 §7); they stay in C1/C2",
    "disambiguation": "GT v2 family disambiguation, listed with its simulation; report only",
    "gans_subset": "frozen_r1.json's gans_subset, unchanged",
}


class FreezeError(ValueError):
    """An input is not the one the prereg names, or does not have its shape."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    resolved = Path(path).resolve()
    return str(resolved.relative_to(REPO)) if resolved.is_relative_to(REPO) else str(resolved)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read {path}: {exc}") from None


# ---------------------------------------------------------------- the two arms

def git_source(path: str, commit: str = R1_COMMIT) -> str:
    return subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], check=True,
                          capture_output=True, text=True).stdout


def git_module(name: str, path: str, deps: Mapping[str, types.ModuleType] | None = None,
               commit: str = R1_COMMIT) -> types.ModuleType:
    """``path`` as of ``commit``, run as module ``name``; its imports of ``deps`` (module
    name → module) see those modules instead of this checkout's."""
    module = types.ModuleType(name)
    module.__file__ = f"{commit}:{path}"
    saved = {key: sys.modules.get(key) for key in deps or {}}
    sys.modules.update(deps or {})
    sys.modules[name] = module          # dataclasses look their module up while defining
    try:
        exec(compile(git_source(path, commit), module.__file__, "exec"), module.__dict__)
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return module


@dataclass(frozen=True)
class Arm:
    name: str
    lexicon: Any
    detect: Callable          # signal_detector.detect_signals of the arm's code
    select: Callable          # its select_route
    registry: tuple           # its event_registry.parse_registry of the contract
    match_events: Callable    # its event_registry.match_events
    book_ids: Mapping[str, str]
    book_names: tuple[str, ...]   # what its event lane masks (serving.context)
    to_ev: Mapping[str, str]      # reported event id -> R2's surviving ev id


def contracts_build(directory: Path) -> str:
    return _read_json(directory / "manifest.json")["build_id"]


def r1_arm(contracts: Path, ids: IdMap) -> Arm:
    routing = git_module("r1_ragcommon_routing", CODE["routing"])
    detector = git_module("r1_signal_detector", CODE["signal_detector"],
                          {"ragcommon.routing": routing})
    events = git_module("r1_event_registry", CODE["event_registry"])
    lexicon = routing.load_lexicon(contracts / "routing_lexicon.json")
    registry = events.parse_registry(_read_json(contracts / "event_registry.json"))
    book_ids = {b.full_name: b.book_id for b in lexicon.books}
    return Arm("R1", lexicon, detector.detect_signals, detector.select_route, registry,
               events.match_events, book_ids, tuple(book_ids),          # R1 masks full names
               {e.id: ids.canonical(e.event_id) for e in registry})


def r2_arm(contracts: Path, ids: IdMap) -> Arm:
    from ragcommon import routing
    from utils import signal_detector as detector
    from utils.retrieval import event_registry as events
    lexicon = routing.load_lexicon(contracts / "routing_lexicon.json")
    registry = events.parse_registry(_read_json(contracts / "event_registry.json"))
    return Arm("R2", lexicon, detector.detect_signals, detector.select_route, registry,
               events.match_events, {b.full_name: b.book_id for b in lexicon.books},
               lexicon.full_names,                         # serving.context.book_names
               {e.id: ids.canonical(e.id) for e in registry})


def check_verse_parser() -> None:
    """Both arms read questions with this checkout's parser, so it must be R1's."""
    path = CODE["verse_parser"]
    if (REPO / path).read_text(encoding="utf-8") != git_source(path):
        raise FreezeError(f"{path} changed since R1 ({R1_COMMIT[:7]}); the "
                          "simulation assumes one verse parser for both arms")


# ---------------------------------------------------------------- one question

def infer_llm(observed: str | None, r1_route: str, r1_with: Callable[[str], str]) -> str | None:
    """The intent LLM's contribution that turns R1's query-only route into the observed one
    (``r1_with(contribution)`` is R1's route with it): "" none (or no observation),
    "xref" / "persons" / "event" / "place", None unexplained."""
    if observed is None or observed == r1_route:
        return ""
    contrib = LLM_ROUTE.get(observed)
    return contrib if contrib is not None and r1_with(contrib) == observed else None


def with_llm(arm: Arm, signals: Any, contrib: str | None) -> str:
    """The arm's route for its query-only ``signals`` plus the LLM's contribution."""
    if contrib == "xref":
        return arm.select(signals, "cross_reference")
    flag = LLM_FLAG.get(contrib or "")
    return arm.select(replace(signals, **{flag: True}) if flag else signals, "")


def lane(arm: Arm, route: str, question: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(triggered R2 ev ids, anchor preference) of the arm's event lane on ``route``."""
    if route not in LANE_ROUTES:
        return (), ()
    hits = arm.match_events(question, arm.registry, arm.book_names)
    return (tuple(dict.fromkeys(arm.to_ev[e.id] for e in hits)),
            tuple(dict.fromkeys(a for e in hits for a in e.anchors)))


def simulate(question: str, refs: list, observed: str | None, r1: Arm, r2: Arm) -> dict:
    """Both arms' routes, books and lanes for one question, and why retrieval can differ."""
    def query_only(arm: Arm) -> Any:
        return arm.detect(query=question, verse_refs=refs, intent_type="", entity_names=[],
                          lexicon=arm.lexicon, book_ids=arm.book_ids)

    s1, s2 = query_only(r1), query_only(r2)
    contrib = infer_llm(observed, s1.route, lambda c: with_llm(r1, s1, c))
    routes = ((observed if observed and contrib is not None else s1.route),
              with_llm(r2, s2, contrib))
    arms = {}
    for key, arm, signals, route in (("R1", r1, s1, routes[0]), ("R2", r2, s2, routes[1])):
        events, anchors = lane(arm, route, question)
        arms[key] = {"query_only": signals.route, "route": route,
                     "books": list(signals.detected_book_ids), "events": list(events),
                     "lane": list(anchors)}
    klass = [r if r not in DENSE else "dense" for r in routes]
    causes = [c for c, differs in (("route", klass[0] != klass[1]),
                                   ("books", arms["R1"]["books"] != arms["R2"]["books"]),
                                   ("lane", arms["R1"]["lane"] != arms["R2"]["lane"])) if differs]
    return {"observed": observed, "llm": "unexplained" if contrib is None else contrib,
            **arms, "causes": causes}


# ---------------------------------------------------------------- the freeze

def observed_routes(paths: Sequence[Path], build: str) -> tuple[dict[str, str], list[dict]]:
    """Modal route per question over the R1 runs (ties: the earlier run), and their record."""
    seen: dict[str, list[str]] = {}
    record = []
    for path in paths:
        run = _read_json(path)
        meta = run.get("meta") or {}
        if meta.get("data_build_id") != build or meta.get("gt_version") != "v2":
            raise FreezeError(f"{path}: build {meta.get('data_build_id')}, GT "
                              f"{meta.get('gt_version')}; the R1 arm's runs are {build}, GT v2")
        for qid, row in (run.get("per_question") or {}).items():
            if row.get("route"):
                seen.setdefault(qid, []).append(row["route"])
        record.append({"path": _rel(path), "sha256": sha256_of(path),
                       "n_routes": sum(1 for r in run["per_question"].values() if r.get("route"))})
    return {q: Counter(rs).most_common(1)[0][0] for q, rs in seen.items()}, record


def _ids_block(qids: Iterable[str]) -> dict:
    qids = sorted(set(qids))
    return {"question_ids": qids, "n_questions": len(qids)}


def slice_doc(rows: Mapping[str, dict], families: Mapping[str, str]) -> dict:
    """The sub-slices, their union (minus EXCLUDED), the excluded and disambiguation rows."""
    subs = {c: _ids_block(q for q, row in rows.items() if c in row["causes"]
                          and q not in EXCLUDED) for c in SUB_SLICES}
    union = set().union(*(s["question_ids"] for s in subs.values()))
    family = sorted(q for q, f in families.items() if f == REPORT_FAMILY)
    return {
        SLICE_KEY: {"sub_slices": subs, "union": _ids_block(union)},
        "excluded": {**_ids_block(EXCLUDED), "rows": {q: rows[q] for q in EXCLUDED if q in rows}},
        REPORT_FAMILY: {**_ids_block(family), "rows": {q: rows[q] for q in family}},
        "changed": {q: row for q, row in sorted(rows.items()) if row["causes"]},
        "unexplained": sorted(q for q, row in rows.items() if row["llm"] == "unexplained"),
        "transitions": dict(sorted(Counter(
            f"{row['R1']['route']}->{row['R2']['route']}" for row in rows.values()
            if row["R1"]["route"] != row["R2"]["route"]).items())),
    }


def arm_record(name: str, contracts: Path) -> dict:
    code = ({"commit": R1_COMMIT} if name == "R1" else
            {path: sha256_of(REPO / path) for path in CODE.values()})
    return {"build": contracts_build(contracts), "code": code,
            "contracts": {f: sha256_of(contracts / f)
                          for f in ("event_registry.json", "routing_lexicon.json")}}


def derive(r1_contracts: Path, r2_contracts: Path, observed: Sequence[Path],
           gt_path: Path = GT_V2_PATH, freeze_path: Path = FREEZE_PATH) -> dict:
    check_verse_parser()
    if contracts_build(r1_contracts) != R1_BUILD:
        raise FreezeError(f"{r1_contracts} is not the R1 build {R1_BUILD}")
    gt = load_ground_truth_v2(Path(gt_path), Path(freeze_path))
    ids = id_map(_read_json(r1_contracts / "event_registry.json"),
                 _read_json(r2_contracts / "event_registry.json"))
    r1, r2 = r1_arm(r1_contracts, ids), r2_arm(r2_contracts, ids)
    routes, runs = observed_routes(observed, R1_BUILD)
    from utils.verse_parser import find_verse_references
    rows = {q.question_id: {"question_type": q.question_type, "family": q.family,
                            **simulate(q.question, list(find_verse_references(q.question).refs),
                                       routes.get(q.question_id), r1, r2)}
            for q in gt.items}
    gans = sorted(load_frozen().gans_subset)
    return {
        "schema": SCHEMA, "prereg": _rel(HERE / "prereg.md"), "rules": RULES,
        "script": {"path": _rel(SCRIPT), "sha256": sha256_of(SCRIPT)},
        "gt": {"path": _rel(gt_path), "sha256": gt.sha256, "freeze_record": _rel(freeze_path),
               "slot_universe": gt.slot_universe, "n_questions": len(gt.items)},
        "arms": {"R1": arm_record("R1", r1_contracts), "R2": arm_record("R2", r2_contracts)},
        "observed_runs": runs,
        **slice_doc(rows, {q.question_id: q.family for q in gt.items}),
        "gans_subset": {"source": _rel(FROZEN_R1_PATH), "sha256": sha256_of(FROZEN_R1_PATH),
                        **_ids_block(gans)},
    }


def render(frozen: dict) -> bytes:
    return (json.dumps(frozen, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()


def summary(frozen: dict) -> str:
    block = frozen[SLICE_KEY]
    lines = [f"{c}: {s['n_questions']} questions" for c, s in block["sub_slices"].items()]
    lines.append(f"route-change slice (C3): {block['union']['n_questions']} questions; "
                 f"excluded {frozen['excluded']['question_ids']}")
    lines.append(f"{REPORT_FAMILY}: {frozen[REPORT_FAMILY]['n_questions']} questions; "
                 f"unexplained routes {len(frozen['unexplained'])}; transitions "
                 f"{frozen['transitions']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Freeze the R2 route-change slice.")
    ap.add_argument("--r2-contracts", type=Path, required=True, help="contracts/<R2 build>/")
    ap.add_argument("--r1-contracts", type=Path,
                    default=settings.rag_store / "contracts" / R1_BUILD)
    ap.add_argument("--observed", type=Path, nargs="+", required=True,
                    help="the R1 arm's quick_retrieval_eval results (only their routes are read)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="re-derive and exit 1 if --out differs; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="replace an --out whose bytes differ from the re-derivation")
    a = ap.parse_args(argv)
    try:
        frozen = derive(a.r1_contracts, a.r2_contracts, a.observed)
    except (GtV2Error, FreezeError, FrozenR1Error, HeldoutError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    data = render(frozen)
    if a.check:
        same = a.out.is_file() and a.out.read_bytes() == data
        print(f"{a.out}: {'matches' if same else 'DIFFERS from'} the re-derivation")
        return 0 if same else 1
    if a.out.is_file() and a.out.read_bytes() != data and not a.force:
        print(f"refused: {a.out} (sha256 {sha256_of(a.out)}) differs from the re-derivation "
              f"(sha256 {hashlib.sha256(data).hexdigest()}); pass --force to replace it",
              file=sys.stderr)
        return 2
    a.out.write_bytes(data)
    print(f"{summary(frozen)}\nsaved → {a.out}\nsha256 {hashlib.sha256(data).hexdigest()} "
          "→ pin it in src/r2_frozen.py FROZEN_R2_SHA256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
