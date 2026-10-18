"""Reference-layer view of the confirmation set (confirm_A.md §1, §2.9): king names → reference ids,
support facts as probe_C5 supply.py defines them, segment check (seg_cross), the one-verse
genealogy shortcut, and the extra_king lexicon. CPU only; the reference layer never judges gold.

Chains: 以色列 I01–I19, 猶大 J01–J20 (J00 所羅門 is off the chain). Names are a king's name plus its
reference aliases. Support facts: S1a/S1b/S1c = the adjacent pairs E(a,b) of the chain; S4 = A(seed),
R(every walked king except the seed) and E(a,b). A genealogy shortcut is one 1ch / mat verse that
states every father→son link of an all-son path as 「A的兒子是B」 or 「A生B」 (aliases included).
A same-kingdom namesake (homonym) must carry its father tag 「name（F的兒子）」; that tag is the only
father mention extra_king allows, and a tag naming another king of the chain leaks a step (tag_leak).
"""
from __future__ import annotations

import functools
import re
import unicodedata

from c_common import CHAIN_EXCLUDE, KD, LAYER_REF, QUESTIONS_PASSED, SEGMENTS, SUPPORT_JSON, cc, read_json, verse_units

GEN_BOOKS = ("1ch", "mat")
GEN_PASSAGES = (tuple(f"1ch.3.{i}" for i in range(10, 17)), tuple(f"mat.1.{i}" for i in range(2, 17)))
KING_PREFIX = re.compile(r"^(?:猶大|以色列)(?:國)?(?:的)?王")
PAREN_FATHER = re.compile(r"^(?P<n>[^（(]+?)[（(](?P<f>[^）)]+?)(?:的兒子|之子)[）)]$")
PREFIX_FATHER = re.compile(r"^(?P<f>.+?)(?:的兒子|之子)(?P<n>[^的]+)$")


@functools.cache
def ref() -> dict:
    """id -> raw reference-layer row (ref_layer.json is in succession order)."""
    return {k["id"]: k for k in read_json(LAYER_REF)}


@functools.cache
def chains() -> dict:
    return {kd: tuple(x for x, k in ref().items() if k["kingdom"] == kd and x not in CHAIN_EXCLUDE) for kd in "IJ"}


def kingdom(x: str) -> str:
    return ref()[x]["kingdom"]


def chain_index(x: str) -> int | None:
    ch = chains()[kingdom(x)]
    return ch.index(x) if x in ch else None


def in_chain_order(ids) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(ids), key=lambda x: (kingdom(x), chain_index(x) if chain_index(x) is not None else -1)))


def names(x: str) -> list[str]:
    k = ref()[x]
    return list(dict.fromkeys([k["name"]] + [a[0] for a in k["aliases"]]))


def father(x: str) -> str | None:
    f = ref()[x]["father"]
    return f[0] if f else None


def homonym(x: str) -> bool:
    """Another king of the same kingdom bears this king's main name (main name or alias)."""
    nm = ref()[x]["name"]
    return any(y != x and kingdom(y) == kingdom(x) and nm in names(y) for y in ref())


def required_tag(x: str) -> str | None:
    """Father name of the 「name（F的兒子）」 tag a seed must carry (homonyms only), else None."""
    return father(x) if homonym(x) and father(x) else None


def tag_leak(seed: str | None, path) -> bool:
    """The seed's required father tag names another king of the chain (a step or the answer)."""
    f = required_tag(seed) if seed else None
    return bool(f) and any(y != seed and f in names(y) for y in path if y)


def is_father(a: str | None, b: str | None) -> bool:
    """Either king is the other's father (reference father name among the other's names)."""
    return bool(a and b) and (father(a) in names(b) or father(b) in names(a))


def etype(a: str, b: str) -> str | None:
    p = ref()[b]["pred"]
    return p[1] if p and p[0] == a else None


def age(x: str):
    return ref()[x]["age"][0] if ref()[x]["age"] else None


def reign(x: str):
    return ref()[x]["reign"][1] if ref()[x]["reign"] else None


@functools.cache
def alt_age() -> frozenset:
    return frozenset(x for x, k in ref().items() if any(a[0] == "age" for a in k["alt"]))


def born_under(x: str, variant: str = "cum"):
    """(king, margin years, steps back) walking back on the segment chain; None if undecidable."""
    ch = chains()[kingdom(x)]
    if age(x) is None or x not in ch:
        return None
    i, rem = ch.index(x), float(age(x))
    for j in range(i - 1, -1, -1):
        r = reign(ch[j])
        if r is None:
            return None
        if variant == "nonacc" and r >= 1:
            r -= 1
        if rem < r:
            return ch[j], min(rem, r - rem), i - j
        rem -= r
    return None


# ---------------------------------------------------------------- genealogy shortcut
@functools.cache
def gen_verses() -> dict:
    return {k: r["text"] for k, r in verse_units().items() if k.split(".")[0] in GEN_BOOKS}


def link(a: str, b: str, text: str) -> bool:
    return any(f"{p}的兒子是{q}" in text or f"{p}生{q}" in text for p in names(a) for q in names(b))


def all_son(path) -> bool:
    return all(etype(path[i], path[i + 1]) == "son" for i in range(len(path) - 1))


@functools.cache
def _shortcut(path: tuple) -> tuple:
    if len(path) < 2 or not all_son(path):
        return ()
    return tuple(k for k, t in gen_verses().items() if all(link(path[i], path[i + 1], t) for i in range(len(path) - 1)))


def genealogy_shortcut(path) -> tuple[str, ...]:
    """1ch / mat verse keys that alone state every link of an all-son path (empty = no shortcut)."""
    return _shortcut(in_chain_order(path))


def genealogy_passage(path) -> bool:
    """Every link stated somewhere in one genealogy passage (1ch 3:10–16 or mat 1:2–16); hidden flag."""
    path = in_chain_order(path)
    if len(path) < 2 or not all_son(path):
        return False
    for keys in GEN_PASSAGES:
        txt = "".join(gen_verses().get(k, "") for k in keys)
        if all(link(path[i], path[i + 1], txt) for i in range(len(path) - 1)):
            return True
    return False


# ---------------------------------------------------------------- names → reference ids
def parse_name(s: str) -> tuple[str, str | None]:
    """'耶羅波安（約阿施的兒子）' / '約阿施的兒子耶羅波安' / '以色列王耶羅波安' -> (name, father|None)."""
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).replace("(", "（").replace(")", "）")
    s = KING_PREFIX.sub("", s)
    m = PAREN_FATHER.match(s)
    if m:
        return KING_PREFIX.sub("", m.group("n")), m.group("f")
    m = PREFIX_FATHER.match(s)
    if m:
        return m.group("n"), KING_PREFIX.sub("", m.group("f"))
    return s, None


def resolve_king(name: str, father_name: str | None = None, kd: str | None = None) -> str | None:
    """A name (or 「name（F的兒子）」) to one reference id; None when unknown or ambiguous.
    Same-kingdom bearers are split by the father; else a unique main name beats an alias."""
    nm, f = parse_name(name)
    f = f or (parse_name(father_name)[0] if father_name else None)
    kd = KD.get(kd) if kd else None
    cands = [x for x, k in ref().items() if (kd is None or k["kingdom"] == kd) and nm in names(x)]
    if f:
        cands = [x for x in cands if father(x) == f]
    if len(cands) > 1:
        mains = [x for x in cands if ref()[x]["name"] == nm]
        if len(mains) == 1:
            cands = mains
    return cands[0] if len(cands) == 1 else None


def resolve_question(q: dict) -> dict:
    """Seeds, chain and answer of a §2.8 question as reference ids (None = name_unresolved)."""
    kd = KD.get(q.get("kingdom"))
    seeds = [resolve_king(s["name"], s.get("father"), kd) for s in q.get("seeds", [])]
    chain = [resolve_king(c["king"], c.get("father"), kd) for c in q.get("chain", [])]
    ans_rows = [c for c in q.get("chain", []) if c.get("role") == "answer"]
    if ans_rows:
        answer = resolve_king(ans_rows[-1]["king"], ans_rows[-1].get("father"), kd)
    elif (q.get("answer") or {}).get("kind") == "name":
        answer = resolve_king(q["answer"]["text"], None, kd)
    else:
        answer = None
    unresolved = [s["name"] for s, x in zip(q.get("seeds", []), seeds) if x is None] + \
                 [c["king"] for c, x in zip(q.get("chain", []), chain) if x is None]
    if (q.get("answer") or {}).get("kind") == "name" and answer is None:
        unresolved.append(q["answer"].get("text", ""))
    return {"seeds": seeds, "chain": chain, "answer": answer, "unresolved": list(dict.fromkeys(unresolved))}


# ---------------------------------------------------------------- support facts and segments
def support_facts(qtype: str, ids) -> list[list[str]]:
    """supply.py facts of one chain: E for every adjacent pair; S4 adds A(seed) and R(walked, not seed)."""
    path = in_chain_order(ids)
    facts = [["E", path[i], path[i + 1]] for i in range(len(path) - 1)]
    if qtype == "S4" and path:
        facts = [["A", path[-1]]] + [["R", z] for z in path[:-1]] + facts
    return facts


def ref_disagree(ids) -> bool:
    """Hidden flag: the written chain is not a run of consecutive reference kings in one direction."""
    if any(x is None for x in ids) or len(set(ids)) != len(ids):
        return True
    if len({kingdom(x) for x in ids}) > 1 or any(chain_index(x) is None for x in ids):
        return True
    idx = [chain_index(x) for x in ids]
    steps = {b - a for a, b in zip(idx, idx[1:])}
    return not (steps <= {1} or steps <= {-1})


def seg_check(seg: dict, ids) -> list[str]:
    """['seg_cross'] when a chain king is unresolved or outside the segment's kings (gap edges
    included: 亞她利雅 is in no segment); [] otherwise."""
    return [] if ids and all(x in seg["kings"] for x in ids) else ["seg_cross"]


def boundary_kings(seg: dict, segments: list[dict]) -> list[str]:
    others = {x for s in segments if s["id"] != seg["id"] for x in s["kings"]}
    return [x for x in seg["kings"] if x in others]


@functools.cache
def verse_ord() -> dict:
    return {k: r["ord"] for k, r in verse_units().items()}


def in_range(seg: dict, key: str) -> bool:
    """A Kings verse key inside the segment's range (inclusive, canonical order)."""
    o, (a, b) = verse_ord(), seg["range"]
    return key in o and key.split(".")[0] in ("1ki", "2ki") and o[a] <= o[key] <= o[b]


# ---------------------------------------------------------------- extra_king
@functools.cache
def king_lexicon() -> frozenset:
    """Every reference name and alias of both kingdoms (所羅門 included)."""
    return frozenset(nm for x in ref() for nm in names(x))


def lexicon_spans(text: str) -> list[str]:
    """Greedy longest-match names in text (亞撒 is not found inside 亞撒利雅)."""
    by_len, out, i = sorted(king_lexicon(), key=len, reverse=True), [], 0
    while i < len(text):
        hit = next((n for n in by_len if text.startswith(n, i)), None)
        if hit:
            out.append(hit)
            i += len(hit)
        else:
            i += 1
    return out


def extra_kings(question: str, seed_ids) -> list[str]:
    """King names in the question other than the seeds' names and their required homonym father tags."""
    allowed = {nm for x in seed_ids if x for nm in names(x)} | {required_tag(x) for x in seed_ids if x and required_tag(x)}
    return sorted({n for n in lexicon_spans(question or "") if n not in allowed})


def answer_is_father(qtype: str, seeds, answer: str | None) -> bool:
    """Hidden flag: the answer is the seed's father or son (S1b: the two named ends are father and son)."""
    if qtype == "S1b":
        return len(seeds) == 2 and is_father(seeds[0], seeds[1])
    return len(seeds) >= 1 and is_father(seeds[0], answer)


def support_record(q: dict, segments: list[dict]) -> dict:
    """Everything §1.4 stores for one question: ids, facts, segment check and the hidden flags."""
    r = resolve_question(q)
    seg = next((s for s in segments if s["id"] == q.get("segment")), None)
    ids = [x for x in r["chain"] if x]
    path = in_chain_order(ids) if ids else ()
    errors = (["name_unresolved"] if r["unresolved"] else []) + \
             (seg_check(seg, r["chain"]) if seg else ["seg_cross"])
    return {"id": q.get("id"), "segment": q.get("segment"), "qtype": q.get("qtype"), **r, "path": list(path),
            "support": support_facts(q.get("qtype", ""), path) if path else [],
            "errors": errors,
            "genealogy_shortcut": list(genealogy_shortcut(path)) if q.get("qtype") in ("S1a", "S1b") and path else [],
            "boundary_kings": [x for x in path if seg and x in boundary_kings(seg, segments)],
            "hidden": {"ref_disagree": ref_disagree(r["chain"]), "gen_passage": genealogy_passage(path) if path else False,
                       "answer_is_father": answer_is_father(q.get("qtype", ""), r["seeds"], r["answer"])}}


def main(argv=None) -> None:
    """Store the support records of a question file (default: the audited questions so far)."""
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="支撐事實與歸段（§1.4）→ support.json")
    ap.add_argument("--questions", type=Path, default=QUESTIONS_PASSED)
    args = ap.parse_args(argv)
    doc = read_json(args.questions)
    qs = doc["questions"] if isinstance(doc, dict) else doc
    segs = read_json(SEGMENTS)["segments"]
    recs = [support_record(q, segs) for q in qs]
    cc.write_json(SUPPORT_JSON, {"n": len(recs), "n_errors": sum(bool(r["errors"]) for r in recs), "records": recs})
    print(SUPPORT_JSON, len(recs), "with errors", sum(bool(r["errors"]) for r in recs))


if __name__ == "__main__":
    main()
