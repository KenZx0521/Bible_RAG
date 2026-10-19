"""The regnal layer's builder, ported from experiment A's layer_build.py (probe_C5
auto_layer.py, occ alias policy; ``compile_layer`` takes the inputs instead of reading the
store); fixed 2026-10-19 so the layer meets experiment A's reference layer with Solomon off the
Judah chain (docs/records/2026-10-19_kg_expansion_feasibility.md §6-1):

- R1a: a usurpation is the usurper's accession evidence, so Athaliah is a king, not a ghost;
- R1b: the span right before her usurpation clause is her reign (2ki.11.3);
- R1c: a king's own mother who takes his throne is a ``queen_usurp`` edge, not ``usurp``;
- R2: a death formula with a pronoun subject names the verse's reign-formula king (1ki.14.20);
- R3: the people make a named man king after the reigning one (``people``, 1ki.16.16);
- R4: X rebels against Y without 篡 is a usurpation when X is a known person and Y a reigning
  king (2ki.9.14);
- R5: a king with no predecessor edge who follows a usurper, with exactly one anointing verse
  in Kings between the two, is ``restored`` (2ki.11.12);
- R7: a son made king after his father while another king reigns is ``installed`` over the
  reigning king (2ki.23.34);
- R8: a reign formula over all Israel with no accession formula is the united monarchy 'U'
  (1ki.11.42), whose king starts no chain edge;
- R9: a successor's pronoun predecessor defaults to the reigning king only if this or the
  previous verse names him, so a foreign king's son is no king of Judah (2ki.19.37);
- R10: a bare 作王N年 that dates an event is no reign length (2ch.16.12, 2ch.35.19).
- R14: a usurpation or rebellion verse is the victim's death only when it says he was killed
  (殺): 2ki.9.14 is only Jehu's revolt, and 2ki.11.3 Athaliah's reign, not Ahaziah's death.

A death field records formulas only: ``natural`` is the 同睡 formula (a king killed in the
narrative before it keeps it, 1ki.22.40, 2ki.14.22), ``killed`` a usurpation verse that says so;
other deaths are not read. No card reads the field.

R6, R11 and R12 are in ``regnal_core``. The port's per-verse step order is kept (a fix adds a
step, ``step_people``, or a pass after the verses, ``restored_edges``, and moves none), and so
is first-value-wins: a field keeps its first value, an edge its first type, except that a typed
edge replaces a ``seat`` edge (R6). The footnote-alias step is the appendix-A rule
(fn_rule="slot", K0-2): a 又名／就是 footnote binds only a name that fills a king slot of a
regnal formula matched in that verse (successor > accession > synchronism reference); for 就是
the slot's king must be in the target king's kingdom; else it is rejected. fn_rule="probe" (the
probe's word pick) stays for comparison only.
"""
from __future__ import annotations

import re

from ragdata.kg.regnal_core import Layer, lexicons
from ragdata.kg.regnal_rules import (C, CHAIN_KINGDOMS, FOREIGN_DEATH, KMAP, N1, OPP, P_ACC0, P_ACC1, P_ACC_REV,
                                     P_ACC_SUCC_SYNC, P_AGE, P_AGE2, P_ANOINT, P_COUP_SYNC, P_MOTHER, P_PEOPLE,
                                     P_REBEL, P_REIGN, P_REIGN_END, P_RENAME, P_REPL, P_SEAT, P_SLEEP,
                                     P_SLEEP_PRON, P_SUCC, P_USURP, P_USURP_SPAN, P_VERB, UNITED, zh2int)

SLOT_PRIORITY = ("succ", "acc", "ref")


class Builder:
    def __init__(self, verses, fns, fn_rule):
        self.A, self.verses, self.fns, self.fn_rule = Layer(), verses, fns, fn_rule
        self.lex, self.plex = lexicons(verses)
        self.lex_set, self.plex_set = set(self.lex), set(self.plex)
        self.last, self.curk, self.ch_ptr = None, {}, None
        self.prev_t, self.reign_node = "", None   # R9: the previous verse; R2: this verse's named reign king

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

    @staticmethod
    def is_date(m, t):
        """R10: a bare 作王N年 followed by more of the sentence dates an event (2ch.16.12,
        2ch.35.19); a length has 共, 在, 登基 or a kingdom, or ends the sentence or the reign."""
        pre = m.group("pre") or ""
        bare = not m.group("k") and "共" not in m.group(0) and "在" not in pre and "登基" not in pre
        return bare and not P_REIGN_END.match(t, m.end())

    def step_reign(self, t, subj):
        for m in P_REIGN.finditer(t):
            if self.is_date(m, t):
                self.A.log.append(("reign_date_skipped", self.uk, m.group("v")))
                continue
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
                elif k == "以色列眾人的" and not nd["has_acc"]:
                    nd["kingdom"] = UNITED   # R8: all Israel and no accession formula (1ki.11.42)
            self.reign_node = nd if nm else None
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
        if not sleepers and self.reign_node is not None and P_SLEEP_PRON.search(t):
            nd = self.reign_node   # R2: 「…就與他列祖同睡」 after the verse's own reign formula
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
                father, default, etyp = None, False, typ
                if pred is not None and not self.is_ch:
                    cur = self.curk.get(pred["kingdom"])
                    if cur is not None and cur is not pred and cur["order"] > pred["order"]:
                        # R7: 「接續他父親F作王」 while a later king of F's kingdom reigns: X is
                        # installed over that king, F stays X's father (2ki.23.34)
                        pred, father, etyp = cur, pred["name"], "installed"
                if pred is None:
                    pred = sleepers[-1] if sleepers else subj
                    default = not sleepers
                if pred is None:
                    continue
                if default and not self.is_ch and not self.named_before(pred, t[:m.start("s")]):
                    A.log.append(("skip_unanchored_succ", uk, m.group("s")))   # R9
                    continue
                typ2 = "brother" if (etyp == "son" and "兄弟" + m.group("s") in t) else etyp
                sname = m.group("s")
                united = pred["kingdom"] == UNITED
                kd = None if united else pred["kingdom"]
                if self.is_ch:
                    s = A.resolve(sname, "J", uk, min_order=pred["order"] + 1)
                    if s is None:
                        s = A.new("J", sname, uk, pending=True, src="succ_ch")
                else:
                    s = A.resolve(sname, kd, uk, pending_first=True)
                    if s is None or (not s["pending"] and s["order"] <= pred["order"]):
                        s = A.new(kd, sname, uk, pending=True, src="succ")
                if not united:
                    A.add_edge(pred, s, typ2, uk)   # R8: a united-monarchy king starts no chain edge
                if typ2 == "son":
                    A.setf(s, "father", pred["name"], uk, "succ")
                if father:
                    A.setf(s, "father", father, uk, "succ")
                if m2:
                    A.setf(s, "age", zh2int(m2.group("a")), uk, "age2")
                self.slots.append(("succ", sname, s))

    def named_before(self, nd, head):
        """R9: a pronoun predecessor is the reigning king only if the previous verse or this
        verse before the successor's name names him."""
        text = self.prev_t + head
        return any(n in text for n in [nd["name"], *nd["aliases"]])

    def rebel(self, t):
        """R4: 「(F的兒子)X背叛Y」, X a person of the lexicon and Y a reigning king of Israel or
        Judah: (match, Y's node), or None."""
        for m in P_REBEL.finditer(t):
            if m.group("u") in self.plex_set and m.group("v") in self.lex_set and m.group("u") != m.group("v"):
                v = self.R(m.group("v"))
                if v is not None and v["has_acc"] and v["kingdom"] in CHAIN_KINGDOMS:
                    return m, v
        return None

    def step_usurp(self, t, subj):
        A, uk = self.A, self.uk
        if self.is_ch:
            return
        rb = None
        if not P_USURP.search(t):
            rb = self.rebel(t)
            if rb is None:
                return
        if rb is not None:
            uname, victim = rb[0].group("u"), rb[1]
        else:
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
        typ = "usurp"
        if victim["fields"].get("mother", [None])[0] == uname:
            typ = "queen_usurp"   # R1c: the king's own mother takes the throne (2ki.11.1-3)
        A.add_edge(victim, s, typ, uk)
        if "殺" in t:   # R14
            A.setf(victim, "death", "killed", uk, "usurp")
        s["has_acc"] = True   # R1a: taking the throne is the usurper's accession (pending ends after the verses)
        sp = P_USURP_SPAN.search(t)
        if sp and sp.group("n") == uname:   # R1b
            u, v = sp.group("u"), zh2int(sp.group("v"))
            A.setf(s, "reign", round(v if u == "年" else (v / 12 if u == "個月" else v / 365), 3), uk, "ki")
        uf = self.lex_suffix(rb[0].group("uf")) if rb is not None and rb[0].group("uf") else None
        if uf:
            A.setf(s, "father", uf, uk, "rebel")   # R4: 「F的兒子X背叛Y」 names X's father
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

    def step_people(self, t):
        """R3: the people make a named man king of a kingdom (1ki.16.16): a ``people`` edge from
        that kingdom's reigning king; the name is the longest lexicon suffix (a title before it)."""
        if self.is_ch:
            return
        for m in P_PEOPLE.finditer(t):
            nm = self.lex_suffix(m.group("pre"))
            kd = KMAP[m.group("k")]
            pred = self.curk.get(kd)
            if nm is None or pred is None or pred["name"] == nm:
                continue
            s = self.A.resolve(nm, kd, self.uk, pending_first=True)
            if s is None or (not s["pending"] and s["order"] <= pred["order"]):
                s = self.A.new(kd, nm, self.uk, pending=True, src="people")
            self.A.add_edge(pred, s, "people", self.uk)
            self.slots.append(("succ", nm, s))

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
        self.reign_node = None
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
        self.step_people(t)
        self.step_other_syncs(t)
        self.step_rename(t)
        self.step_footnotes(t)
        self.prev_t = t


def restored_edges(A, verses):
    """R5: a king with accession evidence and no predecessor edge whose predecessor in node
    order came in by usurpation, with exactly one anointing (``P_ANOINT``) in the Kings verses
    between their first evidence verses: a ``restored`` edge at that verse (2ki.11.12)."""
    pos = {r["unit_key"]: i for i, r in enumerate(verses)}
    has_pred = {e[1] for e in A.edges}
    into = {e[1]: e[2] for e in A.edges}
    for kd in CHAIN_KINGDOMS:
        seq = [n for n in A.nodes if n["kingdom"] == kd and (n["has_acc"] or "reign" in n["fields"])]
        for prev, n in zip(seq, seq[1:]):
            if n["id"] in has_pred or into.get(prev["id"]) not in ("usurp", "queen_usurp"):
                continue
            lo, hi = pos[prev["evidence"][0]], pos[n["evidence"][0]]
            hits = [r["unit_key"] for r in verses[lo + 1:hi] if r["book_id"] != "2ch" and P_ANOINT.search(r["text"])]
            if len(hits) == 1:
                A.add_edge(prev, n, "restored", hits[0])


def fallback_edges(A):
    """Order fallback edges (nodes with accession evidence and no explicit predecessor)."""
    fb, has_pred = [], {e[1] for e in A.edges}
    for kd in ("I", "J"):
        seq = [n for n in A.nodes if n["kingdom"] == kd and (n["has_acc"] or "reign" in n["fields"])]
        for i, n in enumerate(seq):
            if n["id"] not in has_pred and i > 0:
                fb.append((seq[i - 1]["id"], n["id"], "order_fallback", None))
    return fb


def compile_layer(verses, fns, fn_rule: str = "slot") -> dict:
    """The layer document of the in-scope verse rows and alias footnotes (``regnal_core.inputs``)."""
    b = Builder(verses, fns, fn_rule)
    for r in verses:
        b.verse(r)
    A = b.A
    for n in A.nodes:
        if n["has_acc"]:
            n["pending"] = False   # R1a: an accession (formula or usurpation) ends the pending state
    restored_edges(A, verses)
    return dict(policy="occ", fn_rule=fn_rule, nodes=A.nodes, edges=A.edges, fallback_edges=fallback_edges(A),
                syncs=A.syncs, conflicts=A.conflicts, log=A.log,
                occ_alias=[[k[0], k[1], v] for k, v in A.occ_alias.items()], union_classes=None)
