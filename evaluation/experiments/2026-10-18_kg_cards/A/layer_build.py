"""G-auto regnal layer of prereg §2: probe_C5 auto_layer.py (occ alias policy), split into short steps.

Same regexes and the same per-verse order as the probe. Only the footnote-alias step differs:
fn_rule="probe" is the probe's word pick (reproduces K/probe_C5/auto_layer_occ.json);
fn_rule="slot" is the appendix-A rule (K0-2): a 又名/就是 footnote binds only a name that fills a
king slot of a regnal formula matched in that verse (successor > accession > synchronism
reference); for 就是 the slot's king must be in the target king's kingdom; else it is rejected.
"""
from __future__ import annotations

import re

from layer_core import Layer, lexicons, load
from layer_re import (C, FOREIGN_DEATH, KMAP, N1, OPP, P_ACC0, P_ACC1, P_ACC_REV, P_ACC_SUCC_SYNC,
                      P_AGE, P_AGE2, P_COUP_SYNC, P_MOTHER, P_REIGN, P_RENAME, P_REPL, P_SEAT,
                      P_SLEEP, P_SUCC, P_USURP, P_VERB, zh2int)

SLOT_PRIORITY = ("succ", "acc", "ref")


class Builder:
    def __init__(self, verses, fns, fn_rule):
        self.A, self.verses, self.fns, self.fn_rule = Layer(), verses, fns, fn_rule
        self.lex, self.plex = lexicons(verses)
        self.last, self.curk, self.ch_ptr = None, {}, None

    # ---- helpers
    def names_in(self, t, person=False):
        out = []
        for n in (self.plex if person else self.lex):
            for m in re.finditer(re.escape(n), t):
                if not any(m.start() < e and s < m.end() for s, e, _ in out):
                    out.append((m.start(), m.end(), n))
        return sorted(out)

    def lex_suffix(self, pre):
        return next((n for n in self.lex if pre.endswith(n)), None)

    def R(self, name, kingdom=None, **kw):
        if self.is_ch:
            p = self.ch_ptr
            return self.A.resolve(name, "J", self.uk, prefer=(p,), min_order=(p["order"] if p else 0))
        return self.A.resolve(name, kingdom, self.uk, prefer=(self.last,), **kw)

    def src(self):
        return "ch" if self.is_ch else "ki"

    def mark_acc(self, nd):
        nd["pending"] = False
        nd["has_acc"] = True
        if self.uk not in nd["evidence"]:
            nd["evidence"].append(self.uk)

    # ---- per-verse steps (probe order)
    def step_acc_sync(self, t, acc):
        A, uk = self.A, self.uk
        for m in P_ACC1.finditer(t):
            rk = KMAP.get(m.group("rk")) if m.group("rk") else None
            nk = KMAP.get(m.group("nk")) if m.group("nk") else None
            tail = m.group("tail")
            if "猶大" in tail:
                nk = "J"
            elif "以色列" in tail:
                nk = "I"
            ref = A.resolve(m.group("rn"), rk, uk)
            if rk is None and ref is not None:
                rk = ref["kingdom"]
            if nk is None and rk:
                nk = OPP[rk]
            if rk is None and nk:
                rk = OPP[nk]
            if ref is not None and ref["kingdom"] is None and rk:
                ref["kingdom"] = rk
            nd = A.resolve(m.group("nn"), nk, uk, pending_first=True)
            if nd is not None and not nd["pending"] and nd is not self.curk.get(nk):
                nd = None
            if nd is None:
                nd = A.new(nk, m.group("nn"), uk, src="acc_sync")
            self.mark_acc(nd)
            if nd["kingdom"] is None:
                nd["kingdom"] = nk
            if m.group("nf"):
                A.setf(nd, "father", m.group("nf"), uk, "acc")
            if ref is None:
                ref = A.new(rk, m.group("rn"), uk, src="sync_ref")
            A.syncs.append((nd["id"], ref["id"], zh2int(m.group("y")), uk, "acc"))
            acc.append(nd)
            self.slots += [("acc", m.group("nn"), nd), ("ref", m.group("rn"), ref)]
        for m in P_ACC_REV.finditer(t):
            nk = KMAP[m.group("nk")]
            nd = A.resolve(m.group("nn"), nk, uk, prefer=(self.last,))
            ref = A.resolve(m.group("rn"), OPP[nk], uk)
            if nd and ref:
                A.syncs.append((nd["id"], ref["id"], zh2int(m.group("y")), uk, "rev"))
                self.slots += [("acc", m.group("nn"), nd), ("ref", m.group("rn"), ref)]

    def step_acc0(self, t, acc):
        for m in P_ACC0.finditer(t):
            nn = self.lex_suffix(m.group("pre"))
            if not nn:
                continue
            nk = KMAP[m.group("nk")]
            nd = self.R(nn, nk, pending_first=True) if not self.is_ch else self.R(nn)
            if nd is None:
                nd = self.A.new(nk, nn, self.uk, src="acc0")
            self.mark_acc(nd)
            if nd["kingdom"] is None:
                nd["kingdom"] = nk
            acc.append(nd)
            self.slots.append(("acc", nn, nd))

    def step_age_named(self, m, acc):
        nm = self.lex_suffix(m.group("pre")) if m.group("pre") else None
        if not nm:
            return None
        nd = self.R(nm, None, pending_first=True) if not self.is_ch else self.R(nm)
        if nd is None:
            kd = "J" if self.is_ch else (self.last["kingdom"] if self.last else None)
            nd = self.A.new(kd, nm, self.uk, src="age_named")
        self.mark_acc(nd)
        acc.append(nd)
        self.slots.append(("acc", nm, nd))
        return nd

    def step_reign(self, t, subj):
        for m in P_REIGN.finditer(t):
            pre = re.sub("在" + C + "{2,4}$", "", m.group("pre") or "")
            nm = self.lex_suffix(pre) if pre else None
            nd = None
            if nm:
                nd = self.R(nm)
                if nd is None and not self.is_ch:
                    nd = self.A.new(None, nm, self.uk, src="reign_named")
            if nd is None:
                nd = subj
            u, v = m.group("u"), zh2int(m.group("v"))
            val = v if u == "年" else (v / 12 if u == "個月" else v / 365)
            self.A.setf(nd, "reign", round(val, 3), self.uk, self.src())
            k = m.group("k") or ""
            if nd is not None and nd["kingdom"] is None and k:
                if k.startswith("以色列") and k != "以色列眾人的":
                    nd["kingdom"] = "I"
                elif k == "猶大":
                    nd["kingdom"] = "J"
            break

    def step_mother_sleep(self, t, subj):
        m = P_MOTHER.search(t)
        if m and subj is not None:
            self.A.setf(subj, "mother", m.group("m"), self.uk, self.src())
            if m.group("d"):
                self.A.setf(subj, "mother_desc", m.group("d"), self.uk, self.src())
        sleepers = []
        for m in P_SLEEP.finditer(t):
            nd = self.R(m.group("n"))
            if nd is None and not self.is_ch:
                nd = self.A.new(None, m.group("n"), self.uk, src="sleep")
            if nd is not None:
                self.A.setf(nd, "death", "natural", self.uk, self.src())
                sleepers.append(nd)
        return sleepers

    def step_succession(self, t, subj, sleepers, m2):
        A, uk = self.A, self.uk
        if FOREIGN_DEATH.search(t):
            A.log.append(("skip_foreign_succ", uk))
            return
        for P, typ in ((P_SUCC, "son"), (P_SEAT, "seat"), (P_REPL, "installed")):
            for m in P.finditer(t):
                pred = self.R(m.group("pf")) if "pf" in m.groupdict() and m.group("pf") else None
                if pred is None:
                    pred = sleepers[-1] if sleepers else subj
                if pred is None:
                    continue
                typ2 = "brother" if (typ == "son" and "兄弟" + m.group("s") in t) else typ
                sname = m.group("s")
                if self.is_ch:
                    s = A.resolve(sname, "J", uk, min_order=pred["order"] + 1)
                    if s is None:
                        s = A.new("J", sname, uk, pending=True, src="succ_ch")
                else:
                    s = A.resolve(sname, pred["kingdom"], uk, pending_first=True)
                    if s is None or (not s["pending"] and s["order"] <= pred["order"]):
                        s = A.new(pred["kingdom"], sname, uk, pending=True, src="succ")
                A.add_edge(pred, s, typ2, uk)
                if typ2 == "son":
                    A.setf(s, "father", pred["name"], uk, "succ")
                if m2:
                    A.setf(s, "age", zh2int(m2.group("a")), uk, "age2")
                self.slots.append(("succ", sname, s))

    def step_usurp(self, t, subj):
        A, uk = self.A, self.uk
        if not P_USURP.search(t) or self.is_ch:
            return
        vm = P_VERB.search(t)
        before = [n for s, e, n in self.names_in(t, person=True) if e <= vm.start()]
        if not before:
            return
        uname, victim = before[-1], None
        vv = re.search(r"(?:背叛|殺了|擊殺)(?:" + N1 + r"的兒子)?(" + "|".join(map(re.escape, self.plex)) + r")", t)
        if vv and vv.group(1) != uname:
            victim = self.R(vv.group(1))
        if victim is None:
            victim = subj
        if victim is None:
            return
        s = A.resolve(uname, victim["kingdom"], uk, pending_first=True)
        if s is None or (not s["pending"] and s["order"] <= victim["order"]):
            s = A.new(victim["kingdom"], uname, uk, pending=True, src="usurp")
        A.add_edge(victim, s, "usurp", uk)
        A.setf(victim, "death", "killed", uk, "usurp")
        A.log.append(("usurp", uk, victim["name"], "->", uname))

    def step_other_syncs(self, t):
        A, uk = self.A, self.uk
        if self.is_ch:
            return
        for m in P_COUP_SYNC.finditer(t):
            nd, ref = A.resolve(m.group("nn"), None, uk), A.resolve(m.group("rn"), None, uk)
            if nd and ref and nd["kingdom"] and ref["kingdom"] and nd["kingdom"] != ref["kingdom"]:
                A.syncs.append((nd["id"], ref["id"], zh2int(m.group("y")), uk, "coup"))
                self.slots += [("acc", m.group("nn"), nd), ("ref", m.group("rn"), ref)]
        for m in P_ACC_SUCC_SYNC.finditer(t):
            sm = P_SUCC.search(t)
            if sm:
                nd = A.resolve(sm.group("s"), None, uk)
                ref = A.resolve(m.group("rn"), KMAP.get(m.group("rk")) if m.group("rk") else None, uk)
                if nd and ref:
                    A.syncs.append((nd["id"], ref["id"], zh2int(m.group("y")), uk, "succ_sync"))
                    self.slots.append(("ref", m.group("rn"), ref))

    def step_rename(self, t):
        A, uk = self.A, self.uk
        for m in P_RENAME.finditer(t):
            tgt = next((A.byid(e[1]) for e in reversed(A.edges) if e[3] == uk), None)
            if tgt is None:
                m3 = re.search(r"給(" + N1 + r")改名", t)
                if m3:
                    tgt = self.R(m3.group(1))
            if tgt is not None and tgt["name"] != m.group("new"):
                old = tgt["name"]
                tgt["name"] = m.group("new")
                if old not in tgt["aliases"]:
                    tgt["aliases"].append(old)
                A.log.append(("rename", uk, old, "->", m.group("new"), tgt["id"]))

    # ---- footnote aliases
    def pick_probe(self, t, target):
        ns = [n for _, _, n in self.names_in(t) if n != target]
        if not ns:
            return None
        prim = {nd["name"] for nd in self.A.nodes}
        non = [n for n in ns if n not in prim]
        return non[0] if non else ns[-1]

    def pick_slot(self, target, tnode):
        cands = [(c, w, n) for c, w, n in self.slots if w != target and n is not None
                 and (tnode is None or n["kingdom"] == tnode["kingdom"])]
        for cls in SLOT_PRIORITY:
            hit = next(((w, n) for c, w, n in cands if c == cls), None)
            if hit:
                return hit
        return None

    def step_footnotes(self, t):
        A, uk = self.A, self.uk
        for fid, kind, target in self.fns.get(uk, []):
            if self.fn_rule == "probe":
                word = self.pick_probe(t, target)
                if word is None:
                    continue
                nd = self.R(word) if kind == "又名" else self.R(target)
            else:
                tnode = self.R(target) if kind == "就是" else None
                hit = self.pick_slot(target, tnode) if (kind == "又名" or tnode is not None) else None
                if hit is None:
                    A.log.append(("fn_alias_rejected", fid, kind, target))
                    continue
                word, nd = hit[0], (hit[1] if kind == "又名" else tnode)
            if kind == "又名":
                if nd is not None and target not in nd["aliases"]:
                    nd["aliases"].append(target)
            elif nd is not None:
                A.occ_alias[(uk, word)] = nd["id"]
            A.log.append(("fn_alias", fid, kind, word, target, nd["id"] if nd else None))

    # ---- verse loop
    def verse(self, r):
        self.uk, t = r["unit_key"], r["text"]
        self.is_ch, self.slots, acc = r["book_id"] == "2ch", [], []
        if not self.is_ch:
            self.step_acc_sync(t, acc)
        self.step_acc0(t, acc)
        m = P_AGE.search(t)
        age_node = self.step_age_named(m, acc) if m else None
        if acc:
            if self.is_ch:
                self.ch_ptr = acc[-1]
            else:
                self.last = acc[-1]
                for a in acc:
                    if a["kingdom"]:
                        self.curk[a["kingdom"]] = a
        subj = self.ch_ptr if self.is_ch else self.last
        if m:
            self.A.setf(age_node or subj, "age", zh2int(m.group("a")), self.uk, self.src())
        m2 = P_AGE2.search(t)
        self.step_reign(t, subj)
        sleepers = self.step_mother_sleep(t, subj)
        self.step_succession(t, subj, sleepers, m2)
        self.step_usurp(t, subj)
        self.step_other_syncs(t)
        self.step_rename(t)
        self.step_footnotes(t)


def fallback_edges(A):
    """Order fallback edges (nodes with accession evidence and no explicit predecessor)."""
    fb, has_pred = [], {e[1] for e in A.edges}
    for kd in ("I", "J"):
        seq = [n for n in A.nodes if n["kingdom"] == kd and (n["has_acc"] or "reign" in n["fields"])]
        for i, n in enumerate(seq):
            if n["id"] not in has_pred and i > 0:
                fb.append((seq[i - 1]["id"], n["id"], "order_fallback", None))
    return fb


def build(fn_rule: str = "slot") -> dict:
    verses, fns = load()
    b = Builder(verses, fns, fn_rule)
    for r in verses:
        b.verse(r)
    A = b.A
    return dict(policy="occ", fn_rule=fn_rule, nodes=A.nodes, edges=A.edges, fallback_edges=fallback_edges(A),
                syncs=A.syncs, conflicts=A.conflicts, log=A.log,
                occ_alias=[[k[0], k[1], v] for k, v in A.occ_alias.items()], union_classes=None)
