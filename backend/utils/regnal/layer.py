"""The build's regnal layer (contract file ``regnal_layer.json``, optional since contract 1.2.0)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from ragcommon import regnal, routing

LAYER_FILE = regnal.LAYER_FILE


@dataclass(frozen=True)
class RegnalLayer:
    view: regnal.View
    sha256: str
    names: tuple[str, ...]   # every chain king's name and alias, longest first
    # lexicon names that hold a chain name and are none (押沙龍 holds 沙龍), longest first;
    # attached from the build's routing lexicon (with_blockers), () until then
    blockers: tuple[str, ...] = ()

    def chain_size(self) -> dict[str, int]:
        return {kd: len(ids) for kd, ids in self.view.chain.items()}


def parse_layer(data: bytes) -> RegnalLayer:
    """The layer of the contract file's bytes; ValueError when it is not one."""
    try:
        doc = json.loads(data.decode("utf-8"))
        view = regnal.load(doc)
    except ValueError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"not a regnal layer: {exc!r}") from None
    if not all(view.chain.get(kd) for kd in regnal.KINGDOMS):
        raise ValueError("a regnal layer needs a chain for both kingdoms")
    on_chain = {x for ids in view.chain.values() for x in ids}
    names = sorted({n for x in on_chain for n in view.names(x) if len(n) >= 2}, key=lambda n: (-len(n), n))
    return RegnalLayer(view, hashlib.sha256(data).hexdigest(), tuple(names))


def blockers_of(names: Iterable[str], surfaces: Iterable[str]) -> tuple[str, ...]:
    """The (NFKC) surfaces that hold a chain name and are none, longest first."""
    chain = set(names)
    found = {s for s in (unicodedata.normalize("NFKC", w) for w in surfaces)
             if s not in chain and any(n in s for n in chain)}
    return tuple(sorted(found, key=lambda s: (-len(s), s)))


def with_blockers(layer: RegnalLayer, lexicon: routing.RoutingLexicon) -> RegnalLayer:
    """The layer with the blockers of the build's routing lexicon: its person and place names
    (kinds name, dotless), not its events, whose surface does name the king (所羅門獻殿)."""
    surfaces = (t.surface for t in lexicon.terms if t.kind in routing.CATEGORY_KINDS["names"])
    return dataclasses.replace(layer, blockers=blockers_of(layer.names, surfaces))
