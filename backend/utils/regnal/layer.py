"""The build's regnal layer (contract file ``regnal_layer.json``, optional since contract 1.2.0)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ragcommon import regnal

LAYER_FILE = regnal.LAYER_FILE


@dataclass(frozen=True)
class RegnalLayer:
    view: regnal.View
    sha256: str
    names: tuple[str, ...]   # every chain king's name and alias, longest first

    def chain_size(self) -> dict[str, int]:
        return {kd: len(ids) for kd, ids in self.view.chain.items()}


def parse_layer(data: bytes) -> RegnalLayer:
    """The layer of the contract file's bytes; ValueError when it is not one."""
    try:
        doc = json.loads(data.decode("utf-8"))
        view = regnal.load(doc)
    except (UnicodeDecodeError, KeyError, TypeError, IndexError) as exc:
        raise ValueError(f"not a regnal layer: {exc!r}") from None
    if not all(view.chain.get(kd) for kd in regnal.KINGDOMS):
        raise ValueError("a regnal layer needs a chain for both kingdoms")
    on_chain = {x for ids in view.chain.values() for x in ids}
    names = sorted({n for x in on_chain for n in view.names(x) if len(n) >= 2}, key=lambda n: (-len(n), n))
    return RegnalLayer(view, hashlib.sha256(data).hexdigest(), tuple(names))
