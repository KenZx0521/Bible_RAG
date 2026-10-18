"""Layer store and inputs of the G-auto build (probe_C5 auto_layer.py, occ policy, union dropped)."""
from __future__ import annotations

import collections

from a_common import TEXT, jsonl
from layer_re import (P_ACC1, P_ACC_REV, P_ACC_SUCC_SYNC, P_COUP_SYNC, P_FN_ALIAS, P_MOTHER, P_RENAME,
                      P_REPL, P_SEAT, P_SLEEP, P_SUCC)


def in_scope(r: dict) -> bool:
    b, c, v = r["book_id"], r["chapter"], r["v_start"]
    return ((b == "1ki" and (c > 11 or (c == 11 and v >= 41))) or b == "2ki"
            or (b == "2ch" and (c > 9 or (c == 9 and v >= 29))))


def load():
    verses = [r for r in jsonl(TEXT / "verse_units.jsonl") if in_scope(r)]
    fns = collections.defaultdict(list)
    for r in jsonl(TEXT / "footnotes.jsonl"):
        m = P_FN_ALIAS.match(r["text"].strip())
        if m:
            fns[r["unit_key"]].append((r["fn_id"], m.group(1), m.group(2)))
    return verses, fns


class Layer:
    def __init__(self):
        self.nodes, self.edges, self.syncs, self.conflicts, self.log = [], [], [], [], []
        self.occ_alias = {}

    def byid(self, i):
        return next(n for n in self.nodes if n["id"] == i)

    def new(self, kingdom, name, verse, pending=False, src="?"):
        nd = dict(id="A%02d" % len(self.nodes), kingdom=kingdom, name=name, aliases=[], fields={},
                  evidence=[verse], pending=pending, order=len(self.nodes), created_by=src, has_acc=False)
        self.nodes.append(nd)
        return nd

    @staticmethod
    def match(nd, name):
        return name == nd["name"] or name in nd["aliases"]

    def resolve(self, name, kingdom=None, verse=None, prefer=(), pending_first=False, min_order=None):
        if verse and (verse, name) in self.occ_alias:
            return self.byid(self.occ_alias[(verse, name)])
        for p in prefer:
            if p is not None and self.match(p, name) and (kingdom is None or p["kingdom"] in (kingdom, None)):
                return p
        cands = [nd for nd in self.nodes if self.match(nd, name) and (kingdom is None or nd["kingdom"] in (kingdom, None))]
        if min_order is not None:
            c2 = [c for c in cands if c["order"] >= min_order]
            return c2[0] if c2 else None
        if pending_first:
            p = [c for c in cands if c["pending"]]
            if p:
                return p[-1]
        return cands[-1] if cands else None

    def setf(self, nd, f, val, verse, src):
        if nd is None:
            return
        if f in nd["fields"]:
            if nd["fields"][f][0] != val:
                self.conflicts.append((nd["id"], nd["name"], f, nd["fields"][f], (val, verse, src)))
            return
        nd["fields"][f] = (val, verse, src)
        if verse not in nd["evidence"]:
            nd["evidence"].append(verse)

    def add_edge(self, p, s, typ, verse):
        if p is None or s is None or p is s:
            return
        if not any(e[0] == p["id"] and e[1] == s["id"] for e in self.edges):
            self.edges.append((p["id"], s["id"], typ, verse))
        if s["kingdom"] is None and p["kingdom"]:
            s["kingdom"] = p["kingdom"]
        if p["kingdom"] is None and s["kingdom"]:
            p["kingdom"] = s["kingdom"]


def lexicons(verses):
    lex = set()
    for r in verses:
        t = r["text"]
        for P in (P_ACC1, P_ACC_REV, P_ACC_SUCC_SYNC, P_COUP_SYNC):
            for m in P.finditer(t):
                for g in ("rn", "nn", "rf", "nf"):
                    if g in m.groupdict() and m.group(g):
                        lex.add(m.group(g))
        for P, g in ((P_SUCC, "s"), (P_SLEEP, "n"), (P_SEAT, "s"), (P_REPL, "s"), (P_RENAME, "new")):
            for m in P.finditer(t):
                lex.add(m.group(g))
    plex = set(lex) | {m.group("m") for r in verses for m in P_MOTHER.finditer(r["text"])}
    return sorted(lex, key=len, reverse=True), sorted(plex, key=len, reverse=True)
