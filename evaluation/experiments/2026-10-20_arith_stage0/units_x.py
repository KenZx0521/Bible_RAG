"""Independent segments of the ordered-chain arithmetic stage-0 (prereg §3.5 獨立段).

Dynasty: 9 node-disjoint 3-king segments, by hand-reference (ref_v2) id. Genesis: 8 edge-disjoint
2-edge segments, by gen_layer id (亞當–以挪士 … 西鹿–他拉; neighbouring segments share an end node).
An item touches a segment when its path shares a king (dynasty) or a begetting edge (Genesis) with
it; it is nested when the whole path lies inside one segment.
"""
from __future__ import annotations

DYN_SEGMENTS = (("I02", "I04"), ("I06", "I08"), ("I09", "I11"), ("I16", "I18"),
                ("J01", "J03"), ("J04", "J06"), ("J08", "J10"), ("J11", "J13"), ("J14", "J16"))
GEN_SEGMENTS = (("G05.00", "G05.02"), ("G05.02", "G05.04"), ("G05.04", "G05.06"), ("G05.06", "G05.08"),
                ("G11.00", "G11.02"), ("G11.02", "G11.04"), ("G11.04", "G11.06"), ("G11.06", "G11.08"))


def label(seg: tuple[str, str]) -> str:
    return f"{seg[0]}-{seg[1]}"


def span(a: str, b: str, chain: list[str]) -> list[str]:
    i, j = chain.index(a), chain.index(b)
    return chain[i:j + 1]


def node_units(path: list[str], chains: dict[str, list[str]], segments=DYN_SEGMENTS) -> tuple[list[str], bool]:
    """(labels of the segments sharing a king with path, path inside one segment) for ids on chains."""
    touched, nested = [], False
    for seg in segments:
        ch = next(c for c in chains.values() if seg[0] in c)
        members = set(span(*seg, ch))
        if members & set(path):
            touched.append(label(seg))
            nested = nested or set(path) <= members
    return touched, nested


def edge_units(path: list[str], chains: dict[int, list[str]] | dict[str, list[str]],
               segments=GEN_SEGMENTS) -> tuple[list[str], bool]:
    """(labels of the segments sharing an edge with path, all path edges inside one segment)."""
    edges = set(zip(path, path[1:]))
    touched, nested = [], False
    for seg in segments:
        ch = next(c for c in chains.values() if seg[0] in c)
        s = span(*seg, ch)
        seg_edges = set(zip(s, s[1:]))
        if seg_edges & edges:
            touched.append(label(seg))
            nested = nested or (bool(edges) and edges <= seg_edges)
    return touched, nested
