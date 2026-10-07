"""G-ROUTE, R1 rules: the routing contract is the frozen legacy lexicon (design §8).

- the layer's ``routing_lexicon.json`` is the frozen file byte for byte (same sha256);
- the ``routing_terms`` records join back into exactly that file;
- every word is ``external_legacy`` and retires by R2;
- behaviour: the matcher rebuilt from the file gives, text for text, the live
  entity_dicts results on the probe texts (GT questions, verses, headings).

The live results come from the backend venv; without them, the frozen file or the
probe texts the gate fails closed. R2 replaces these rules (§5.2 union, no external_legacy).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from ragcommon import routing
from ragdata.contract import record_to_dict
from ragdata.gates.base import MAX_DETAILS, GateResult, capped
from ragdata.kg.k4_route import join_lexicon, rebuilt_matches

NAME = "G-ROUTE"


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _file_checks(rows: Sequence[Mapping[str, Any]], rest: Mapping[str, Any], lexicon: bytes,
                 frozen: bytes | None) -> list[str]:
    out = []
    if frozen is None:
        out.append("needs the frozen lexicon (config/registries/routing_lexicon.legacy.json)")
    elif lexicon != frozen:
        out.append(f"routing_lexicon.json (sha {_sha(lexicon)}) is not the frozen file "
                   f"(sha {_sha(frozen)})")
    if routing.render_lexicon(join_lexicon(rest, rows)) != lexicon:
        out.append("the routing_terms records do not join into routing_lexicon.json")
    out += [f"{r['term_key']}: R1 words are external_legacy retiring by R2, not "
            f"{r['provenance_class']}/{r['retire_by']}"
            for r in rows if (r["provenance_class"], r["retire_by"]) != ("external_legacy", "R2")]
    return out


def _behaviour(lexicon: bytes, texts: Sequence[str] | None,
               live: Sequence[Mapping[str, Any]] | None) -> tuple[list[str], int]:
    if texts is None or live is None:
        return ["needs the probe texts and the live entity_dicts results"], -1
    if not texts or len(live) != len(texts):
        return [f"{len(texts)} probe texts, {len(live)} live results"], -1
    try:
        rebuilt = rebuilt_matches(routing.parse_lexicon(json.loads(lexicon)), texts)
    except (ValueError, routing.RoutingLexiconError) as exc:
        return [f"routing_lexicon.json does not load: {exc}"], -1
    diffs = [f"{text[:30]!r}: frozen {got}, live {dict(want)}"
             for text, got, want in zip(texts, rebuilt, live) if got != dict(want)]
    return diffs, len(diffs)


def check_route(terms: Sequence[Any], rest: Mapping[str, Any], lexicon: bytes,
                frozen: bytes | None, texts: Sequence[str] | None,
                live: Sequence[Mapping[str, Any]] | None) -> GateResult:
    """``terms`` are the routing_terms records; ``rest`` the lexicon without its words (from
    the layer report); ``lexicon`` the layer's routing_lexicon.json bytes."""
    rows = [record_to_dict(t) for t in terms]
    violations = [] if rows else ["the layer holds no routing terms"]
    violations += _file_checks(rows, rest, lexicon, frozen)
    diffs, mismatches = _behaviour(lexicon, texts, live)
    violations += diffs
    observed = {"terms": len(rows), "probes": len(texts or ()), "mismatches": mismatches,
                "lexicon_sha256": _sha(lexicon), "frozen_sha256": _sha(frozen),
                "violations": len(violations)}
    return GateResult(NAME, True, not violations, observed, {"violations": 0, "mismatches": 0},
                      capped(violations, MAX_DETAILS))
