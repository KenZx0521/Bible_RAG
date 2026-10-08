"""The build this process serves, installed once at startup and never switched.

``active()`` is what request handlers read: the build row, the contract's routing
lexicon and event registry. When the handshake failed (and STRICT_BUILD_CHECK is
off) nothing is active and every handler that needs data answers 503.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

from ragcommon.routing import RoutingLexicon
from serving.build import Build
from serving.handshake import Handshake
from utils.retrieval.event_registry import RegistryEvent


class NoActiveBuild(RuntimeError):
    """No build passed the handshake; the backend serves no data."""


@dataclass(frozen=True)
class Active:
    build: Build
    lexicon: RoutingLexicon
    registry: tuple[RegistryEvent, ...]
    book_ids: Mapping[str, str]          # routing full book name -> book_id

    @property
    def book_names(self) -> tuple[str, ...]:
        """The books' full names: the event lane masks what the router masks before its
        scan (an abbreviation such as 約三 is no mask: 亞伯拉罕之約三個應許)."""
        return self.lexicon.full_names


def make_active(build: Build, lexicon: RoutingLexicon,
                registry: tuple[RegistryEvent, ...]) -> Active:
    names = {b.full_name: b.book_id for b in lexicon.books}
    return Active(build, lexicon, registry, MappingProxyType(names))


_active: Optional[Active] = None
_handshake: Optional[Handshake] = None


def install(active: Optional[Active], handshake: Handshake) -> None:
    global _active, _handshake
    _active, _handshake = active, handshake


def reset() -> None:
    global _active, _handshake
    _active, _handshake = None, None


def active() -> Active:
    if _active is None:
        problems = "; ".join(_handshake.mismatches) if _handshake else "startup has not run"
        raise NoActiveBuild(f"no build is being served: {problems}")
    return _active


def handshake() -> Optional[Handshake]:
    return _handshake
