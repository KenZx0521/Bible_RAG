"""The P1/P2 question-set specification of the GEN confirmation set (prereg §5.4, §5.6; qset.md §2): which slots and
near misses each writer job gets. CPU only; writes store qset/<set>/spec.json (g_common.write_json) and prints
counts and the sha256 only (never a P2 slot, name or near-miss person).

Positives (prereg §5.4).
* P1: 50 positives from the 14 stage-0 GEN F1/F5 development slots (the GEN items of stage-0's frozen items.json
  with qtype F1/F5, rebuilt as pool.json rows by the pool's own rule: ``dev_rows``). Repeats are unavoidable; each
  copy is a new job, so each is newly worded. Interpretation: the 50 follow pool.json's stratum shares (largest
  remainder over F1c5, F1c11, F5c5, F5c11, ties by stratum order: 12, 10, 23, 5), so the rule is tuned on the mix
  G1 is judged on (P2 is a near-proportional sample of the pool; the dev set alone is 12 F1 and 2 F5); within a
  stratum the dev slots are cycled in sid order, every slot once before any twice.
* P2: ``random.Random(P2_SEED).sample(sorted(pool sids), 50)``, no repeats.
Near misses: 20 per set over the 14 families of §5.4, allocated by NEAR_FAMILIES (twice: N2, d = 1 (F1 and F5),
flood / F3, the Cain line, Luke 3 / 1 Chronicles 1, the two common words; once: the other eight). Persons are chosen
at build time from the layer (``gencard.parse``: chains, lifespans, sons, guarded names and their common words),
gen_names (the Cain line, the other books) and the text layer (Genesis 12-50 names, checked). Each item is its
source's first candidate whose key (``near_key``: the name pair, or family, person and word for one person) is not
taken: not used earlier in the set, for P2 not one of P1's near misses (read from the stored P1 spec, whose sha256
the P2 spec records, so no later change of the layer or of this module can make P2 repeat a P1 near miss), and for
P1 not a pool slot's (x, y) pair (§5.4: the rule is tuned on P1 and never on a pool slot's wording, so no P1 near miss
names a pool pair; P2 is never tuned on and may). Cain-line and post-Genesis-12 pairs are fixed name pairs (no layer
holds those lines; famous names, no text), every name checked against gen_names or the text layer.
Jobs (sized from qset's measured costs, qset.md §9, its store ledger read only: 2-3-slot writer jobs cost opus
0.016-0.018 USD (max 0.026), sonnet 0.009-0.010 (max 0.015), about 0.002 per extra slot): JOB_SIZE 3, so 24 jobs per
set and 48 in all, about 0.7 USD plus one refill round, inside QSET_CAP_USD 3 with more than 2 USD to spare; each
job's cap is QSET_JOB_CAP_USD['gen'] (0.2, about 8x qset's largest job). Positives are dealt round-robin in (stratum,
sid, copy) order, so no job holds one slot twice; near misses go to the smallest jobs (ties: the lower index).
Writer = WRITERS[j % 2] (half each), persona = PERSONAS[j % 5] (qset's five; with alternating writers every pair
recurs evenly). Slot labels q1.. follow a shuffle by ``random.Random(f"{P2_SEED}:{set}:slots")`` (the only stream
besides the P2 sample; P2_SEED is the only seed). The spec holds no timestamp: a rebuild has the same bytes.

    spec_qg.py build --set p1|p2      write qset/<set>/spec.json (refused when it exists with another sha)
    spec_qg.py check --set p1|p2      rebuild and compare with the stored spec
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import g_common as GC
import pool_g

SCHEMA = "gen_confirm.qset_spec.v1"
SETS = GC.QSET_SETS
QSET_DIR = GC.QSET_ROOT.relative_to(GC.OUT_ROOT)                # "qset": the ledger's qset base
SPEC_FILE = GC.QSET_SPEC
N_POS, N_NEAR, N_DEV = GC.N_POS, GC.N_NEAR, GC.N_DEV       # power_g.P2_POSITIVES, run_g.P2_N, the dev slots
JOB_SIZE = GC.QSET_JOB_SIZE
WRITERS = ("opus", "sonnet")
PERSONAS = ("sunday_school", "casual", "seminary", "search_box", "reading")   # qset's five
STRATA = pool_g.STRATA
DEV_QTYPES = ("F1", "F5")
# prereg §5.4's 14 families in its order -> the candidate source of each of their items (20 per set)
NEAR_FAMILIES = (("N2", ("n2", "n2")), ("lifespan", ("lifespan",)), ("d1", ("d1_f1", "d1_f5")),
                 ("flood_f3", ("flood", "f3")), ("f1_far", ("f1_far",)), ("cross_noah", ("cross",)),
                 ("cain_line", ("cain", "cain")), ("terah_sons", ("terah",)), ("luke_chron", ("luke", "chron")),
                 ("after_gen12", ("after12",)), ("generations", ("gens",)), ("longest", ("longest",)),
                 ("yes_no", ("yes_no",)), ("common_word", ("word0", "word1")))
# Genesis 4:17-22 (no layer holds Cain's line): each pair has a chain namesake (以諾, 拉麥) and a Cain-line name
CAIN_PAIRS = (("該隱", "以諾"), ("以諾", "以拿"), ("瑪土撒利", "拉麥"), ("拉麥", "雅八"))
AFTER12_PAIRS = (("亞伯拉罕", "以撒"), ("以撒", "雅各"), ("雅各", "約瑟"))
BOOKS = MappingProxyType({"luke": "路加福音", "chron": "歷代志上"})
BOOK_EN = MappingProxyType({"luke": "the genealogy of Luke 3", "chron": "the genealogy of 1 Chronicles 1"})
F1_MAX_D, FAR_MIN_D, GENS_MIN_D = 4, 5, 3


class SpecError(ValueError):
    """The inputs cannot give the specified set (too few candidates, a name not in the lists, ...)."""


@dataclass(frozen=True)
class Lists:
    """Name lists no layer holds; ``later_names`` (Genesis 12-50 surfaces) None skips that check (tests)."""
    cain_pairs: tuple[tuple[str, str], ...] = CAIN_PAIRS
    after12_pairs: tuple[tuple[str, str], ...] = AFTER12_PAIRS
    books: Mapping[str, str] = field(default_factory=lambda: BOOKS)
    later_names: frozenset[str] | None = None


# ---------------------------------------------------------------- positives
def dev_rows() -> list[dict]:
    """Stage-0's 14 GEN F1/F5 development slots as pool.json rows (pool_g.build's row rule, sids D00..D13)."""
    S = GC.stage0()
    G, I, E = S.gen_layer, S.items_x, S.engine_x
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise SpecError(f"{GC.GEN_LAYER}: sha256 is not {GC.GEN_LAYER_SHA256_PREFIX} (prereg §2)")
    gen = G.load()
    every = I.f1_candidates(gen, {}) + I.f5_candidates(gen, {})
    dev = {(it["qtype"], it["path"][0], it["path"][-1]) for it in GC.read_json(S.x_common.ITEMS)["items"]
           if it["family"] == "GEN" and it["qtype"] in DEV_QTYPES}
    name = lambda i: G.node(gen, i)["name"]  # noqa: E731
    stated, gold_count = pool_g.stated_numbers(S), Counter(c["gold"] for c in every)
    kept = sorted((c for c in every if pool_g._key(c) in dev),
                  key=lambda c: (c["qtype"], c["chapter"], *pool_g._key(c)[1:]))
    if len(kept) != N_DEV or len(dev) != N_DEV:
        raise SpecError(f"{len(kept)} of {len(dev)} development slots found, not {N_DEV}")
    rows = []
    for k, c in enumerate(kept):
        p = c["path"]
        x, y = p[0], p[-1]
        card = E.card({"family": "GEN", "seeds": [x, y], "gold": c["gold"],
                       "keys": [{"type": "arith", "classes": ["A", "Y"]}]}, gen=gen)
        rows.append(dict(
            sid=f"D{k:02d}", qtype=c["qtype"], chapter=c["chapter"], stratum=f"{c['qtype']}c{c['chapter']}",
            d=len(p) - 1, x=x, y=y, pair=f"{x}>{y}", persons=list(p),
            edges=[f"{p[i]}>{p[i + 1]}" for i in range(len(p) - 1)], gold=c["gold"],
            marker_required=pool_g.marker_required(name(x), name(y)),
            homonym=any(name(z) in I.GEN_HOMONYMS for z in (x, y)), shem_x=name(x) == "閃",
            coincide=c["gold"] in stated, dup_gold=gold_count[c["gold"]] > 1,
            verify_gold_ok=not I.verify_gold(I.gen_item(gen, c)),
            covered_gold_seeds=bool(card["covered"]), chars_g=card["chars_g"]))
    return rows


def shares(pool: Sequence[Mapping[str, Any]], n: int) -> dict[str, int]:
    """Stratum counts for n items in proportion to the pool (largest remainder, ties by stratum order)."""
    N = [sum(r["stratum"] == s for r in pool) for s in STRATA]
    q = [n * c / sum(N) for c in N]
    out = [math.floor(v) for v in q]
    for k in sorted(range(len(STRATA)), key=lambda k: (-round(q[k] - out[k], 9), k))[: n - sum(out)]:
        out[k] += 1
    return dict(zip(STRATA, out))


def p1_positives(dev: Sequence[Mapping[str, Any]], pool: Sequence[Mapping[str, Any]], n: int = N_POS) -> list[dict]:
    out = []
    for s, k in shares(pool, n).items():
        mine = sorted((r for r in dev if r["stratum"] == s), key=lambda r: r["sid"])
        if k and not mine:
            raise SpecError(f"stratum {s}: no development slot for {k} positives")
        out += [{**mine[c % len(mine)], "kind": "pos", "copy": c // len(mine)} for c in range(k)]
    return out


def p2_positives(pool: Sequence[Mapping[str, Any]], n: int = N_POS) -> list[dict]:
    by_sid = {r["sid"]: r for r in pool}
    picked = random.Random(GC.P2_SEED).sample(sorted(by_sid), n)
    rows = [{**by_sid[s], "kind": "pos", "copy": 0} for s in picked]
    return sorted(rows, key=lambda r: (STRATA.index(r["stratum"]), r["sid"]))


# ---------------------------------------------------------------- near-miss candidates (from the layer)
def interleave(*lists: Sequence[dict]) -> list[dict]:
    out, n = [], max((len(x) for x in lists), default=0)
    for i in range(n):
        out += [x[i] for x in lists if i < len(x)]
    return out


def _pair(L, a: str, b: str, **extra: Any) -> dict:
    return {"x": L.name[a], "y": L.name[b], "x_id": a, "y_id": b, "chapter": L.chapter[a], **extra}


def _one(L, a: str, **extra: Any) -> dict:
    return {"x": L.name[a], "y": None, "x_id": a, "y_id": None, "chapter": L.chapter[a], **extra}


def _pairs(L, ok: Callable[[str, str, int], bool]) -> list[dict]:
    """Same-chapter (ancestor, descendant) pairs passing ``ok(a, b, d)``, interleaved over the chapters."""
    per = []
    for ch in sorted(L.chains):
        ids = L.chains[ch]
        per.append([_pair(L, a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if ok(a, b, L.distance(a, b))])
    return interleave(*per)


def _alive_at_birth(L, a: str, b: str) -> bool:
    age, life = L.age_at_birth(a, b), L.lifespan[a]
    return age is not None and life is not None and age < life


def _died_after(L, a: str, b: str) -> bool:
    """b alive in the year a died (a not taken): the pool's F5 shape."""
    age, la, lb = L.age_at_birth(a, b), L.lifespan[a], L.lifespan[b]
    return a not in L.taken and None not in (age, la, lb) and 0 < la - age < lb


def _dies_first(L, a: str, b: str) -> bool:
    """b died while a lived (N2: a's age in the year b died is defined)."""
    age, la, lb = L.age_at_birth(a, b), L.lifespan[a], L.lifespan[b]
    return not {a, b} & L.taken and None not in (age, la, lb) and age + lb < la


def candidates(L, lists: Lists) -> dict[str, list[dict]]:
    """Every near-miss source's candidates in pick order (P1 takes the first ones, P2 the next)."""
    chs = sorted(L.chains)
    first, last = L.chains[chs[0]], L.chains[chs[-1]]
    f1 = lambda a, b, d: 2 <= d <= F1_MAX_D and _alive_at_birth(L, a, b)  # noqa: E731
    persons = interleave(*([_one(L, x) for x in L.chains[ch] if x not in L.taken and L.lifespan[x]] for ch in chs))
    tail = L.gen["nodes"][[n["id"] for n in L.gen["nodes"]].index(last[-1])]
    sons = sorted(tail.get("sons") or (), key=lambda s: (s not in L.son_namesakes, (tail.get("sons") or []).index(s)))
    words = []
    for g in L.guarded:
        gid, ids = L.id_of[g], L.chains[L.chapter[L.id_of[g]]]
        near = sorted((x for x in ids if abs(L.index[x] - L.index[gid]) >= 2), key=lambda x: abs(L.index[x] - L.index[gid]))
        words.append([_one(L, x, word=L.guarded[g][0]) for x in near])
    out = {
        "n2": _pairs(L, lambda a, b, d: d >= 2 and _dies_first(L, a, b)),
        "lifespan": persons,
        "d1_f1": _pairs(L, lambda a, b, d: d == 1),
        "d1_f5": _pairs(L, lambda a, b, d: d == 1 and _died_after(L, a, b)),
        "flood": [_one(L, first[-1]), _one(L, last[0])],
        "f3": [_one(L, x) for x in last[2:]],
        "f1_far": _pairs(L, lambda a, b, d: d >= FAR_MIN_D and _alive_at_birth(L, a, b)),
        "cross": [_pair(L, first[-1], y, chapter=None) for y in last[1:]],
        "cain": [{"x": a, "y": b, "x_id": None, "y_id": None, "chapter": 4} for a, b in lists.cain_pairs],
        "terah": [{"x": L.name[last[-1]], "y": s, "x_id": last[-1], "y_id": None, "chapter": chs[-1]} for s in sons],
        "luke": [dict(p, book=lists.books["luke"], book_en=BOOK_EN["luke"]) for p in _pairs(L, f1)],
        "chron": [dict(p, book=lists.books["chron"], book_en=BOOK_EN["chron"]) for p in reversed(_pairs(L, f1))],
        "after12": [{"x": a, "y": b, "x_id": None, "y_id": None, "chapter": None} for a, b in lists.after12_pairs],
        "gens": _pairs(L, lambda a, b, d: d >= GENS_MIN_D),
        "longest": (lambda c: c[len(c) // 2:] + c[:len(c) // 2])(_pairs(L, f1)),
        "yes_no": _pairs(L, lambda a, b, d: d >= 2 and _alive_at_birth(L, a, b)),   # the answer is yes
    }
    for k, w in enumerate(words[:2]):
        out[f"word{k}"] = w
    return out


def list_problems(L, lists: Lists) -> list[str]:
    """Names of the fixed pairs and books that the layer, gen_names or the text layer do not know."""
    chain, cain = set(L.id_of), set(L.cain_line)
    out = [f"Cain pair {k}: a name is neither Cain's line nor the chain" for k, p in enumerate(lists.cain_pairs)
           if not set(p) <= cain | chain]
    out += [f"Cain pair {k}: no Cain-line name" for k, p in enumerate(lists.cain_pairs) if not set(p) & cain]
    out += [f"book {k} is not among gen_names other_books" for k, b in lists.books.items() if b not in L.other_books]
    if lists.later_names is not None:
        out += [f"post-Genesis-12 pair {k}: a name is not in Genesis 12-50" for k, p in enumerate(lists.after12_pairs)
                if not set(p) <= lists.later_names]
    out += [f"post-Genesis-12 pair {k}: a chain name" for k, p in enumerate(lists.after12_pairs) if set(p) & chain]
    return out + ([] if len(L.guarded) >= 2 else ["fewer than two guarded chain names (common-word family)"])


def near_key(item: Mapping[str, Any]) -> tuple:
    """What two near misses must not share: the name pair, or (family, person, word) for a one-person item."""
    return ("pair", item["x"], item["y"]) if item.get("y") else (item["family"], item["x"], item.get("word"))


def near_of(spec: Mapping[str, Any]) -> list[dict]:
    return [s for j in spec["jobs"] for s in j["slots"] if s["kind"] == "near"]


def near_items(set_name: str, L, lists: Lists, avoid_pairs: frozenset = frozenset(),
               taken: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """The 20 near misses of a set: per source, the first candidate whose key is not taken (module docstring);
    ``avoid_pairs`` holds (x_id, y_id) pairs no item may name (P1: the pool's), ``taken`` P1's items (P2)."""
    if bad := list_problems(L, lists):
        raise SpecError(f"near-miss lists: {bad}")
    cands, used, out = candidates(L, lists), {near_key(x) for x in taken}, []
    for fam, srcs in NEAR_FAMILIES:
        for src in srcs:
            free = [c for c in cands.get(src, []) if (c["x_id"], c["y_id"]) not in avoid_pairs
                    and near_key({**c, "family": fam}) not in used]
            if not free:
                raise SpecError(f"{set_name} near-miss source {src}: no free candidate of {len(cands.get(src, []))}")
            out.append({"kind": "near", "family": fam, "source": src, "sid": None, **free[0]})
            used.add(near_key(out[-1]))
    return out


# ---------------------------------------------------------------- jobs and the spec
def build_jobs(set_name: str, positives: Sequence[dict], near: Sequence[dict]) -> list[dict]:
    n = len(positives) + len(near)
    J = math.ceil(n / JOB_SIZE)
    bins: list[list[dict]] = [[] for _ in range(J)]
    for i, it in enumerate(positives):
        bins[i % J].append(dict(it))
    for it in near:
        j = min(range(J), key=lambda j: (len(bins[j]), j))
        bins[j].append(dict(it))
    for b in bins:
        sids = [it["sid"] for it in b if it["kind"] == "pos"]
        if len(b) > JOB_SIZE or len(sids) != len(set(sids)):
            raise SpecError(f"{set_name}: a job holds {len(b)} slots or one slot twice")
    rng, jobs = random.Random(f"{GC.P2_SEED}:{set_name}:slots"), []
    for j, b in enumerate(bins):
        rng.shuffle(b)
        jid = f"{set_name}-j{j:02d}"
        jobs.append({"job_id": jid, "set": set_name, "writer": WRITERS[j % len(WRITERS)],
                     "persona": PERSONAS[j % len(PERSONAS)],
                     "slots": [dict(it, slot=f"q{k}", item_id=f"{jid}-q{k}") for k, it in enumerate(b, 1)]})
    return jobs


def build_spec(set_name: str, pool: Sequence[Mapping[str, Any]], L, lists: Lists,
               dev: Sequence[Mapping[str, Any]] | None = None, inputs: Mapping[str, Any] | None = None,
               p1_near: Sequence[Mapping[str, Any]] | None = None) -> dict:
    """The spec of one set (P1 needs ``dev``, P2 P1's near misses ``p1_near``); ``inputs`` records the sha256 of
    what it was built from."""
    if set_name not in SETS:
        raise SpecError(f"set {set_name!r} is not one of {SETS}")
    if set_name == "p1" and not dev:
        raise SpecError("P1 is built from the development slots")
    if set_name == "p2" and not p1_near:
        raise SpecError("P2 is built after P1: its near misses avoid P1's (p1_near)")
    if set_name == "p1":
        pos, near = p1_positives(dev, pool), near_items("p1", L, lists, frozenset((r["x"], r["y"]) for r in pool))
    else:
        pos, near = p2_positives(pool), near_items("p2", L, lists, taken=p1_near)
    jobs = build_jobs(set_name, pos, near)
    return {"schema": SCHEMA, "set": set_name, "seed": GC.P2_SEED, "job_size": JOB_SIZE, "inputs": dict(inputs or {}),
            "counts": counts(jobs), "jobs": jobs, "order": [j["job_id"] for j in jobs]}


def counts(jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    slots = [s for j in jobs for s in j["slots"]]
    pos = [s for s in slots if s["kind"] == "pos"]
    return {"jobs": len(jobs), "slots": len(slots), "positives": len(pos), "near": len(slots) - len(pos),
            "distinct_positive_slots": len({s["sid"] for s in pos}),
            "by_stratum": {s: sum(p["stratum"] == s for p in pos) for s in STRATA},
            "by_family": {f: sum(s.get("family") == f for s in slots) for f, _ in NEAR_FAMILIES},
            "writers": dict(Counter(j["writer"] for j in jobs)), "personas": dict(Counter(j["persona"] for j in jobs)),
            "job_sizes": dict(sorted(Counter(str(len(j["slots"])) for j in jobs).items()))}


def spec_bytes(spec: Mapping[str, Any]) -> bytes:
    """The bytes g_common.write_json writes, so a spec's sha is its file's."""
    return (json.dumps(spec, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def spec_sha(spec: Mapping[str, Any]) -> str:
    return GC.sha256_text(spec_bytes(spec).decode("utf-8"))


def set_root(set_name: str, out_root: Path | str = GC.OUT_ROOT) -> Path:
    return Path(out_root) / QSET_DIR / set_name


def spec_path(set_name: str, out_root: Path | str = GC.OUT_ROOT) -> Path:
    return set_root(set_name, out_root) / SPEC_FILE


# ---------------------------------------------------------------- the store inputs
def later_genesis_names() -> frozenset[str]:
    import names_g
    spans = names_g.surfaces_by_verse(names_g.jsonl(names_g.TEXT_DIR / "name_spans.jsonl"))
    return frozenset(names_g.nfkc(s) for c, _v, s in spans if c >= 12)


def store_inputs(set_name: str, out_root: Path | str = GC.OUT_ROOT,
                 p1_spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """(pool rows, gencard Layer, Lists, dev rows, P1's near misses, input sha256) from the store, every pin
    checked; P2 reads the stored P1 spec unless ``p1_spec`` is given (a test of a P2 build before P1's is stored)."""
    import gencard
    if GC.sha256_file(GC.POOL) != GC.POOL_SHA256:
        raise SpecError(f"{GC.POOL}: sha256 is not {GC.POOL_SHA256[:12]} (prereg §2.1)")
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise SpecError(f"{GC.GEN_LAYER}: sha256 is not {GC.GEN_LAYER_SHA256_PREFIX} (prereg §2)")
    L = gencard.parse(GC.read_json(GC.GEN_LAYER), GC.read_json(GC.GEN_NAMES))
    inputs = {"pool.json": GC.POOL_SHA256, "gen_layer.json": GC.sha256_file(GC.GEN_LAYER),
              "gen_names.json": GC.sha256_file(GC.GEN_NAMES)}
    dev = p1_near = None
    if set_name == "p1":
        dev = dev_rows()
        inputs["stage0 items.json"] = GC.sha256_file(GC.stage0().x_common.ITEMS)
    else:
        p1 = load_spec("p1", out_root) if p1_spec is None else p1_spec
        p1_near, inputs["p1/spec.json"] = near_of(p1), spec_sha(p1)
    return {"pool": GC.read_json(GC.POOL)["pool"], "L": L, "lists": Lists(later_names=later_genesis_names()),
            "dev": dev, "inputs": inputs, "p1_near": p1_near}


def build_from_store(set_name: str, out_root: Path | str = GC.OUT_ROOT, p1_spec: Mapping[str, Any] | None = None) -> dict:
    return build_spec(set_name, **store_inputs(set_name, out_root, p1_spec))


def load_spec(set_name: str, out_root: Path | str = GC.OUT_ROOT) -> dict:
    p = spec_path(set_name, out_root)
    if not p.is_file():
        raise SpecError(f"{p} missing: run spec_qg.py build --set {set_name} first")
    return GC.read_json(p)


def write_spec(spec: Mapping[str, Any], out_root: Path | str = GC.OUT_ROOT) -> Path:
    p = spec_path(spec["set"], out_root)
    if p.is_file() and GC.sha256_file(p) != spec_sha(spec):
        raise SpecError(f"{p} exists with another sha256: a spec change is recorded, never silent (move it away)")
    return GC.write_json(p, spec)


def summary(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Counts and the sha256 only (the CLI's output; never a slot, sid or name)."""
    return {"set": spec["set"], "sha256": spec_sha(spec), "inputs": spec["inputs"], **spec["counts"]}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="qset P1/P2 specification (CPU)")
    ap.add_argument("cmd", choices=("build", "check"))
    ap.add_argument("--set", required=True, choices=SETS)
    a = ap.parse_args(argv)
    spec = build_from_store(a.set)
    if a.cmd == "check":
        stored = load_spec(a.set)
        same = spec_sha(stored) == spec_sha(spec)
        print(json.dumps({"same": same, "stored": spec_sha(stored), "rebuilt": spec_sha(spec)}))
        return 0 if same else 1
    path = write_spec(spec)
    print(json.dumps({**summary(spec), "file_sha256": GC.sha256_file(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpecError as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False))
        sys.exit(2)
