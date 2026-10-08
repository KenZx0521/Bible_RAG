"""G-ROUTE, R2 rules: the routing lexicon is the union of design §5.2 (``kg.k4_route``).

1. the layer's ``routing_lexicon.json`` (byte for byte), its ``routing_terms`` records and
   its ``query_aliases.json`` are what K4 compiles again from the text, kg0 and events
   layers and the registries (the union, routability and route types, the exclusion
   rows); K4 joins its lexicon from its records, so the stored files join too;
2. every kind carries its provenance class and evidence fields;
3. nothing carries legacy provenance (``external_legacy``, ``retire_by``);
4. an alias stands for a kg0 name or a divine pattern, its surface is no kg0 name and
   has no latin letter;
5. the event terms are exactly the events layer's triggers, each pointing at its owner;
6. the backend's parser (``ragcommon.routing``) accepts the lexicon and the alias contract.

Rules 2 to 6 do not lean on K4's code, so they hold even where K4 and the records agree on
a mistake.

An empty category is legal (the "PDF plus curated only" variant). The GT route diff is
evaluation's, not a gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from ragcommon import routing
from ragdata.contract import record_to_dict
from ragdata.gates.base import MAX_DETAILS, GateResult, capped
from ragdata.kg import k4_route
from ragdata.stages.errors import StageError

NAME = "G-ROUTE"
# kind -> (the provenance classes it may have, the fields it must set)
KINDS = {
    "name": (("pdf_deterministic", "pdf_rule"), ("evidence_span_id",)),
    "dotless": (("pdf_rule",), ("evidence_span_id", "rule_id")),
    "divine": (("pdf_rule",), ("evidence_span_id", "rule_id")),
    "alias": (("external_query",), ("alias_id", "note")),
    "event": (("curated_human", "external_event_alias"), ()),
    "book": (("curated_metadata",), ("book_id", "full_name")),
}
EVENT_FIELDS = {"curated_human": ("at", "decided_by"), "external_event_alias": ("note",)}
ASCII_LETTER = re.compile(r"[A-Za-z]")
Row = Mapping[str, Any]


def _record_diffs(rows: Sequence[Row], want: Sequence[Row]) -> list[str]:
    have = {r["term_key"]: r for r in rows}
    expected = {r["term_key"]: r for r in want}
    out = []
    for key in sorted(set(have) | set(expected)):
        if have.get(key) != expected.get(key):
            what = ("missing" if key not in have else "not in the union" if key not in expected
                    else "differs from the union")
            out.append(f"{key} {(have.get(key) or expected[key])['surface']}: {what}")
    return out


def _union(compiled: k4_route.Compiled, rows: Sequence[Row], lexicon: bytes, aliases: Any
           ) -> list[str]:
    out = _record_diffs(rows, compiled.records)
    if lexicon != routing.render_lexicon(compiled.lexicon):
        out.append("routing_lexicon.json is not the union K4 compiles")
    if aliases != compiled.query_aliases:
        out.append("query_aliases.json is not the compile of query_aliases.yaml")
    return out


def _kind(row: Row) -> list[str]:
    where = f"{row['term_key']} {row['surface']}"
    classes, needs = KINDS[row["kind"]]
    if row["provenance_class"] not in classes:
        return [f"{where}: a {row['kind']} term is not {row['provenance_class']}"]
    needs = (*needs, *EVENT_FIELDS.get(row["provenance_class"], ()))
    out = [f"{where}: a {row['kind']} term needs {f}" for f in needs if not row.get(f)]
    if row["kind"] == "name" and (row["provenance_class"] == "pdf_rule") != bool(
            row["norm_rule_ids"]):
        out.append(f"{where}: a name is pdf_rule iff a normalization rule applied")
    return out


def _aliases(rows: Sequence[Row], inputs: k4_route.RouteInputs) -> list[str]:
    names = {n.norm_key: n.name_id for n in inputs.snapshot.of("names")}
    refs = {*names.values(), *(rule_id for rule_id, _ in inputs.divine.patterns)}
    out = []
    for row in (r for r in rows if r["kind"] == "alias"):
        where = f"{row['term_key']} {row['surface']}"
        out += [f"{where}: target {t['ref']} is no kg0 name or divine pattern"
                for t in row["targets"] if t["ref"] not in refs]
        out += [f"{where}: no target"] if not row["targets"] else []
        out += [f"{where}: the surface is a kg0 name"] if row["surface"] in names else []
        out += [f"{where}: latin letters"] if ASCII_LETTER.search(row["surface"]) else []
    return out


def _events(rows: Sequence[Row], inputs: k4_route.RouteInputs) -> list[str]:
    have = {(r["surface"], t["ref"]) for r in rows if r["kind"] == "event" for t in r["targets"]}
    want = {(text, e.event_id) for e in inputs.snapshot.of("events")
            for text in (*(t.text for t in e.pdf_terms), *(a.text for a in e.external_aliases))}
    return ([f"trigger {s} of {ref} is not an event term" for s, ref in sorted(want - have)]
            + [f"event term {s} -> {ref} is no trigger of that event"
               for s, ref in sorted(have - want)])


def _contract(doc: Any, aliases: Any) -> list[str]:
    """Nothing is legacy; the backend parses both files."""
    if not isinstance(doc, dict):
        return ["routing_lexicon.json is not a JSON object"]
    out = [f"legacy provenance at {where}" for where in
           (routing.legacy_mark(doc), routing.legacy_mark(aliases)) if where]
    for name, parse, data in (("routing_lexicon.json", routing.parse_lexicon, doc),
                              ("query_aliases.json", routing.parse_query_aliases, aliases)):
        try:
            parse(data)
        except routing.RoutingLexiconError as exc:
            out.append(f"the backend refuses {name}: {exc}")
    return out


def _load(data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        return None


def check_route(inputs: k4_route.RouteInputs, terms: Sequence[Any], lexicon: bytes,
                aliases: bytes) -> GateResult:
    """``terms`` are the routing_terms records; ``lexicon`` and ``aliases`` the layer's
    routing_lexicon.json and query_aliases.json bytes."""
    rows, alias_doc = [record_to_dict(t) for t in terms], _load(aliases)
    try:
        violations = _union(k4_route.compile_route(inputs), rows, lexicon, alias_doc)
    except StageError as exc:
        violations = [f"K4 cannot compile the union: {exc}"]
    violations += [v for row in rows for v in _kind(row)]
    violations += _aliases(rows, inputs) + _events(rows, inputs)
    violations += _contract(_load(lexicon), alias_doc)
    observed = {"terms": len(rows), "routable": sum(r["routable"] for r in rows),
                "lexicon_sha256": hashlib.sha256(lexicon).hexdigest(),
                "violations": len(violations)}
    return GateResult(NAME, True, not violations, observed, {"violations": 0},
                      capped(violations, MAX_DETAILS))
