"""Anchored kinship rules (REL-01): kinship edges that a verse states in a slot.

Step 2's rule rows took the direction of SON_OF / FATHER_OF from id order.
Step 6.05 (relation_postprocess) replaces them with these hits: both names
inside one verse, in one of four slot patterns, each resolved through its own
pericope's MENTIONS. The slot decides the direction:

    P1_child_of     P 的兒子/女兒 C(、C)*    C SON_OF / DAUGHTER_OF P
    P2_is_child_of  C 是 P 的兒子/女兒       C SON_OF / DAUGHTER_OF P
    P3_begot        給 F 生 C(、C)*          F FATHER_OF C
    P4_wife         H 的妻 W                 sorted pair SPOUSE_OF, first item only

Names are tokenised by one longest-first alternation over the lexicon
(Person/Place/Group names: an Event/Object/Theme name such as 「兒子大衛」
would swallow the slot) and must not be glued to a hanzi before (prev_ok) or
after (trail_ok) them. A span resolves only when its pericope's MENTIONS give
it exactly one Person id, and (surface: declared) only as that entity's
canonical name or alias. A list item followed by 的 owns the next clause and
ends the list (list_stop). Patterns, character sets and these choices live in
config/relations/anchored_rules.yaml.

Same-name guard, pass 1 (K2 「同名時 abstain」): a parent hit abstains, and is
logged as a conflict, when its child already has another curated, prior or llm
parent (parent_map, built by 6.05 from those rows), or when either endpoint is a
known homonym node (guard.homonym_ids). Pass 2 (guard.disagreement) applies the
same rule within the anchored hits that pass 1 kept: a child they give two or
more parents is a merged homonym node (亞撒利雅 has 11 anchored fathers), and
every parent hit of it abstains.

Port of docs/records/2026-10-04_kg_fix/batch1/planner_1A/anchored_sim.py with
the W1 changes of batch1/w1_1A/anchored_w1.py. PyYAML and the standard library
only: 6.05 reads files and connects to no database.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

try:  # imported as scripts.relation_extraction (6.05, run with -m from the repo root)
    from ..check_identity import TYPE_LABELS
except ImportError:  # imported as relation_extraction (scripts/ on sys.path)
    from check_identity import TYPE_LABELS

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "relations" / "anchored_rules.yaml"
FORMAT_VERSION = 1
BEGOT_MODES = ("gei", "father", "off")
SURFACES = ("declared", "any")
LIST_STOPS = ("cont", "all", "off")
CONFIG_KEYS = (
    "version", "begot", "surface", "list_stop", "lexicon_types", "slot_types", "deny_ids",
    "min_name_len", "delim", "list_sep", "prev_ok", "trail_ok", "sentence_end",
    "child_re", "begot_re", "wife_re", "is_child_re", "guard",
)
GUARD_KEYS = ("other_parent", "homonym_ids", "disagreement")
HOMONYM, OTHER_PARENT = "homonym", "other_parent"   # conflict reasons, pass 1
DISAGREEMENT = "anchored_disagreement"              # conflict reason, pass 2
CONFLICT_KEYS = ("head_id", "relation", "tail_id", "source_pericope_id", "verse", "pattern")

P1, P2, P3, P4 = "P1_child_of", "P2_is_child_of", "P3_begot", "P4_wife"
PATTERNS = (P1, P2, P3, P4)
DE = "的"     # a list item followed by 的 owns the next clause
GEI = "給"    # begot: gei reads only 「給F生C」
SON = "兒子"  # child_re group 1: 兒子 -> SON_OF, otherwise DAUGHTER_OF
VERSE_MARK = re.compile(r"\*\*(\d+)\*\*\s*")

Token = tuple[int, int, str]                   # (start, end, name)
Resolve = Callable[[str, int], "str | None"]   # (span, start) -> Person id


@dataclass(frozen=True)
class GuardConfig:
    other_parent: bool             # abstain when the child already has another parent
    homonym_ids: frozenset[str]    # abstain when either endpoint is one of these
    disagreement: bool             # pass 2: abstain a child whose anchored hits name >= 2 parents


@dataclass(frozen=True)
class AnchoredConfig:
    begot: str
    surface: str
    list_stop: str
    lexicon_types: frozenset[str]
    slot_types: frozenset[str]
    deny_ids: frozenset[str]
    min_name_len: int
    list_sep: frozenset[str]
    prev_ok: frozenset[str]        # delim plus the YAML's prev_ok
    trail_ok: frozenset[str]       # delim plus the YAML's trail_ok
    sentence_end: frozenset[str]
    child_re: re.Pattern
    begot_re: re.Pattern
    wife_re: re.Pattern
    is_child_re: re.Pattern
    guard: GuardConfig


# --- config -----------------------------------------------------------------

def _choice(path: Path, doc: Mapping, key: str, allowed: tuple[str, ...]) -> str:
    if doc[key] not in allowed:
        raise ValueError(f"{path}: {key} {doc[key]!r} is not one of {list(allowed)}")
    return doc[key]


def _labels(path: Path, doc: Mapping, key: str) -> frozenset[str]:
    value = doc[key]
    if not isinstance(value, list) or not value or any(v not in TYPE_LABELS for v in value):
        raise ValueError(f"{path}: {key} {value!r} must list labels of {list(TYPE_LABELS)}")
    return frozenset(value)


def _chars(path: Path, doc: Mapping, key: str) -> frozenset[str]:
    if not isinstance(doc[key], str) or not doc[key]:
        raise ValueError(f"{path}: {key} must be a non-empty string of characters")
    return frozenset(doc[key])


def _pattern(path: Path, doc: Mapping, key: str, groups: int) -> re.Pattern:
    try:
        pattern = re.compile(doc[key])
    except (re.error, TypeError) as e:
        raise ValueError(f"{path}: {key} {doc[key]!r} does not compile: {e}") from e
    if pattern.groups != groups:
        raise ValueError(f"{path}: {key} must have {groups} capturing group(s), has {pattern.groups}")
    return pattern


def _read(path: Path) -> Mapping:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: {e}") from e
    if not isinstance(doc, Mapping):
        raise ValueError(f"{path}: expected a mapping with {list(CONFIG_KEYS)}")
    unknown = sorted(set(doc) - set(CONFIG_KEYS))
    missing = [key for key in CONFIG_KEYS if key not in doc]
    if unknown or missing:
        raise ValueError(f"{path}: unknown key(s) {unknown}, missing key(s) {missing}")
    if doc["version"] != FORMAT_VERSION:
        raise ValueError(f"{path}: expected version {FORMAT_VERSION}, got {doc['version']!r}")
    return doc


def _ids(path: Path, value, key: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError(f"{path}: {key} must list entity ids")
    return frozenset(value)


def _guard(path: Path, doc: Mapping) -> GuardConfig:
    guard = doc["guard"]
    if not isinstance(guard, Mapping) or set(guard) != set(GUARD_KEYS):
        raise ValueError(f"{path}: guard must be a mapping with exactly {list(GUARD_KEYS)}, "
                         f"got {guard!r}")
    for key in ("other_parent", "disagreement"):
        if not isinstance(guard[key], bool):
            raise ValueError(f"{path}: guard.{key} must be true or false")
    return GuardConfig(other_parent=guard["other_parent"],
                       homonym_ids=_ids(path, guard["homonym_ids"], "guard.homonym_ids"),
                       disagreement=guard["disagreement"])


def load_config(path: Path = CONFIG_PATH) -> AnchoredConfig:
    """The anchored-rule config; ValueError on an unknown, missing or malformed key."""
    doc = _read(path)
    if type(doc["min_name_len"]) is not int or doc["min_name_len"] < 1:
        raise ValueError(f"{path}: min_name_len must be a positive integer")
    delim = _chars(path, doc, "delim")
    return AnchoredConfig(
        begot=_choice(path, doc, "begot", BEGOT_MODES),
        surface=_choice(path, doc, "surface", SURFACES),
        list_stop=_choice(path, doc, "list_stop", LIST_STOPS),
        lexicon_types=_labels(path, doc, "lexicon_types"),
        slot_types=_labels(path, doc, "slot_types"),
        deny_ids=_ids(path, doc["deny_ids"], "deny_ids"),
        min_name_len=doc["min_name_len"],
        list_sep=_chars(path, doc, "list_sep"),
        prev_ok=delim | _chars(path, doc, "prev_ok"),
        trail_ok=delim | _chars(path, doc, "trail_ok"),
        sentence_end=_chars(path, doc, "sentence_end"),
        child_re=_pattern(path, doc, "child_re", 1),
        begot_re=_pattern(path, doc, "begot_re", 0),
        wife_re=_pattern(path, doc, "wife_re", 0),
        is_child_re=_pattern(path, doc, "is_child_re", 0),
        guard=_guard(path, doc),
    )


# --- lexicon, span map, verses ----------------------------------------------

def build_lexicon(entities: Mapping[str, Mapping], final_types: Mapping[str, str],
                  mention_rows: Iterable[Mapping], cfg: AnchoredConfig) -> list[str]:
    """Canonical names, aliases and NER spans of lexicon_types entities.

    Stripped, at least min_name_len characters, sorted by (-len, name).
    """
    names: set[str] = set()
    for eid, entity in entities.items():
        if final_types.get(eid) in cfg.lexicon_types:
            names.add((entity.get("canonical_name") or "").strip())
            names.update((alias or "").strip() for alias in entity.get("aliases") or ())
    for mention in mention_rows:
        if final_types.get(mention["entity_id"]) in cfg.lexicon_types:
            names.add((mention.get("text_span") or "").strip())
    return sorted((n for n in names if len(n) >= cfg.min_name_len), key=lambda n: (-len(n), n))


def compile_tokenizer(lexicon: Iterable[str]) -> re.Pattern:
    """One alternation, longest name first (ties by name), so a match is the longest name."""
    names = sorted(set(lexicon), key=lambda n: (-len(n), n))
    if not names:
        return re.compile(r"(?!)")   # matches nothing; an empty alternation would match everywhere
    return re.compile("|".join(re.escape(n) for n in names))


def pericope_of(mention: Mapping, chunk_parent: Mapping[str, str]) -> str:
    """The pericope a mention row belongs to: verse rows split at ':v:', chunks roll up."""
    source_id = mention["source_id"]
    if mention.get("source_type") == "verse" or ":v:" in source_id:
        return source_id.split(":v:")[0]
    if mention.get("source_type") == "chunk":
        return chunk_parent.get(source_id, source_id)
    return source_id


def _declared(entities: Mapping[str, Mapping]) -> dict[str, set[str]]:
    return {eid: {(e.get("canonical_name") or "").strip(),
                  *((alias or "").strip() for alias in e.get("aliases") or ())}
            for eid, e in entities.items()}


def build_span_map(entities: Mapping[str, Mapping], final_types: Mapping[str, str],
                   mention_rows: Iterable[Mapping], chunk_parent: Mapping[str, str],
                   cfg: AnchoredConfig) -> tuple[dict[str, dict[str, set[str]]], int]:
    """({pericope: {span: {slot_types ids}}}, foreign_surface_skipped).

    A mention of a slot_types entity outside deny_ids counts; under
    surface: declared, a span that is not the entity's canonical name or alias
    is skipped and counted as foreign_surface_skipped.
    """
    declared = _declared(entities) if cfg.surface == "declared" else None
    span_map: dict[str, dict[str, set[str]]] = {}
    skipped = 0
    for mention in mention_rows:
        eid, span = mention["entity_id"], (mention.get("text_span") or "").strip()
        if final_types.get(eid) not in cfg.slot_types or eid in cfg.deny_ids or not span:
            continue
        if declared is not None and span not in declared.get(eid, ()):
            skipped += 1
            continue
        span_map.setdefault(pericope_of(mention, chunk_parent), {}).setdefault(span, set()).add(eid)
    return span_map, skipped


def verses_of(content: str) -> list[tuple[int, str]]:
    """[(verse_no, text)] from the '**N** text' blocks of a pericope."""
    parts = VERSE_MARK.split(content)
    return [(int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


# --- one verse --------------------------------------------------------------

def _list_after(text: str, toks: list[Token], j: int, slot_end: int, resolve: Resolve,
                cfg: AnchoredConfig) -> list[str]:
    """Ids of the names listed from slot_end on (A、B和C...)."""
    out: list[str] = []
    cur = slot_end
    while j < len(toks) and toks[j][0] < cur:   # names the pattern swallowed (兒子, 妻子 are names too)
        j += 1
    for start, end, name in toks[j:]:
        if not (start == cur or (start == cur + 1 and text[cur] in cfg.list_sep)):
            break
        if end < len(text) and text[end] not in cfg.trail_ok:
            break   # glued to the next hanzi: a substring of a longer word
        if end < len(text) and text[end] == DE and cfg.list_stop != "off":
            if cfg.list_stop == "cont" and start == slot_end:
                eid = resolve(name, start)
                out.extend([eid] if eid else [])
            break   # 「X的…」 owns the next clause; the list ends
        eid = resolve(name, start)
        out.extend([eid] if eid else [])
        cur = end
        if cur < len(text) and text[cur] in cfg.sentence_end:
            break
    return out


def _begot_hits(text: str, toks: list[Token], i: int, head: str, resolve: Resolve,
                cfg: AnchoredConfig) -> list[tuple[str, str, str, str]] | None:
    """P3, or None when the head is not followed by a begot slot that counts."""
    start, end, _ = toks[i]
    m = cfg.begot_re.match(text, end)
    gei_ok = cfg.begot == "father" or (cfg.begot == "gei" and start > 0 and text[start - 1] == GEI)
    if not (m and cfg.begot != "off" and gei_ok):
        return None
    return [(head, "FATHER_OF", c, P3)
            for c in _list_after(text, toks, i + 1, m.end(), resolve, cfg) if c != head]


def _is_child_hits(text: str, toks: list[Token], i: int, head: str, resolve: Resolve,
                   cfg: AnchoredConfig) -> list[tuple[str, str, str, str]]:
    """P2: C 是 P 的兒子/女兒, the parent the very next name."""
    end = toks[i][1]
    m = cfg.is_child_re.match(text, end)
    if not m or i + 1 >= len(toks) or toks[i + 1][0] != m.end():   # tokens never overlap
        return []
    start2, end2, name2 = toks[i + 1]
    parent = resolve(name2, start2)
    m2 = cfg.child_re.match(text, end2)
    if not (parent and m2 and parent != head):
        return []
    return [(head, "SON_OF" if m2.group(1) == SON else "DAUGHTER_OF", parent, P2)]


def _slot_hits(text: str, toks: list[Token], i: int, head: str, resolve: Resolve,
               cfg: AnchoredConfig) -> list[tuple[str, str, str, str]]:
    """Hits of the slot right after token i; the first pattern that matches decides."""
    end = toks[i][1]
    m = cfg.child_re.match(text, end)
    if m:
        relation = "SON_OF" if m.group(1) == SON else "DAUGHTER_OF"
        return [(c, relation, head, P1)
                for c in _list_after(text, toks, i + 1, m.end(), resolve, cfg) if c != head]
    m = cfg.wife_re.match(text, end)
    if m:
        wives = _list_after(text, toks, i + 1, m.end(), resolve, cfg)[:1]
        return [(min(head, w), "SPOUSE_OF", max(head, w), P4) for w in wives if w != head]
    begot = _begot_hits(text, toks, i, head, resolve, cfg)
    if begot is not None:
        return begot
    return _is_child_hits(text, toks, i, head, resolve, cfg)


def extract_verse(text: str, tokenizer: re.Pattern, resolve: Resolve,
                  cfg: AnchoredConfig) -> list[tuple[str, str, str, str]]:
    """[(head_id, relation, tail_id, pattern)] of one verse, in text order.

    resolve(span, start) gives the span's one Person id, or None.
    """
    toks = [(m.start(), m.end(), m.group()) for m in tokenizer.finditer(text)]
    out = []
    for i, (start, _, name) in enumerate(toks):
        if start > 0 and text[start - 1] not in cfg.prev_ok:
            continue   # glued to the previous hanzi: a substring of a longer word
        head = resolve(name, start)
        if head:
            out.extend(_slot_hits(text, toks, i, head, resolve, cfg))
    return out


# --- same-name guard --------------------------------------------------------

def parent_child(head: str, relation: str, tail: str) -> tuple[str, str] | None:
    """(parent, child): FATHER_OF and MOTHER_OF read head->tail, SON_OF and DAUGHTER_OF tail->head."""
    if relation in ("FATHER_OF", "MOTHER_OF"):
        return head, tail
    if relation in ("SON_OF", "DAUGHTER_OF"):
        return tail, head
    return None


def parent_map_of(triples: Iterable[tuple[str, str, str]]) -> dict[str, set[str]]:
    """{child: {parent}} of (head, relation, tail) triples; other relations are ignored."""
    parents: dict[str, set[str]] = {}
    for head, relation, tail in triples:
        pair = parent_child(head, relation, tail)
        if pair:
            parents.setdefault(pair[1], set()).add(pair[0])
    return parents


def _conflict(hit: Mapping, reason: str, other_parents: Iterable[str]) -> dict:
    return {**{key: hit[key] for key in CONFLICT_KEYS},
            "reason": reason, "other_parents": sorted(other_parents)}


def abstain_same_name(hits: Iterable[dict], parent_map: Mapping[str, Iterable[str]],
                      guard: GuardConfig) -> tuple[list[dict], list[dict]]:
    """(kept, conflicts): pass 1 of the same-name guard, hit order kept.

    A SON_OF, DAUGHTER_OF or FATHER_OF hit with parent p and child c abstains
    when p or c is in guard.homonym_ids (reason homonym, checked first), or,
    with guard.other_parent, when parent_map[c] - {p} is not empty (reason
    other_parent; a mother counts). SPOUSE_OF hits are never guarded. A conflict
    is the hit's CONFLICT_KEYS plus reason and other_parents, the sorted
    parent_map[c] - {p}.
    """
    kept: list[dict] = []
    conflicts: list[dict] = []
    for hit in hits:
        pair = parent_child(hit["head_id"], hit["relation"], hit["tail_id"])
        if pair is None:
            kept.append(hit)
            continue
        parent, child = pair
        others = set(parent_map.get(child, ())) - {parent}
        if parent in guard.homonym_ids or child in guard.homonym_ids:
            conflicts.append(_conflict(hit, HOMONYM, others))
        elif guard.other_parent and others:
            conflicts.append(_conflict(hit, OTHER_PARENT, others))
        else:
            kept.append(hit)
    return kept, conflicts


def _conflict_order(conflict: Mapping) -> tuple:
    return (conflict["reason"], conflict["head_id"], conflict["relation"], conflict["tail_id"],
            conflict["source_pericope_id"], conflict["verse"])


def abstain_disagreements(hits: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, conflicts): pass 2 of the same-name guard, hit order kept.

    A child whose parent hits (parent_child: the patterns emit SON_OF,
    DAUGHTER_OF and FATHER_OF) name two or more different parents, a mother
    counting as one, loses every parent hit; the
    same parent in several verses is one parent. Each goes to conflicts with
    reason anchored_disagreement and other_parents, the child's other parents
    sorted. SPOUSE_OF hits are never touched. Conflicts are sorted by (reason,
    head, relation, tail, pericope, verse).
    """
    hits = list(hits)
    parents = parent_map_of((hit["head_id"], hit["relation"], hit["tail_id"]) for hit in hits)
    kept: list[dict] = []
    conflicts: list[dict] = []
    for hit in hits:
        pair = parent_child(hit["head_id"], hit["relation"], hit["tail_id"])
        if pair is None or len(parents[pair[1]]) < 2:
            kept.append(hit)
            continue
        parent, child = pair
        conflicts.append(_conflict(hit, DISAGREEMENT, parents[child] - {parent}))
    return kept, sorted(conflicts, key=_conflict_order)


def _children(conflicts: Iterable[Mapping]) -> set[str]:
    return {parent_child(c["head_id"], c["relation"], c["tail_id"])[1] for c in conflicts}


# --- corpus -----------------------------------------------------------------

def _resolver(spans: Mapping[str, set[str]], ambiguous: set, where: tuple[str, int]) -> Resolve:
    def resolve(span: str, start: int) -> str | None:
        ids = spans.get(span)
        if not ids:
            return None
        if len(ids) > 1:
            ambiguous.add((*where, start, span))
            return None
        return next(iter(ids))
    return resolve


def _extract(pericopes: Iterable[Mapping], span_map: Mapping[str, Mapping[str, set[str]]],
             tokenizer: re.Pattern, cfg: AnchoredConfig) -> tuple[list[dict], set]:
    """(hits in file order, the ambiguous (pericope, verse, start, span))."""
    hits: list[dict] = []
    ambiguous: set = set()
    for pericope in pericopes:
        pid = pericope["id"]
        spans = span_map.get(pid)
        if not spans:
            continue
        for verse, text in verses_of(pericope.get("content") or ""):
            resolve = _resolver(spans, ambiguous, (pid, verse))
            for head, relation, tail, pattern in extract_verse(text, tokenizer, resolve, cfg):
                hits.append({"head_id": head, "relation": relation, "tail_id": tail,
                             "source_pericope_id": pid, "verse": verse, "pattern": pattern,
                             "evidence_span": text[:200]})
    return hits, ambiguous


def _by_pattern(hits: Iterable[Mapping]) -> dict[str, int]:
    counts = Counter(hit["pattern"] for hit in hits)
    return {p: counts[p] for p in PATTERNS}


def run(pericopes: Iterable[Mapping], span_map: Mapping[str, Mapping[str, set[str]]],
        tokenizer: re.Pattern, cfg: AnchoredConfig,
        parent_map: Mapping[str, Iterable[str]]) -> tuple[list[dict], dict, list[dict]]:
    """(hits, stats, conflicts) over pericopes in the order given (file order).

    A hit is {head_id, relation, tail_id, source_pericope_id, verse, pattern,
    evidence_span (the verse, first 200 characters)}. parent_map is
    {child: {parent}} of the curated, prior and llm rows (parent_map_of),
    required so that a caller cannot run the guard against no parents by
    mistake; the same-name guard moves the hits it abstains to conflicts, those
    of pass 1 in hit order, then those of pass 2 (guard.disagreement, over the
    hits pass 1 kept) sorted. stats: pattern_hits and by_pattern before the
    guard, guard_other_parent and guard_homonym of pass 1,
    anchored_disagreement_children and anchored_disagreement_abstain of pass 2,
    emitted_hits and emitted_by_pattern of the hits returned, and
    ambiguous_name, the distinct (pericope, verse, start, span) whose MENTIONS
    give more than one Person id (report-only).
    """
    hits, ambiguous = _extract(pericopes, span_map, tokenizer, cfg)
    kept, conflicts = abstain_same_name(hits, parent_map, cfg.guard)
    disagreements: list[dict] = []
    if cfg.guard.disagreement:
        kept, disagreements = abstain_disagreements(kept)
    reasons = Counter(conflict["reason"] for conflict in conflicts)
    stats = {"pattern_hits": len(hits), "by_pattern": _by_pattern(hits),
             "guard_other_parent": reasons[OTHER_PARENT], "guard_homonym": reasons[HOMONYM],
             "anchored_disagreement_children": len(_children(disagreements)),
             "anchored_disagreement_abstain": len(disagreements),
             "emitted_hits": len(kept), "emitted_by_pattern": _by_pattern(kept),
             "ambiguous_name": len(ambiguous)}
    return kept, stats, conflicts + disagreements
