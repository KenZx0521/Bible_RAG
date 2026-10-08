"""Book names that sources and GT references carry, resolved by ragcommon.books.

A source names its book in full: the PDF name (尼希米記) or a recorded variant
(尼西米記, the old file name the legacy build still returns). Abbreviations
are reference shorthand, not a source's book name, so they resolve to nothing.
"""

from __future__ import annotations

from ragcommon import books

_FULL_NAME_KINDS = frozenset({"name", "name_variant"})


def book_id_of(name: str | None) -> str | None:
    """The book id of a full book name, or None for anything else."""
    found = books.lookup_name(name.strip()) if name else None
    if found is None or found.kind not in _FULL_NAME_KINDS:
        return None
    return found.book_id
