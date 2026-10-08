"""G-HELDOUT (design §8; experiments/2026-10-09_r2/prereg.md): does the event lane fire on
the right event for questions nobody tuned the triggers on? R2 against R1.

The questions are ``config/gold/heldout_events_r2.json`` (61: 43 positives on 32
events, 18 near-miss negatives), written blind and committed before any trigger
changed; only the bytes :data:`HELDOUT_SHA256` pins are read. ``heldout_gate.py
collect`` asks each arm every question (backend defaults, retrieval_only) and
keeps what this module scores (:func:`response_row`); ``score`` judges two arms.

* **Ids.** R1 reports legacy ids (``event:babieta``), R2 ev ids. Each arm's
  reported id goes to its build's ev id through that build's contract
  event_registry.json, then to R2's surviving event through R2's ``retired``
  (``merged_into``). The gold ids (events@904becb6ccd9 ev ids) take the same
  last step. R2's ``legacy_ids`` must agree with that composition.
* **Triggered**: ``event_registry_events`` is not empty.
* **Scored event**: the event whose anchor the lane appended, recovered with the
  lane's own rule (backend select_aux_anchors) from the arm's registry and the
  question's core top-k; the first triggered event when every triggered anchor
  was already in the top-k, so nothing was appended.
* **Correct**: a positive whose scored events are all acceptable: the gold
  event, or its parent ev0020 for ev0011 / ev0027 / ev0033 (the file's
  scoring_notes; the twins ev0002 / ev0003 / ev0014 already meet in ev0002).
  A triggered negative, or a positive triggered on another event, is an error.
* **ok** per question: a positive triggered correctly, a negative not triggered.
* **Gate** (n = R2's triggered questions, tuned_on items left out): n ≥ 30 →
  PASS iff precision (correct / n) ≥ 0.90 and (R2 not ok, R1 ok) − (R2 ok,
  R1 not ok) ≤ 2; n < 30 → SIGNOFF, a descriptive report Kay signs off.
* **Reported only**: recall on the positives, the offline string hit (the
  arm's own triggers in the book-masked question, no routing) and each missed
  positive's cause: trigger (no string hit), route (string hit, lane silent),
  wrong_event.
Inputs the protocol does not allow raise HeldoutError and get no verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .validity import infra_failed

HELDOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "gold" / "heldout_events_r2.json"
# sha256 of heldout_events_r2.json as committed in 1a0d514, before any trigger changed.
HELDOUT_SHA256 = "c2bd965ce1cb889134c9550518966a5c8dde8b71a7a6462410bf13d3c5909d83"
HELDOUT_SCHEMA = "ragdata.heldout_events.v1"
RUN_SCHEMA = "evaluation.heldout_run.v1"
PREREG = "evaluation/experiments/2026-10-09_r2/prereg.md"
ARMS = ("R1", "R2")
LANE = "event_registry"
REQUEST = MappingProxyType({"top_k": 5, "include_sources": True, "retrieval_only": True})
MIN_TRIGGERS, MIN_PRECISION, MAX_NET_LOSS = 30, 0.90, 2
# scoring_notes: ev0011 / ev0027 / ev0033 mostly lie inside ev0020's (受難週) anchors.
PARENTS = MappingProxyType({"ev0011": ("ev0020",), "ev0027": ("ev0020",),
                            "ev0033": ("ev0020",)})


class HeldoutError(ValueError):
    """Inputs the G-HELDOUT protocol does not allow; nothing is judged."""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise HeldoutError(message)


# ---------------------------------------------------------------- the questions

@dataclass(frozen=True)
class Item:
    id: str
    kind: str                  # "positive" | "negative"
    event_id: str | None       # gold, an ev id of events@904becb6ccd9; None for negatives
    question: str
    tuned_on: bool


@dataclass(frozen=True)
class HeldOut:
    sha256: str
    items: tuple[Item, ...]


def _item(raw: Mapping) -> Item:
    kind, event = raw.get("kind"), raw.get("event_id")
    _require(kind in ("positive", "negative"), f"{raw.get('id')}: kind {kind!r}")
    _require((kind == "positive") == isinstance(event, str),
             f"{raw.get('id')}: a positive needs an event_id, a negative none")
    return Item(raw["id"], kind, event, raw["question"], bool(raw["tuned_on"]))


def load_heldout(path: Path | str = HELDOUT_PATH, sha256: str | None = None) -> HeldOut:
    """The pinned held-out questions (``sha256`` defaults to HELDOUT_SHA256); refuses any
    other bytes."""
    sha256 = sha256 or HELDOUT_SHA256
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    _require(digest == sha256, f"{path}: sha256 {digest} is not the pinned held-out {sha256}")
    doc = json.loads(data)
    _require(doc.get("schema") == HELDOUT_SCHEMA, f"{path}: schema is not {HELDOUT_SCHEMA}")
    items = tuple(_item(raw) for raw in doc["items"])
    _require(len({i.id for i in items}) == len(items), f"{path}: repeated item ids")
    return HeldOut(digest, items)


# ---------------------------------------------------------------- collection

def _passage(source: Mapping) -> str:
    return source.get("passage_id") or source["id"]


def response_row(item_id: str, status: int | None, body: Any, error: str | None = None) -> dict:
    """What a run keeps of one /api/v1/query answer; ``invalid`` "http" or "infra" when the
    pipeline, not the router, failed (src/validity.py infra_failed)."""
    if status != 200 or not isinstance(body, Mapping):
        return {"id": item_id, "status": status, "invalid": "http",
                "error": error or str(body)[:300]}
    stats, intent = body.get("retrieval_stats") or {}, body.get("intent") or {}
    sources = [{"id": s.get("id"), "passage_id": s.get("passage_id"), "strategy": s.get("strategy")}
               for s in body.get("sources") or []]
    errors = stats.get("strategy_errors") or {}
    return {
        "id": item_id, "status": status, "route_used": stats.get("route_used"),
        "event_registry_events": list(stats.get("event_registry_events") or []),
        "use_graph": stats.get("use_graph"), "graph_strategies": stats.get("graph_strategies"),
        "intent": {"type": intent.get("type"), "entities": intent.get("entities")},
        "sources": sources, "strategy_errors": errors,
        "invalid": "infra" if infra_failed([s["strategy"] for s in sources], errors) else None,
    }


# ---------------------------------------------------------------- registries and ids

@dataclass(frozen=True)
class Registry:
    """One arm's contract event registry, keyed by the id that arm reports."""
    variant: str                                 # "R1" | "R2"
    anchors: Mapping[str, tuple[str, ...]]       # reported id -> anchor passages, file order
    triggers: Mapping[str, tuple[str, ...]]      # reported id -> what the lane matches
    to_ev: Mapping[str, str]                     # reported id -> the build's ev id
    book_names: tuple[str, ...]                  # what the lane masks (backend context)


def _texts(rows: Sequence[Mapping] | None) -> list[str]:
    return [row["text"] for row in rows or []]


def registry_from_contract(registry: Mapping, lexicon: Mapping) -> Registry:
    """R1 fires on legacy_triggers and reports legacy_id; R2 fires on pdf_terms then
    external_aliases and reports event_id. Both mask the lexicon books' full names (the
    backend's serving.context.book_names)."""
    variant = registry.get("variant")
    _require(variant in ARMS, f"event registry variant {variant!r} is neither R1 nor R2")
    key = "legacy_id" if variant == "R1" else "event_id"
    anchors, triggers, to_ev = {}, {}, {}
    for event in registry["events"]:
        rid = event[key]
        anchors[rid] = tuple(a["passage_id"] for a in event["anchors"])
        texts = (_texts(event.get("legacy_triggers")) if variant == "R1" else
                 _texts(event.get("pdf_terms")) + _texts(event.get("external_aliases")))
        triggers[rid] = tuple(dict.fromkeys(texts))
        to_ev[rid] = event["event_id"]
    names = tuple(dict.fromkeys(b["full_name"] for b in lexicon["books"]))
    return Registry(variant, MappingProxyType(anchors), MappingProxyType(triggers),
                    MappingProxyType(to_ev), names)


@dataclass(frozen=True)
class IdMap:
    merged_into: Mapping[str, str]     # R2 retired ev id -> surviving ev id
    events: frozenset[str]             # R2's ev ids

    def canonical(self, ev: str) -> str:
        out = self.merged_into.get(ev, ev)
        _require(out in self.events, f"{ev} is no R2 event and was not merged into one")
        return out

    def accepts(self, gold: str, ev: str) -> bool:
        target = self.canonical(gold)
        return self.canonical(ev) in {target, *PARENTS.get(target, ())}


def id_map(r1_registry: Mapping, r2_registry: Mapping) -> IdMap:
    """R2's retired list, checked against R2's legacy_ids: every R1 legacy id must land
    where R1 legacy_id -> ev id -> merged_into lands."""
    merged = {r["event_id"]: r["merged_into"] for r in r2_registry.get("retired") or []}
    ids = IdMap(MappingProxyType(merged),
                frozenset(e["event_id"] for e in r2_registry["events"]))
    owner = {legacy: e["event_id"] for e in r2_registry["events"] for legacy in e["legacy_ids"]}
    for event in r1_registry["events"]:
        via = ids.canonical(event["event_id"])
        _require(owner.get(event["legacy_id"]) == via,
                 f"{event['legacy_id']}: R2 legacy_ids say {owner.get(event['legacy_id'])}, "
                 f"R1 ev id + merged_into say {via}")
    return ids


# ---------------------------------------------------------------- one arm

def lane_picks(events: Sequence[str], anchors: Mapping[str, Sequence[str]],
               core: Sequence[str], slots: int) -> list[tuple[str, str]]:
    """(event, anchor) the lane appends: backend event_registry.select_aux_anchors."""
    covered, picks = set(core), []
    for event in events:
        if len(picks) >= slots:
            break
        anchor = next((a for a in anchors[event] if a not in covered), None)
        if anchor is not None:
            picks.append((event, anchor))
            covered.add(anchor)
    return picks


def scored_events(row: Mapping, reg: Registry) -> list[str]:
    """The reported ids of the events whose anchors were appended (see module docstring)."""
    events = row["event_registry_events"]
    unknown = [e for e in events if e not in reg.anchors]
    _require(not unknown, f"{row['id']}: {unknown} are not in the arm's {reg.variant} registry")
    if not events:
        return []
    appended = [_passage(s) for s in row["sources"] if s["strategy"] == LANE]
    core = [_passage(s) for s in row["sources"] if s["strategy"] != LANE]
    picks = lane_picks(events, reg.anchors, core, max(1, len(appended)))
    expected = [a for _, a in picks]
    _require(expected == appended if appended else not picks,
             f"{row['id']}: appended {appended}, but the lane picks {expected} from {events}; "
             "is this the arm's contract?")
    return [e for e, _ in picks] if appended else events[:1]


def string_hits(question: str, reg: Registry) -> list[str]:
    """Reported ids whose triggers occur in the book-masked question (no routing)."""
    masked = question
    for name in sorted((n for n in reg.book_names if len(n) >= 2), key=len, reverse=True):
        masked = masked.replace(name, "□" * len(name))
    return [rid for rid, texts in reg.triggers.items() if any(t in masked for t in texts)]


def judge_item(item: Item, row: Mapping, reg: Registry, ids: IdMap) -> dict:
    """One question on one arm; event ids are R2's surviving ev ids."""
    def to_ev(rids: Sequence[str]) -> list[str]:
        return list(dict.fromkeys(ids.canonical(reg.to_ev[r]) for r in rids))

    scored, hits = to_ev(scored_events(row, reg)), to_ev(string_hits(item.question, reg))
    triggered = bool(row["event_registry_events"])
    positive = item.kind == "positive"
    correct = positive and triggered and all(ids.accepts(item.event_id, e) for e in scored)
    return {"route": row["route_used"], "triggered": triggered,
            "events": to_ev(row["event_registry_events"]), "scored": scored,
            "correct": correct, "ok": correct if positive else not triggered,
            "string_hits": hits,
            "string_hit_ok": positive and any(ids.accepts(item.event_id, e) for e in hits)}


def _miss(item: Item, judged: dict) -> str | None:
    if item.kind != "positive" or judged["correct"]:
        return None
    if judged["triggered"]:
        return "wrong_event"
    return "route" if judged["string_hit_ok"] else "trigger"


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def arm_summary(items: Sequence[Item], judged: Mapping[str, dict]) -> dict:
    triggered = [i.id for i in items if judged[i.id]["triggered"]]
    correct = [q for q in triggered if judged[q]["correct"]]
    positives = [i for i in items if i.kind == "positive"]
    misses: dict[str, list[str]] = {"trigger": [], "route": [], "wrong_event": []}
    for item in positives:
        if (cause := _miss(item, judged[item.id])) is not None:
            misses[cause].append(item.id)
    n_hit = sum(judged[i.id]["string_hit_ok"] for i in positives)
    return {"n_items": len(items), "n_triggered": len(triggered), "n_correct": len(correct),
            "precision": _ratio(len(correct), len(triggered)),
            "errors": [q for q in triggered if q not in correct],
            "recall": {"n_positive": len(positives), "n_correct": len(correct),
                       "value": _ratio(len(correct), len(positives))},
            "string_hit_recall": {"n_hit": n_hit, "value": _ratio(n_hit, len(positives))},
            "misses": misses}


# ---------------------------------------------------------------- the gate

def _run_problems(arm: str, run: Mapping, heldout: HeldOut) -> list[str]:
    meta, rows = run.get("meta") or {}, run.get("rows")
    if run.get("schema") != RUN_SCHEMA or not isinstance(rows, list):
        return [f"{arm}: not a {RUN_SCHEMA} run"]
    problems = [] if meta.get("arm") == arm else [f"{arm}: the run is arm {meta.get('arm')!r}"]
    if meta.get("heldout_sha256") != heldout.sha256:
        problems.append(f"{arm}: asked another held-out file ({meta.get('heldout_sha256')})")
    if not meta.get("data_build_id"):
        problems.append(f"{arm}: meta has no data_build_id")
    got = [row.get("id") for row in rows]
    if sorted(got) != sorted(i.id for i in heldout.items):
        problems.append(f"{arm}: rows are not exactly the {len(heldout.items)} held-out ids")
    invalid = {r.get("id"): r.get("invalid") for r in rows if r.get("invalid")}
    if invalid:
        problems.append(f"{arm}: invalid rows {invalid} (rerun arm)")
    off = [r.get("id") for r in rows if not r.get("invalid")
           and (r.get("use_graph") is not True or LANE not in (r.get("graph_strategies") or []))]
    if off:
        problems.append(f"{arm}: the {LANE} lane was off on {off} (backend defaults required)")
    return problems


def validate(runs: Mapping[str, Mapping], regs: Mapping[str, Registry], heldout: HeldOut) -> None:
    problems = [p for arm in ARMS for p in _run_problems(arm, runs[arm], heldout)]
    problems += [f"{arm}: registry variant {regs[arm].variant}" for arm in ARMS
                 if regs[arm].variant != arm]
    builds = {arm: (runs[arm].get("meta") or {}).get("data_build_id") for arm in ARMS}
    if not problems and builds["R1"] == builds["R2"]:
        problems.append(f"both arms ran build {builds['R1']}")
    _require(not problems, "; ".join(problems))


def _criteria(summary: Mapping[str, dict], judged: Mapping[str, Mapping[str, dict]],
              items: Sequence[Item]) -> dict:
    r2 = summary["R2"]
    losses = [i.id for i in items if judged["R1"][i.id]["ok"] and not judged["R2"][i.id]["ok"]]
    wins = [i.id for i in items if judged["R2"][i.id]["ok"] and not judged["R1"][i.id]["ok"]]
    precision = r2["precision"]
    return {
        "n_triggered": {"n": r2["n_triggered"], "min": MIN_TRIGGERS,
                        "enough": r2["n_triggered"] >= MIN_TRIGGERS},
        "precision": {"value": precision, "threshold": MIN_PRECISION,
                      "passed": precision is not None and precision >= MIN_PRECISION},
        "noninferiority": {"r2_lose_r1_win": losses, "r2_win_r1_lose": wins,
                           "net_loss": len(losses) - len(wins), "max": MAX_NET_LOSS,
                           "passed": len(losses) - len(wins) <= MAX_NET_LOSS},
    }


def _verdict(criteria: Mapping[str, dict]) -> tuple[str, list[str]]:
    reasons = []
    if not criteria["precision"]["passed"]:
        reasons.append(f"precision {criteria['precision']['value']} < {MIN_PRECISION}")
    noninf = criteria["noninferiority"]
    if not noninf["passed"]:
        reasons.append(f"net loss {noninf['net_loss']} > {MAX_NET_LOSS}")
    if not criteria["n_triggered"]["enough"]:
        return "SIGNOFF", [f"R2 triggered {criteria['n_triggered']['n']} < {MIN_TRIGGERS} "
                           "questions: descriptive report, Kay signs off"] + reasons
    return ("FAIL" if reasons else "PASS"), reasons


def heldout_gate(runs: Mapping[str, Mapping], contracts: Mapping[str, tuple[Mapping, Mapping]],
                 heldout: HeldOut) -> dict:
    """G-HELDOUT over the R1 and R2 runs (keys "R1", "R2") and each one's build contracts
    (event_registry.json, routing_lexicon.json)."""
    regs = {arm: registry_from_contract(*contracts[arm]) for arm in ARMS}
    validate(runs, regs, heldout)
    ids = id_map(contracts["R1"][0], contracts["R2"][0])
    items = [i for i in heldout.items if not i.tuned_on]
    rows = {arm: {r["id"]: r for r in runs[arm]["rows"]} for arm in ARMS}
    judged = {arm: {i.id: judge_item(i, rows[arm][i.id], regs[arm], ids) for i in items}
              for arm in ARMS}
    summary = {arm: {"data_build_id": runs[arm]["meta"]["data_build_id"],
                     **arm_summary(items, judged[arm])} for arm in ARMS}
    criteria = _criteria(summary, judged, items)
    verdict, reasons = _verdict(criteria)
    return {
        "gate": "G-HELDOUT", "prereg": PREREG, "verdict": verdict,
        "passed": {"PASS": True, "FAIL": False}.get(verdict), "fail_reasons": reasons,
        "heldout": {"sha256": heldout.sha256, "n_items": len(items),
                    "n_positive": sum(i.kind == "positive" for i in items),
                    "excluded_tuned_on": [i.id for i in heldout.items if i.tuned_on]},
        "params": {"min_triggers": MIN_TRIGGERS, "min_precision": MIN_PRECISION,
                   "max_net_loss": MAX_NET_LOSS, "parents": dict(PARENTS),
                   "merged_into": dict(ids.merged_into)},
        "arms": summary, "criteria": criteria,
        "per_item": [{"id": i.id, "kind": i.kind, "gold": i.event_id,
                      **{arm: judged[arm][i.id] for arm in ARMS}} for i in items],
    }
