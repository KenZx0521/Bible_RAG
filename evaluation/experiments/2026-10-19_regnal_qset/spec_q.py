"""The question set's specification (qset.md §1, §2): cells from the reference layer, the P1/P2 split by
king, quotas, writer jobs, personas and writer models. CPU only; the spec goes to <root>/spec.json.

* Reference: ref_layer_v2.json when it exists, else derived in memory from experiment A's frozen
  ref_layer.json (q_common). Chains follow the ``pred`` links per kingdom; a node of any other kingdom
  (所羅門 as 'U') is off the chains. 所羅門 on a chain is refused (Kay 2026-10-19).
* Cells (positives, all on the reference chains):
    S1a  start x, k ∈ {±2, ±3}, gold = the king k places away;
    S1b  two kings of one kingdom 2–4 places apart, gold = the number of handovers;
    S1c  Israel only (the engine counts ``usurp`` edges; 亞她利雅's queen_usurp is not one): the n-th
         usurper after x within +3, at least 2 handovers away, gold = that king;
    S4   a king of Judah with an accession age whose walk back over the reigns (engine convention:
         reign lengths end to end) lands on a king with margin > 0; 亞哈謝 (J06) and 約雅斤 (J19) left out.
* Near misses (should not take the card): N1 one recorded attribute, N2 an event, N3 an accession
  synchronism, N4 contemporaries, N5 family line; their kings belong to the same side.
* Split: kings of one primary name form one unit (34 units); units are stratified (has an S4 start /
  has an S1c start / kingdom), shuffled with SEED per stratum, and dealt alternately to p1 and p2.
* Jobs (per side): exactly one S1a each, at most one S1b, S1c, S4 and one near miss (2–5 slots). A cell
  drawn twice lands in two jobs of different personas. Slots get opaque labels q1… in a shuffled order.

    spec_q.py build [--root R] [--seed N]     write <root>/spec.json (prints counts and sha only)
    spec_q.py check [--root R]                rebuild and compare with <root>/spec.json
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from q_common import (INTENT, KINGDOMS, KNAME, NEAR_FAMILIES, PERSONAS, POS_TYPES, QUOTA, REF_A, REF_A_SHA256,
                      REF_V2, REF_V2_DERIVED_SHA256, ROOT, SEED, SETS, WRITERS, QError, canonical, read_json,
                      sha256_bytes, split_evenly, write_json)

SCHEMA = "regnal_qset_spec.v1"
SPEC_FILE = "spec.json"
S1A_K = (2, 3, -2, -3)
S1B_D = (2, 3, 4)
S1C_MAX_K, S1C_MIN_K = 3, 2
S4_EXCLUDE = ("J06", "J19")          # Kings / Chronicles give different accession ages
EXCLUDED_KING = "所羅門"
MAX_PER_CELL = 2
JOB_MAX = 5
ATTR_ASPECTS = ("reign_length", "accession_age", "mother", "father")
ATTR_FIELD = {"accession_age": "age", "mother": "mother", "father": "father"}   # reign_length: every king
EVENT_ASPECTS = ("death", "came_to_throne", "remembered_for", "prophet")
KIN_ASPECTS = {"J": "generations_from_david", "I": "grandfather"}


# ---------------------------------------------------------------- reference layer

@dataclass(frozen=True)
class Ref:
    rows: tuple
    sha256: str
    source: str              # "ref_layer_v2" | "derived:79d57efe"
    matches_derivation: bool


def derive_v2(rows_a: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """所羅門 (J00) out, 羅波安 (J01) the Judah founder (Kay 2026-10-19); everything else unchanged."""
    out = [copy.deepcopy(dict(r)) for r in rows_a if r["id"] != "J00"]
    for r in out:
        if r["pred"] and r["pred"][0] == "J00":
            r["pred"] = [None, "founder", r["pred"][2]]
    return out


def load_ref(v2: Path = REF_V2, a: Path = REF_A) -> Ref:
    """ref_layer_v2 if present; else the in-memory derivation from A's frozen file (sha checked; read only)."""
    raw_a = Path(a).read_bytes()
    if sha256_bytes(raw_a) != REF_A_SHA256:
        raise QError(f"{Path(a).name} sha256 {sha256_bytes(raw_a)[:12]} is not the frozen {REF_A_SHA256[:12]}")
    derived = derive_v2(json.loads(raw_a.decode("utf-8")))
    if sha256_bytes(canonical(derived)) != REF_V2_DERIVED_SHA256:
        raise QError("the in-memory ref_layer_v2 derivation does not hash to the pinned sha")
    if Path(v2).is_file():
        raw = Path(v2).read_bytes()
        rows = json.loads(raw.decode("utf-8"))
        return Ref(tuple(rows), sha256_bytes(raw), "ref_layer_v2", rows == derived)
    return Ref(tuple(derived), REF_V2_DERIVED_SHA256, "derived:" + REF_A_SHA256[:8], True)


class Chains:
    """Succession chains of the reference rows (``pred`` links), names and the S4 walk back."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        self.rows = {r["id"]: r for r in rows}
        self.chain = {kd: self._walk(kd) for kd in KINGDOMS}
        self.pos = {x: (kd, i) for kd, ids in self.chain.items() for i, x in enumerate(ids)}
        if any(self.rows[x]["name"] == EXCLUDED_KING for x in self.pos):
            raise QError(f"{EXCLUDED_KING} is on a chain (Kay 2026-10-19: off the Judah chain)")

    def _walk(self, kd: str) -> list[str]:
        ids = sorted(i for i, r in self.rows.items() if r["kingdom"] == kd)
        nxt: dict[str, list[str]] = {}
        roots = []
        for i in ids:
            p = (self.rows[i]["pred"] or [None])[0]
            (nxt.setdefault(p, []).append(i) if p in ids else roots.append(i))
        if len(roots) != 1 or any(len(v) != 1 for v in nxt.values()):
            raise QError(f"kingdom {kd}: the pred links are not one chain (roots {roots})")
        seq = [roots[0]]
        while seq[-1] in nxt:
            seq.append(nxt[seq[-1]][0])
        if len(seq) != len(ids):
            raise QError(f"kingdom {kd}: {len(ids) - len(seq)} node(s) not reached from the root")
        return seq

    def on_chain(self) -> list[str]:
        return [x for kd in KINGDOMS for x in self.chain[kd]]

    def kingdom(self, x: str) -> str:
        return self.pos[x][0]

    def idx(self, x: str) -> int:
        return self.pos[x][1]

    def name(self, x: str) -> str:
        return self.rows[x]["name"]

    def names(self, x: str) -> list[str]:
        r = self.rows[x]
        return list(dict.fromkeys([r["name"]] + [a[0] for a in r["aliases"]]))

    def safe_names(self, x: str) -> list[str]:
        """Names the writer may use: an alias that is another chain king's name is never offered."""
        taken = {n for y in self.on_chain() if y != x for n in self.names(y)}
        return [n for n in self.names(x) if n == self.name(x) or n not in taken]

    def edge_into(self, x: str) -> str | None:
        p = self.rows[x]["pred"]
        return p[1] if p else None

    def field(self, x: str, key: str) -> Any:
        v = self.rows[x].get(key)
        return None if v is None else v[0]

    def reign(self, x: str) -> float | None:
        v = self.rows[x].get("reign")
        return None if v is None else float(v[1])

    def homonyms(self, x: str) -> list[str]:
        """Chain kings (x included, chain order) sharing x's primary name."""
        return [y for y in self.on_chain() if self.name(y) == self.name(x)]

    def born(self, x: str) -> tuple[str, float, int] | None:
        """(king at x's birth, margin in years, kings walked back) under the engine's convention, or None."""
        age = self.field(x, "age")
        if age is None or self.kingdom(x) != "J":
            return None
        rem, ids = float(age), self.chain["J"]
        for back, j in enumerate(range(self.idx(x) - 1, -1, -1), 1):
            r = self.reign(ids[j])
            if r is None:
                return None
            if rem < r:
                return ids[j], min(rem, r - rem), back
            rem -= r
        return None

    def syncs(self, x: str) -> list[tuple[str, int]]:
        """x's primary accession synchronisms with chain kings of the other kingdom: (other, year)."""
        return [(s[0], s[1]) for s in self.rows[x]["sync"] if s[3] == "primary" and s[0] in self.pos]


# ---------------------------------------------------------------- cells, units, split

def cells(ch: Chains) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in POS_TYPES}
    for kd, ids in ch.chain.items():
        for p, x in enumerate(ids):
            for k in S1A_K:
                if 0 <= p + k < len(ids):
                    out["S1a"].append(_cell("S1a", kd, x, gold=ids[p + k], k=k))
            for d in S1B_D:
                if p + d < len(ids):
                    out["S1b"].append(_cell("S1b", kd, x, gold=d, other=ids[p + d], d=d))
            if kd == "I":
                n = 0
                for k in range(1, S1C_MAX_K + 1):
                    if p + k >= len(ids):
                        break
                    if ch.edge_into(ids[p + k]) == "usurp":
                        n += 1
                        if k >= S1C_MIN_K:
                            out["S1c"].append(_cell("S1c", kd, x, gold=ids[p + k], n=n, steps=k))
            if kd == "J" and x not in S4_EXCLUDE:
                b = ch.born(x)
                if b and b[1] > 0:
                    out["S4"].append(_cell("S4", kd, x, gold=b[0], margin=b[1], steps=b[2]))
    return out


def _cell(qtype: str, kd: str, start: str, gold: Any, other: str | None = None, k: int | None = None,
          n: int | None = None, d: int | None = None, margin: float | None = None,
          steps: int | None = None) -> dict[str, Any]:
    key = (f"{start}{k:+d}" if qtype == "S1a" else f"{start}-{other}" if qtype == "S1b"
           else f"{start}#{n}" if qtype == "S1c" else start)
    return {"qtype": qtype, "cell": f"{qtype}:{key}", "kingdom": kd, "start": start, "other": other, "k": k,
            "n": n, "d": d, "gold": gold, "margin": margin, "steps": steps}


def units(ch: Chains) -> list[tuple[str, ...]]:
    """Chain kings grouped by primary name (同名王併成一個單位), each unit sorted, units by first id."""
    by: dict[str, list[str]] = {}
    for x in ch.on_chain():
        by.setdefault(ch.name(x), []).append(x)
    return sorted((tuple(sorted(v)) for v in by.values()), key=lambda u: u[0])


def split(ch: Chains, seed: int = SEED) -> dict[str, str]:
    """{king id: 'p1' | 'p2'}: units stratified, shuffled per stratum, dealt alternately (carried over)."""
    c = cells(ch)
    s4 = {x["start"] for x in c["S4"]}
    s1c = {x["start"] for x in c["S1c"]}

    def tag(u: tuple[str, ...]) -> str:
        return "S4" if s4 & set(u) else "S1c" if s1c & set(u) else ch.kingdom(u[0])
    strata: dict[str, list[tuple[str, ...]]] = {}
    for u in units(ch):
        strata.setdefault(tag(u), []).append(u)
    part, turn = {}, 0
    for name in sorted(strata):
        us = list(strata[name])
        random.Random(f"{seed}:split:{name}").shuffle(us)
        for u in us:
            for x in u:
                part[x] = SETS[turn % 2]
            turn += 1
    return part


def side_cells(ch: Chains, part: Mapping[str, str], side: str) -> dict[str, list[dict[str, Any]]]:
    """A side's cells: every king the question names (start, and other for S1b) is on that side; the
    answer king is never written into a question, so it may be on either side."""
    def ok(c: Mapping[str, Any]) -> bool:
        return all(part[x] == side for x in (c["start"], c["other"]) if x)
    return {t: [c for c in cs if ok(c)] for t, cs in cells(ch).items()}


# ---------------------------------------------------------------- draws

def spread(pool: Sequence[Mapping[str, Any]], rng: random.Random, key: str = "start") -> list[dict[str, Any]]:
    """Shuffled, then every key value once before any repeats (stable within a rank)."""
    items = [dict(p) for p in pool]
    rng.shuffle(items)
    seen: dict[Any, int] = {}
    ranked = []
    for it in items:
        ranked.append((seen.get(it[key], 0), it))
        seen[it[key]] = seen.get(it[key], 0) + 1
    return [it for _, it in sorted(ranked, key=lambda r: r[0])]


def draw_s1a(pool: Sequence[Mapping[str, Any]], quota: int, rng: random.Random) -> list[dict[str, Any]]:
    """Kingdom × direction halves; |k| = 2 and 3 about 2:1; without replacement."""
    out = []
    strata = [(kd, s) for kd in KINGDOMS for s in (1, -1)]
    for (kd, s), n in zip(strata, split_evenly(quota, len(strata))):
        n2 = round(n * 2 / 3)
        p2 = spread([c for c in pool if c["kingdom"] == kd and c["k"] == 2 * s], rng)
        p3 = spread([c for c in pool if c["kingdom"] == kd and c["k"] == 3 * s], rng)
        take = p2[:n2] + p3[:n - n2]
        take += (p2[n2:] + p3[n - n2:])[:n - len(take)]
        if len(take) < n:
            raise QError(f"S1a {KNAME[kd]} {'+' if s > 0 else '-'}: {len(take)} cells for a quota of {n}")
        out += take
    return out


def draw_s1b(pool: Sequence[Mapping[str, Any]], quota: int, rng: random.Random) -> list[dict[str, Any]]:
    """Kingdoms halved, distances 2/3/4 evened; without replacement."""
    out = []
    for kd, n in zip(KINGDOMS, split_evenly(quota, len(KINGDOMS))):
        mine = [c for c in pool if c["kingdom"] == kd]
        by_d = {d: spread([c for c in mine if c["d"] == d], rng) for d in S1B_D}
        take = [c for d, m in zip(S1B_D, split_evenly(n, len(S1B_D))) for c in by_d[d][:m]]
        rest = [c for c in spread(mine, rng) if c not in take]
        take += rest[:n - len(take)]
        if len(take) < n:
            raise QError(f"S1b {KNAME[kd]}: {len(take)} pairs for a quota of {n}")
        out += take
    return out


def draw_repeat(pool: Sequence[Mapping[str, Any]], quota: int, rng: random.Random, qtype: str) -> list[dict[str, Any]]:
    """S1c / S4: each cell at most MAX_PER_CELL times, all cells once before any twice."""
    seq = [c for _ in range(MAX_PER_CELL) for c in spread(pool, rng)]
    if len(seq) < quota:
        raise QError(f"{qtype}: {len(pool)} cells × {MAX_PER_CELL} < quota {quota}")
    return seq[:quota]


def draw_near(ch: Chains, part: Mapping[str, str], side: str, quota: Mapping[str, int],
              rng: random.Random) -> list[dict[str, Any]]:
    kings = [x for x in ch.on_chain() if part[x] == side]
    pool = [{"start": x} for x in kings]
    out = []
    n1 = spread(pool, rng)[:quota["N1"]]
    for i, p in enumerate(n1):
        x = p["start"]
        ok = [a for a in ATTR_ASPECTS if a not in ATTR_FIELD or ch.field(x, ATTR_FIELD[a])]
        out.append(_near("N1", ch, x, aspect=ok[i % len(ok)]))
    for i, p in enumerate(spread(pool, rng)[:quota["N2"]]):
        out.append(_near("N2", ch, p["start"], aspect=EVENT_ASPECTS[i % len(EVENT_ASPECTS)]))
    pairs = [{"start": x, "other": o, "year": y} for x in kings for o, y in ch.syncs(x) if part[o] == side]
    take = spread(pairs, rng)[:quota["N3"]]
    if len(take) < quota["N3"]:
        raise QError(f"N3 {side}: {len(take)} synchronisms for a quota of {quota['N3']}")
    out += [_near("N3", ch, p["start"], other=p["other"]) for p in take]
    out += [_near("N4", ch, p["start"]) for p in spread(pool, rng)[:quota["N4"]]]
    by_kd = {kd: spread([p for p in pool if ch.kingdom(p["start"]) == kd], rng) for kd in KINGDOMS}
    used = {kd: 0 for kd in KINGDOMS}
    for i in range(quota["N5"]):                       # Judah, Israel, Judah, …
        kd = ("J", "I")[i % 2]
        out.append(_near("N5", ch, by_kd[kd][used[kd]]["start"], aspect=KIN_ASPECTS[kd]))
        used[kd] += 1
    return out


def _near(family: str, ch: Chains, x: str, aspect: str | None = None, other: str | None = None) -> dict[str, Any]:
    return {"qtype": family, "cell": f"{family}:{x}:{aspect or other or ''}", "kingdom": ch.kingdom(x), "start": x,
            "other": other, "k": None, "n": None, "d": None, "gold": None, "aspect": aspect}


# ---------------------------------------------------------------- jobs

def slot_type(item: Mapping[str, Any]) -> str:
    return "near" if item["qtype"] in NEAR_FAMILIES else item["qtype"]


def build_jobs(side: str, items: Sequence[Mapping[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """One S1a per job; S1b, S1c, S4 and near misses at most one each, smallest job first (ties random);
    a cell drawn twice goes to a job of another persona."""
    s1a = [dict(i) for i in items if i["qtype"] == "S1a"]
    rng.shuffle(s1a)
    personas = rng.sample(PERSONAS, len(PERSONAS))
    jobs = [{"job_id": f"{side}-j{n:02d}", "set": side, "persona": personas[n % len(personas)],
             "writer": WRITERS[n % len(WRITERS)], "items": [x]} for n, x in enumerate(s1a)]
    for t in ("S1b", "S1c", "S4", "near"):
        pending = [dict(i) for i in items if slot_type(i) == t]
        rng.shuffle(pending)
        for it in pending:
            same = [j for j in jobs if any(o["cell"] == it["cell"] for o in j["items"])]
            banned_personas = {j["persona"] for j in same}
            cands = [j for j in jobs if len(j["items"]) < JOB_MAX and j not in same
                     and j["persona"] not in banned_personas and not any(slot_type(o) == t for o in j["items"])]
            if not cands:
                raise QError(f"{side}: no job can take {it['cell']}")
            least = min(len(j["items"]) for j in cands)
            rng.choice([j for j in cands if len(j["items"]) == least])["items"].append(it)
    if any(len(j["items"]) < 2 for j in jobs):
        raise QError(f"{side}: a job has fewer than 2 slots")
    for j in jobs:
        rng.shuffle(j["items"])
        j["slots"] = [dict(it, slot=f"q{i}", item_id=f"{j['job_id']}-q{i}", set=side,
                           kind="near" if slot_type(it) == "near" else "pos", intent=INTENT[it["qtype"]])
                      for i, it in enumerate(j.pop("items"), 1)]
    return jobs


def build_spec(ref: Ref, seed: int = SEED) -> dict[str, Any]:
    ch = Chains(ref.rows)
    part = split(ch, seed)
    jobs, avail, drawn = {}, {}, {}
    for side in SETS:
        rng = random.Random(f"{seed}:draw:{side}")
        sc = side_cells(ch, part, side)
        avail[side] = {t: len(v) for t, v in sc.items()}
        q = QUOTA[side]
        items = (draw_s1a(sc["S1a"], q["S1a"], rng) + draw_s1b(sc["S1b"], q["S1b"], rng)
                 + draw_repeat(sc["S1c"], q["S1c"], rng, "S1c") + draw_repeat(sc["S4"], q["S4"], rng, "S4")
                 + draw_near(ch, part, side, q, rng))
        drawn[side] = {t: sum(1 for i in items if i["qtype"] == t) for t in (*POS_TYPES, *NEAR_FAMILIES)}
        jobs[side] = build_jobs(side, items, random.Random(f"{seed}:jobs:{side}"))
    order = [j["job_id"] for pair in zip(*(jobs[s] for s in SETS)) for j in pair]
    longest = max(SETS, key=lambda s: len(jobs[s]))
    order += [j["job_id"] for j in jobs[longest][min(len(jobs[s]) for s in SETS):]]
    return {"schema": SCHEMA, "seed": seed,
            "ref": {"source": ref.source, "sha256": ref.sha256, "matches_derivation": ref.matches_derivation},
            "chains": ch.chain, "partition": dict(sorted(part.items())), "units": [list(u) for u in units(ch)],
            "cells_all": {t: len(v) for t, v in cells(ch).items()}, "cells_by_side": avail, "quota": QUOTA,
            "drawn": drawn, "jobs": [j for s in SETS for j in jobs[s]], "order": order}


def spec_sha(spec: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical(spec))


def summary(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Counts only (never king names of p2): the CLI's output and the prereg's record."""
    out = {"sha256": spec_sha(spec), "ref": spec["ref"], "cells_all": spec["cells_all"],
           "cells_by_side": spec["cells_by_side"], "drawn": spec["drawn"]}
    for s in SETS:
        js = [j for j in spec["jobs"] if j["set"] == s]
        out[s] = {"kings": sum(1 for v in spec["partition"].values() if v == s), "jobs": len(js),
                  "slots": sum(len(j["slots"]) for j in js),
                  "job_sizes": {str(n): sum(1 for j in js if len(j["slots"]) == n) for n in range(2, JOB_MAX + 1)},
                  "writers": {w: sum(1 for j in js if j["writer"] == w) for w in WRITERS},
                  "personas": {p: sum(1 for j in js if j["persona"] == p) for p in PERSONAS}}
    return out


def jobs_by_id(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {j["job_id"]: j for j in spec["jobs"]}


def probe_job(spec: Mapping[str, Any], model: str) -> dict[str, Any]:
    """The probe's job: a p1 job's first three slot kinds (S1a, a positive, a near miss), relabelled.
    Its output never enters the question set."""
    p1 = [j for j in spec["jobs"] if j["set"] == "p1"]
    for j in p1:
        kinds = [s["kind"] for s in j["slots"]]
        if len(j["slots"]) >= 3 and "near" in kinds:
            pos = [s for s in j["slots"] if s["kind"] == "pos"][:2]
            near = [s for s in j["slots"] if s["kind"] == "near"][:1]
            slots = [dict(s, slot=f"q{i}", item_id=f"probe-q{i}", set="probe") for i, s in enumerate(pos + near, 1)]
            return {"job_id": "probe", "set": "probe", "persona": j["persona"], "writer": model, "slots": slots,
                    "from_job": j["job_id"]}
    raise QError("no p1 job with three slots and a near miss")


def load_spec(root: Path = ROOT) -> dict[str, Any]:
    path = Path(root) / SPEC_FILE
    if not path.is_file():
        raise QError(f"{SPEC_FILE} missing in {root}: run spec_q.py build first")
    return read_json(path)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="問法集規格（CPU）")
    ap.add_argument("cmd", choices=("build", "check"))
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    spec = build_spec(load_ref(), a.seed)
    if a.cmd == "check":
        old = load_spec(a.root)
        same = spec_sha(old) == spec_sha(spec)
        print(json.dumps({"same": same, "stored": spec_sha(old), "rebuilt": spec_sha(spec)}, ensure_ascii=False))
        return 0 if same else 1
    path = Path(a.root) / SPEC_FILE
    if path.is_file() and spec_sha(read_json(path)) != spec_sha(spec):
        raise QError(f"{path} exists with another sha; move it away first (spec changes are recorded, not silent)")
    write_json(path, spec, a.root)
    print(json.dumps(summary(spec), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except QError as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False))
        sys.exit(2)
