#!/usr/bin/env python3
"""K9 kinship review (batch 1A-T3; plan docs/records/2026-10-04_kg_batch1_plan.md
§2.1 閘門「錨定規則人工抽樣」, §5.4 and §8 K9): a fixed-seed blind sample of the
6.05 kinship edges, then the score of two blind AI labellings, their
adjudication and Kay's spot-check, with a Wilson gate on one field.

One flat CLI, so every flag is in one --help (test_docs_alignment).

--mode sample draws the sample. The pool is the --clean rows whose primary
source (the row's `source`) is --source and whose relation is in KINSHIP,
sorted by (head_id, relation, tail_id); the sample is
random.Random(--seed).sample(pool, n), with --all meaning n = the pool size.
Each item has item_id (sha1 of 'head<TAB>relation<TAB>tail', first 12 hex),
the relation, both endpoints as the KG knows them (canonical name, aliases,
the frozen description, the TOP_PERICOPES pericopes and TOP_BOOKS books with
the most mention rows) and the evidence: the verse the edge rests on. That is
the row's verse for an anchored row, the verses its evidence span covers for
an llm row, and the cited verse ('創 21:3') for a prior row; the span or the
citation itself when it cannot be placed. Nothing tells the source: no
source, sources, notes (the anchored pattern), phase, run_id, model or
confidence reaches the file. The meta holds the seed, the pool size and
sha256, the sha256 of every input, and the rubric of the two fields.

Decision Q9 (Kay 2026-10-06, M340): an llm or prior item also has a context
field, apart from the evidence: the verse right before the first evidence
verse and the one right after the last, in the book's reading order
(chapters and verses by number, across a chapter or pericope, never into
another book; null at a book's edge, across a merged block that opens a
pericope, or when the evidence cannot be placed). Their rubric is one rule:
text_correct is true when the evidence verses state the relation, in this
direction, between the two people, where a person may appear in the evidence
by name, by a pronoun or as an omitted subject whose referent the evidence
or the shown context fixes; a relation stated only in the context does not
count. anchored_rule samples and their rubric are the pre-registered gate
protocol and stay byte for byte what they were.

--mode score reads the sample, two --labels files (one annotator each,
'ai:<session>'; a row per item {item_id, text_correct, id_correct,
annotator, note}), an optional --adjudication (rows for exactly the items the
two disagree on, by a third 'ai:' session: neither A's nor B's annotator) and
an optional --spotcheck (Kay's rows for any items; an 'ai:' annotator is
refused, since the report says 「Kay 抽查」). The report has, per field, k, n
and the Wilson lower bound (z = 1.96) of the final labels before and after
the spot-check, the identity rate among the final text_correct items
(k_id_given_text, n_text and its Wilson lower bound) before and after it, the
raw agreement and Cohen's κ of the two labellings, the disagreements, the
spot-check against the final labels with every override, every input's
sha256, the gate, and the annotation ANNOTATION.

Decision Q8 (Kay 2026-10-06, M381, option a): a spot-check row replaces the
final label of its item, both fields, after the agreement and the
adjudication and before the Wilson bounds and the gate; the gate reads the
labels after the spot-check. --min-spotcheck-extra N refuses (exit 2,
nothing written, no gate) a spot-check that misses an adjudicated item or has
fewer than N other items: Kay's labels change what the gate reads, so a short
spot-check is not judged.

Adjudication is per item, not per field (staging_promotion.md K9:
「只裁決兩者不一致的項目」): the adjudication row replaces both fields of the
item, including a field A and B agreed on. Under the rubric an item they
disagree on only in id_correct has text_correct true in both, so the
override can only lower text_correct, never lift the gate.

Decision Q1 (Kay 2026-10-05): the gate field is text_correct (n = 60
anchored, lower bound ≥ 0.85); id_correct is labelled with the same rubric
and reported as the deferred-A baseline, never gating.

Exit codes: sample 0 written, 2 bad input or usage. score 0 the gate's
lower bound ≥ --min-lb (or --report-only), 1 below (the report is still
written), 2 bad input, a spot-check short of --min-spotcheck-extra, or usage
(nothing written). Both modes remove an existing --out before reading any
input, so a failed rerun leaves no earlier report at that path (a usage
error stops before --out is touched), and write it through <out>.tmp and
os.replace. An --out (or its .tmp) that is one of
the inputs is a usage error.

Usage (from the project root):
    scripts/.venv/bin/python scripts/tools/kin_review.py --mode sample \\
        --clean output/relations_clean.jsonl --source anchored_rule --n 60 --seed S --out sample.json
    scripts/.venv/bin/python scripts/tools/kin_review.py --mode score --sample sample.json \\
        --labels a.jsonl --labels b.jsonl --adjudication c.jsonl --spotcheck kay.jsonl \\
        --min-spotcheck-extra 10 --out report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from bible_chunking.config import CROSS_REF_ABBREV  # noqa: E402
from scripts.relation_extraction.anchored_rules import VERSE_MARK, verses_of  # noqa: E402

KINSHIP = ("FATHER_OF", "MOTHER_OF", "SON_OF", "DAUGHTER_OF",
           "SIBLING_OF", "SPOUSE_OF", "ANCESTOR_OF", "DESCENDANT_OF")
SOURCES = ("anchored_rule", "llm", "prior")
TOP_PERICOPES, TOP_BOOKS = 5, 6
SAMPLE_FORMAT, REPORT_FORMAT = "kin_review_sample/v1", "kin_review_report/v2"
CONTEXT_SOURCES = ("llm", "prior")              # decision Q9: these samples show the verses around the evidence
FIELDS = ("text_correct", "id_correct")
DEFAULT_GATE_FIELD, DEFAULT_MIN_LB, Z = "text_correct", 0.85, 1.96
ANNOTATION = "非人工（AI 雙盲＋裁決，Kay 抽查）"
AI_PREFIX = "ai:"
_DIRECTION = ("而且方向對（X SON_OF Y：X 是 Y 的兒子；X FATHER_OF Y：X 是 Y 的父親；ANCESTOR_OF／"
              "DESCENDANT_OF 指隔代；SPOUSE_OF、SIBLING_OF 不分方向）？")
_KINSHIP_ONLY = "要生育或婚姻意義上的關係，稱謂或比喻（例如對先知自稱「你兒子」）不算。"
_NOT_IDENTITY = "這一欄不管兩端節點實際指的是誰。"
# The anchored rule, byte for byte as pre-registered (kin_review_sample/v1 meta.rubric).
_TEXT_RULE = ("是否明說 head 與 tail 這兩個名字之間有 relation 所指的親屬關係，" + _DIRECTION + _KINSHIP_ONLY
              + "明說才記 true；沒說、只是推論、方向反了或關係種類不對都記 false。" + _NOT_IDENTITY)
RUBRIC = {
    "text_correct": "只看 evidence 的經文：經文" + _TEXT_RULE,
    "id_correct": (
        "text_correct 為 true，而且 head 與 tail 兩個節點都就是這節經文裡的那個人，才記 true："
        "看 canonical_name、aliases、description、top_pericopes、mention_books 描繪的主要人物。"
        "任一端是同名的另一人，或是合併了多個同名人物、以別人為主的節點，記 false。"
        "text_correct 為 false 時一律記 false。"),
}
# Decision Q9, one rule: a person in the evidence may be a pronoun or an omitted subject that the evidence
# itself or the ±1 context fixes; the relation must still be stated by the evidence.
RUBRIC_WITH_CONTEXT = {
    **RUBRIC,
    "text_correct": (
        "看 evidence 的經文：經文是否明說 head 與 tail 這兩個人之間有 relation 所指的親屬關係，" + _DIRECTION
        + "evidence 的經文裡，一個人可以用名字、代名詞或省略的主詞出現，只要他指的是誰能由 evidence 的經文本身，"
          "或 context 附的前一節與後一節（同一卷，可跨章；沒有可附的那一邊是 null）確定；確定不了就記 false。"
          "關係本身要由 evidence 的經文說出，只在 context 的經文裡說的不算。" + _KINSHIP_ONLY
        + "evidence 的經文明說這個關係才記 true；關係沒說或只是推論、方向反了、關係種類不對，都記 false。"
        + _NOT_IDENTITY),
}
_CHAPTER = re.compile(r"(.+):(\d+)")
_CITATION = re.compile(r"(\S+?)\s*(\d+):(\d+)")
_DEFAULTS = {"clean": "output/relations_clean.jsonl", "entities": "output/entities.jsonl",
             "mentions": "output/entity_mentions.jsonl", "pericopes": "output/pericopes.jsonl",
             "descriptions": "output/frozen/descriptions.jsonl"}
_MODE_FLAGS = {"sample": ("clean", "entities", "mentions", "pericopes", "descriptions",
                          "source", "n", "all", "seed"),
               "score": ("sample", "labels", "adjudication", "spotcheck", "min_spotcheck_extra",
                         "gate_field", "min_lb", "report_only")}


class BadInput(Exception):
    """An input the tool cannot use as given (exit 2, nothing written)."""


# --- files -----------------------------------------------------------------------

def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as e:
        raise BadInput(f"{path} is not readable: {e}") from e


def _jsonl(path: Path) -> Iterable[dict]:
    """The objects of a JSON-lines file, one per non-blank line."""
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError(f"line {number} is not an object")
                    yield row
    except (OSError, ValueError) as e:
        raise BadInput(f"{path} is not readable JSON lines: {e}") from e


def _temp(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".tmp")


def _write(path: Path, doc: dict) -> None:
    """Through <path>.tmp and os.replace: a failed write leaves no partial file at `path`."""
    tmp = _temp(path)
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# --- sample: pool and draw -------------------------------------------------------

def key_of(row: Mapping) -> tuple[str, str, str]:
    return row["head_id"], row["relation"], row["tail_id"]


def item_id(key: tuple[str, str, str]) -> str:
    return hashlib.sha1("\t".join(key).encode("utf-8")).hexdigest()[:12]


def build_pool(rows: Iterable[dict], source: str) -> list[dict]:
    """The kinship rows whose primary source is `source`, sorted by key (one row per key)."""
    try:
        pool = sorted((r for r in rows if r.get("source") == source and r["relation"] in KINSHIP), key=key_of)
    except KeyError as e:
        raise BadInput(f"a relations row has no {e}") from e
    repeated = [key_of(a) for a, b in zip(pool, pool[1:]) if key_of(a) == key_of(b)]
    if repeated:
        raise BadInput(f"the pool has a key twice (not a 6.05 output?): {repeated[0]}")
    return pool


def pool_sha256(pool: Iterable[Mapping]) -> str:
    return hashlib.sha256("".join("\t".join(key_of(r)) + "\n" for r in pool).encode("utf-8")).hexdigest()


# --- sample: context -------------------------------------------------------------

@dataclass(frozen=True)
class Corpus:
    entities: dict[str, dict]
    descriptions: dict[str, str]
    pericopes: dict[str, dict]
    verse_home: dict[tuple[str, int], str]     # (chapter id, verse) -> pericope id
    reading: dict[tuple[str, int], tuple]      # (chapter id, verse) -> (verse before, verse after) in its book
    by_pericope: dict[str, Counter]            # entity -> mention rows per pericope
    by_book: dict[str, Counter]                # entity -> mention rows per book


def mention_pericope(source_id: str) -> str:
    """A mention's pericope: verse ids split at ':v:', chunk ids ('book:ch:p:i') roll up.

    The id prefix, not anchored_rules.pericope_of's chunks.jsonl lookup: all
    173,896 rows of output/entity_mentions.jsonl (2026-10-05) land on a
    pericope of pericopes.jsonl this way, the 11,361 chunk rows included.
    """
    return ":".join(source_id.split(":v:")[0].split(":")[:3])


def _mention_counts(path: Path, ids: set[str]) -> tuple[dict, dict]:
    by_pericope, by_book = defaultdict(Counter), defaultdict(Counter)
    for row in _jsonl(path):
        if row.get("entity_id") in ids:
            by_pericope[row["entity_id"]][mention_pericope(row["source_id"])] += 1
            by_book[row["entity_id"]][row["source_id"].split(":")[0]] += 1
    return dict(by_pericope), dict(by_book)


def load_corpus(args: argparse.Namespace, ids: set[str]) -> Corpus:
    entities = {row["entity_id"]: row for row in _jsonl(args.entities)}
    lost = sorted(ids - entities.keys())
    if lost:
        raise BadInput(f"{len(lost)} endpoints are not in {args.entities}: {lost[:5]}")
    descriptions = {row["entity_id"]: row.get("description") for row in _jsonl(args.descriptions)}
    pericopes = {row["id"]: row for row in _jsonl(args.pericopes)}
    verse_home = {(p.get("parent_id"), number): pid for pid, p in pericopes.items()
                  for number, _ in verses_of(p.get("content") or "")}
    return Corpus(entities, descriptions, pericopes, verse_home, reading_order(verse_home, opening_gaps(pericopes)),
                  *_mention_counts(args.mentions, ids))


def opening_gaps(pericopes: Mapping[str, Mapping]) -> set[tuple[str, int]]:
    """(chapter id, first marked verse) of each pericope whose text opens before its first '**N**' mark.

    RCUV opens six pericopes with a merged block such as '**1-2**' (psa:135:0, zep:2:0, luk:1:0, jer:34:1,
    luk:21:5, col:2:2 in output/pericopes.jsonl, 2026-10-06), which verses_of drops: the text between that
    verse and the one before it in reading order is not a verse the sample can show.
    """
    gaps = set()
    for p in pericopes.values():
        parts = VERSE_MARK.split(p.get("content") or "")
        if len(parts) > 1 and parts[0].strip():
            gaps.add((p.get("parent_id"), int(parts[1])))
    return gaps


def reading_order(verse_home: Mapping[tuple[str, int], str],
                  gaps: Iterable[tuple[str, int]] = ()) -> dict[tuple[str, int], tuple]:
    """(chapter id, verse) -> (the verse before it, the verse after it) within its book.

    Chapters and verses go by number, across chapters and pericopes; None at
    either end of a book. A verse number the text has no '**N**' mark for is
    no gap inside a pericope: RCUV's '**29-30**' block of 創 24 (verses_of keeps
    it in verse 28's text, as the evidence does) makes 28 and 31 neighbours. A
    verse in `gaps` (opening_gaps: a merged block opens its pericope and is
    dropped) has no verse before it, and the verse before it none after it.
    """
    books, gaps = defaultdict(list), set(gaps)
    for chapter, verse in verse_home:
        number = _CHAPTER.fullmatch(chapter or "")
        if number:
            books[number.group(1)].append((int(number.group(2)), verse, chapter))
    links = {}
    for verses in books.values():
        keys = [(chapter, verse) for _, verse, chapter in sorted(verses)]
        for i, key in enumerate(keys):
            after = keys[i + 1] if i + 1 < len(keys) else None
            links[key] = (keys[i - 1] if i and key not in gaps else None, None if after in gaps else after)
    return links


def _top(counter: Counter, n: int) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def endpoint(eid: str, corpus: Corpus) -> dict:
    entity = corpus.entities[eid]
    return {"id": eid, "canonical_name": entity.get("canonical_name"),
            "aliases": entity.get("aliases") or [], "description": corpus.descriptions.get(eid),
            "top_pericopes": [{"pericope_id": pid, "title": corpus.pericopes.get(pid, {}).get("title"),
                               "mentions": n} for pid, n in _top(corpus.by_pericope.get(eid, Counter()),
                                                                 TOP_PERICOPES)],
            "mention_books": [[book, n] for book, n in _top(corpus.by_book.get(eid, Counter()), TOP_BOOKS)]}


def _span_verses(content: str, span: str) -> list[int]:
    """The verses whose '**N** …' block overlaps the first occurrence of `span`."""
    at = content.find(span) if span else -1
    if at < 0:
        return []
    marks = list(VERSE_MARK.finditer(content))
    stops = [m.start() for m in marks[1:]] + [len(content)]
    return [int(m.group(1)) for m, stop in zip(marks, stops) if m.start() < at + len(span) and stop > at]


def _locate(row: Mapping, corpus: Corpus) -> tuple[str | None, list[int]]:
    """(pericope id, verses) the edge rests on; ([]: the span or citation is shown as it is)."""
    pid, span = row.get("source_pericope_id") or "", row.get("evidence_span") or ""
    if pid:
        if pid not in corpus.pericopes:
            raise BadInput(f"{key_of(row)}: pericope {pid} is not in the pericopes file")
        if row.get("verse") is not None:
            return pid, [int(row["verse"])]
        return pid, _span_verses(corpus.pericopes[pid].get("content") or "", span)
    cited = _CITATION.fullmatch(span.strip())
    book = CROSS_REF_ABBREV.get(cited.group(1)) if cited else None
    home = corpus.verse_home.get((f"{book}:{cited.group(2)}", int(cited.group(3)))) if book else None
    return home, [int(cited.group(3))] if home else []


def evidence(row: Mapping, corpus: Corpus, located: tuple[str | None, list[int]]) -> dict:
    pid, verses = located
    pericope = corpus.pericopes.get(pid) if pid else None
    text = dict(verses_of(pericope.get("content") or "")) if pericope else {}
    if any(v not in text for v in verses):
        raise BadInput(f"{key_of(row)}: verse {verses} is not in pericope {pid}")
    return {"pericope_id": pid, "title": pericope.get("title") if pericope else None,
            "verse": verses[0] if verses else None,
            "verse_text": " ".join(text[v] for v in verses) if verses else row.get("evidence_span") or ""}


def _verse(key: tuple[str, int] | None, corpus: Corpus) -> dict | None:
    if key is None:
        return None
    pid = corpus.verse_home[key]
    pericope = corpus.pericopes[pid]
    return {"pericope_id": pid, "title": pericope.get("title"), "verse": key[1],
            "verse_text": dict(verses_of(pericope.get("content") or ""))[key[1]]}


def context(located: tuple[str | None, list[int]], corpus: Corpus) -> dict:
    """The verse before the first evidence verse and the one after the last (decision Q9)."""
    pid, verses = located
    if not verses:
        return {"before": None, "after": None}
    chapter = corpus.pericopes[pid].get("parent_id")
    before = corpus.reading.get((chapter, verses[0]), (None, None))[0]
    after = corpus.reading.get((chapter, verses[-1]), (None, None))[1]
    return {"before": _verse(before, corpus), "after": _verse(after, corpus)}


def sample_item(row: Mapping, corpus: Corpus, *, with_context: bool) -> dict:
    located = _locate(row, corpus)
    item = {"item_id": item_id(key_of(row)), "relation": row["relation"],
            "head": endpoint(row["head_id"], corpus), "tail": endpoint(row["tail_id"], corpus),
            "evidence": evidence(row, corpus, located)}
    return {**item, "context": context(located, corpus)} if with_context else item


def run_sample(args: argparse.Namespace) -> dict:
    pool = build_pool(_jsonl(args.clean), args.source)
    n = len(pool) if args.all else args.n
    if not 0 < n <= len(pool):
        raise BadInput(f"--n {n} does not fit a pool of {len(pool)} {args.source} kinship rows")
    drawn = random.Random(args.seed).sample(pool, n)
    corpus = load_corpus(args, {eid for row in pool for eid in (row["head_id"], row["tail_id"])})
    with_context = args.source in CONTEXT_SOURCES
    items = [sample_item(row, corpus, with_context=with_context) for row in drawn]
    meta = {"seed": args.seed, "pool_size": len(pool), "pool_sha256": pool_sha256(pool),
            "clean_sha256": _sha256(args.clean), "rubric": RUBRIC_WITH_CONTEXT if with_context else RUBRIC,
            "inputs_sha256": {name: _sha256(getattr(args, name))
                              for name in ("entities", "mentions", "pericopes", "descriptions")}}
    return {"format": SAMPLE_FORMAT, "meta": meta, "items": items}


# --- score: statistics -----------------------------------------------------------

def wilson_lower_bound(k: int, n: int, z: float = Z) -> float:
    p, z2 = k / n, z * z
    return (p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Cohen's κ of two binary labellings; None when chance agreement is 1 (κ undefined)."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    return None if chance == 1 else (observed - chance) / (1 - chance)


# --- score: inputs ---------------------------------------------------------------

def read_sample(path: Path) -> tuple[list[str], dict]:
    """(the item ids of a sample file in its order, its meta without the rubric)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        ids = [item["item_id"] for item in doc["items"]] if doc["format"] == SAMPLE_FORMAT else None
        meta = {k: doc["meta"][k] for k in ("seed", "pool_size", "pool_sha256", "clean_sha256")}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BadInput(f"{path} is not a kin_review sample: {e!r}") from e
    if not ids or len(set(ids)) != len(ids):
        raise BadInput(f"{path} is not a {SAMPLE_FORMAT} sample with distinct, non-empty items")
    return ids, meta


def _check_label(row: Mapping, path: Path, known: set[str]) -> None:
    where = f"{path}: {row.get('item_id')!r}"
    if row.get("item_id") not in known:
        raise BadInput(f"{where} is not an item this file may label")
    if not all(isinstance(row.get(field), bool) for field in FIELDS):
        raise BadInput(f"{where} needs true/false {' and '.join(FIELDS)}")
    if row["id_correct"] and not row["text_correct"]:
        raise BadInput(f"{where} has id_correct without text_correct (rubric)")


def read_labels(path: Path, known: Iterable[str], *, complete: bool, ai: bool) -> tuple[dict, str | None]:
    """({item_id: row}, the file's one annotator); `complete`: every known item exactly once."""
    known, labels = set(known), {}
    for row in _jsonl(path):
        _check_label(row, path, known)
        if row["item_id"] in labels:
            raise BadInput(f"{path}: {row['item_id']} is labelled twice")
        labels[row["item_id"]] = row
    annotators = {row.get("annotator") for row in labels.values()}
    if len(annotators) > 1 or not all(isinstance(a, str) and a.strip() for a in annotators):
        raise BadInput(f"{path} must have one non-empty annotator, has {sorted(map(str, annotators))}")
    annotator = annotators.pop() if annotators else None
    if ai and labels and not annotator.startswith(AI_PREFIX):
        raise BadInput(f"{path}: annotator {annotator!r} is not '{AI_PREFIX}<session>' (the report says 非人工)")
    if complete and labels.keys() != known:
        lacking = sorted(known - labels.keys())
        raise BadInput(f"{path} lacks {len(lacking)} items, e.g. {lacking[:3]}")
    return labels, annotator


def _pick(row: Mapping) -> dict:
    return {field: row[field] for field in FIELDS}


def final_labels(ids: list[str], a: dict, b: dict, adjudicated: dict | None) -> tuple[dict, list[dict]]:
    """({item_id: final label}, the disagreements); every disagreement needs an adjudication row."""
    final, disagreements = {}, []
    for iid in ids:
        fields = sorted(f for f in FIELDS if a[iid][f] != b[iid][f])
        if not fields:
            final[iid] = _pick(a[iid])
            continue
        if iid not in (adjudicated or {}):
            raise BadInput(f"{iid}: the labellings disagree on {fields} and --adjudication has no row for it")
        final[iid] = _pick(adjudicated[iid])
        disagreements.append({"item_id": iid, "fields": fields, "labels": [_pick(a[iid]), _pick(b[iid])],
                              "final": final[iid]})
    extra = sorted((adjudicated or {}).keys() - {d["item_id"] for d in disagreements})
    if extra:
        raise BadInput(f"--adjudication has rows for items the labellings agree on: {extra[:5]}")
    return final, disagreements


# --- score: report ---------------------------------------------------------------

def _input(path: Path | None, annotator: str | None = None, *, labelled: bool = True) -> dict | None:
    if path is None:
        return None
    entry = {"path": str(path), "sha256": _sha256(path)}
    return {**entry, "annotator": annotator} if labelled else entry


def _spotcheck(path: Path | None, ids: list[str]) -> tuple[dict, str | None]:
    """({item_id: Kay's label} ({} without --spotcheck), the annotator); an 'ai:' annotator is refused."""
    if path is None:
        return {}, None
    rows, annotator = read_labels(path, ids, complete=False, ai=False)
    if annotator and annotator.startswith(AI_PREFIX):
        raise BadInput(f"{path}: annotator {annotator!r} is an AI session; the spot-check is Kay's "
                       "(the report says Kay 抽查)")
    return {iid: _pick(row) for iid, row in rows.items()}, annotator


def spotcheck_report(ids: list[str], final: dict, kay: dict, disagreements: list[dict], annotator: str | None,
                     min_extra: int | None) -> dict:
    """Kay's labels against the final ones: every override (item, field) and the coverage of the adjudication."""
    overrides = [{"item_id": iid, "field": field, "final": final[iid][field], "kay": kay[iid][field]}
                 for iid in ids if iid in kay for field in FIELDS if kay[iid][field] != final[iid][field]]
    disagree = sorted({o["item_id"] for o in overrides})
    adjudicated = [d["item_id"] for d in disagreements]
    return {"n": len(kay), "agree": len(kay) - len(disagree), "disagree": disagree, "annotator": annotator,
            "overrides": overrides, "extra": len(kay.keys() - set(adjudicated)),
            "adjudicated_missing": [iid for iid in adjudicated if iid not in kay], "min_extra": min_extra}


def check_coverage(spotcheck: dict, path: Path | None) -> None:
    """--min-spotcheck-extra N: every adjudicated item and N others, or exit 2 before any gate."""
    if spotcheck["min_extra"] is None:
        return
    if spotcheck["adjudicated_missing"]:
        raise BadInput(f"{path}: the spot-check does not cover the adjudicated items "
                       f"{spotcheck['adjudicated_missing'][:5]}")
    if spotcheck["extra"] < spotcheck["min_extra"]:
        raise BadInput(f"{path}: the spot-check has {spotcheck['extra']} items beyond the adjudicated ones, "
                       f"--min-spotcheck-extra wants {spotcheck['min_extra']}")


def field_stats(ids: list[str], labels: dict) -> dict:
    """Per field: {k, n, p, wilson_lb} of `labels`."""
    stats = {}
    for field in FIELDS:
        k, n = sum(labels[i][field] for i in ids), len(ids)
        stats[field] = {"k": k, "n": n, "p": k / n, "wilson_lb": wilson_lower_bound(k, n)}
    return stats


def identity_given_text(ids: list[str], labels: dict) -> dict:
    """Decision Q9: id_correct among the text_correct items (p and the bound are None when there are none)."""
    texts = [i for i in ids if labels[i]["text_correct"]]
    k, n = sum(labels[i]["id_correct"] for i in texts), len(texts)
    return {"k_id_given_text": k, "n_text": n, "p": k / n if n else None,
            "wilson_lb": wilson_lower_bound(k, n) if n else None}


def agreement_stats(ids: list[str], a: dict, b: dict) -> dict:
    """Per field: {raw, kappa} of labellings A and B."""
    agreement = {}
    for field in FIELDS:
        pair = [[labels[i][field] for i in ids] for labels in (a, b)]
        agreement[field] = {"raw": sum(x == y for x, y in zip(*pair)) / len(ids), "kappa": cohen_kappa(*pair)}
    return agreement


def _gate(args: argparse.Namespace, fields: dict) -> dict:
    bound = fields[args.gate_field]["wilson_lb"]
    min_lb = None if args.report_only else args.min_lb
    return {"field": args.gate_field, "min_lb": min_lb, "report_only": args.report_only,
            "wilson_lb": bound, "pass": None if args.report_only else bound >= min_lb}


def _labellings(args: argparse.Namespace, ids: list[str]) -> tuple[dict, dict, dict | None, list]:
    """(A, B, the adjudication or None, [A's, B's, the adjudication's annotator])."""
    (a, who_a), (b, who_b) = (read_labels(p, ids, complete=True, ai=True) for p in args.labels)
    if who_a == who_b:
        raise BadInput(f"both --labels files are by {who_a}; the labelling must be double-blind")
    adjudicated = who_c = None
    if args.adjudication is not None:
        adjudicated, who_c = read_labels(args.adjudication, ids, complete=False, ai=True)
        if who_c in (who_a, who_b):
            raise BadInput(f"--adjudication is by {who_c}, who labelled A or B; the adjudication must be "
                           "a third session")
    return a, b, adjudicated, [who_a, who_b, who_c]


def run_score(args: argparse.Namespace) -> dict:
    ids, sample_meta = read_sample(args.sample)
    a, b, adjudicated, (who_a, who_b, who_c) = _labellings(args, ids)
    final, disagreements = final_labels(ids, a, b, adjudicated)
    kay, who_k = _spotcheck(args.spotcheck, ids)
    spotcheck = spotcheck_report(ids, final, kay, disagreements, who_k, args.min_spotcheck_extra)
    check_coverage(spotcheck, args.spotcheck)
    checked = {iid: kay.get(iid, final[iid]) for iid in ids}          # decision Q8: Kay's label replaces
    fields = field_stats(ids, checked)
    gate = _gate(args, fields)
    return {"format": REPORT_FORMAT, "annotation": ANNOTATION, "n": len(ids), "wilson_z": Z,
            "sample": sample_meta, "fields": fields, "fields_before_spotcheck": field_stats(ids, final),
            "identity_given_text": identity_given_text(ids, checked),
            "identity_given_text_before_spotcheck": identity_given_text(ids, final),
            "agreement": agreement_stats(ids, a, b), "disagreements": disagreements,
            "spotcheck": spotcheck, "gate": gate, "exit": 1 if gate["pass"] is False else 0,
            "inputs": {"sample": _input(args.sample, labelled=False),
                       "labels": [_input(p, who) for p, who in zip(args.labels, (who_a, who_b))],
                       "adjudication": _input(args.adjudication, who_c),
                       "spotcheck": _input(args.spotcheck, who_k)}}


def _bound(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_score(doc: dict) -> str:
    lines = [f"kin_review score: n {doc['n']}, {doc['annotation']}"]
    for field in FIELDS:
        f, was, agree = doc["fields"][field], doc["fields_before_spotcheck"][field], doc["agreement"][field]
        lines.append(f"  {field:<13} {f['k']}/{f['n']}  Wilson lower bound {f['wilson_lb']:.3f}"
                     f"  (before spot-check {was['k']}/{was['n']}, {was['wilson_lb']:.3f})"
                     f"  agreement {agree['raw']:.3f}  κ {_bound(agree['kappa'])}")
    i, was = doc["identity_given_text"], doc["identity_given_text_before_spotcheck"]
    lines.append(f"  identity given text {i['k_id_given_text']}/{i['n_text']}  Wilson lower bound "
                 f"{_bound(i['wilson_lb'])}  (before spot-check {was['k_id_given_text']}/{was['n_text']}, "
                 f"{_bound(was['wilson_lb'])})")
    spot, gate = doc["spotcheck"], doc["gate"]
    lines.append(f"  disagreements {len(doc['disagreements'])}  spot-check {spot['agree']}/{spot['n']} agree, "
                 f"overrides {len(spot['overrides'])}")
    if gate["report_only"]:
        lines.append(f"exit 0: report only ({gate['field']} lower bound {gate['wilson_lb']:.3f})")
    else:
        verdict = "≥" if gate["pass"] else "<"
        lines.append(f"exit {doc['exit']}: {gate['field']} lower bound {gate['wilson_lb']:.3f} "
                     f"{verdict} {gate['min_lb']}")
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("sample", "score"), required=True)
    parser.add_argument("--out", type=Path, required=True, help="the sample or report file to write")
    for name, default in _DEFAULTS.items():
        parser.add_argument(f"--{name}", type=Path, help=f"sample: default {default}")
    parser.add_argument("--source", choices=SOURCES, help="sample: the pool's primary source")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--n", type=int, help="sample: draw N rows of the pool")
    size.add_argument("--all", action="store_true", default=None, help="sample: the whole pool, shuffled")
    parser.add_argument("--seed", type=int, help="sample: the random.Random seed (pre-registered)")
    parser.add_argument("--sample", type=Path, help="score: the sample file the labels are for")
    parser.add_argument("--labels", type=Path, action="append", help="score: an AI labelling; give it twice")
    parser.add_argument("--adjudication", type=Path,
                        help="score: final labels for the items A and B disagree on")
    parser.add_argument("--spotcheck", type=Path,
                        help="score: Kay's spot-check labels; each row replaces its item's final label, both "
                             "fields, before the Wilson bounds and the gate (decision Q8)")
    parser.add_argument("--min-spotcheck-extra", type=int, metavar="N",
                        help="score: exit 2 (no gate) unless --spotcheck covers every adjudicated item and at "
                             "least N others")
    parser.add_argument("--gate-field", choices=FIELDS,
                        help=f"score: the field the gate reads (default {DEFAULT_GATE_FIELD}, decision Q1)")
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument("--min-lb", type=float,
                      help=f"score: the gate's Wilson lower bound (default {DEFAULT_MIN_LB})")
    gate.add_argument("--report-only", action="store_true", default=None, help="score: report, never fail")
    return parser


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse, refuse the other mode's flags, check this mode's, then fill the defaults."""
    parser = build_parser()
    args = parser.parse_args(argv)
    other = next(m for m in _MODE_FLAGS if m != args.mode)
    stray = [f"--{name.replace('_', '-')}" for name in _MODE_FLAGS[other] if getattr(args, name) is not None]
    if stray:
        parser.error(f"--mode {args.mode} does not take {', '.join(stray)}")
    if args.mode == "sample":
        if args.source is None or args.seed is None or (args.n is None and not args.all):
            parser.error("--mode sample needs --source, --seed and --n or --all")
        for name, default in _DEFAULTS.items():
            setattr(args, name, getattr(args, name) or _PROJECT_ROOT / default)
        args.all = bool(args.all)
    else:
        if args.sample is None or len(args.labels or ()) != 2:
            parser.error("--mode score needs --sample and --labels twice")
        if args.min_lb is not None and not 0 < args.min_lb <= 1:
            parser.error("--min-lb must be in (0, 1]")
        if args.min_spotcheck_extra is not None and args.min_spotcheck_extra < 0:
            parser.error("--min-spotcheck-extra must be >= 0")
        if args.min_spotcheck_extra is not None and args.spotcheck is None:
            parser.error("--min-spotcheck-extra needs --spotcheck")
        args.gate_field = args.gate_field or DEFAULT_GATE_FIELD
        args.min_lb = DEFAULT_MIN_LB if args.min_lb is None else args.min_lb
        args.report_only = bool(args.report_only)
    clash = _out_clash(args)
    if clash:
        parser.error(f"--out {args.out}: it or its .tmp is an input ({clash}); main removes and replaces --out")
    return args


def _out_clash(args: argparse.Namespace) -> Path | None:
    """The first input path that --out or its temp file resolves to, if any."""
    written = {Path(args.out).resolve(), _temp(args.out).resolve()}
    for name in _MODE_FLAGS[args.mode]:
        value = getattr(args, name)
        for path in value if isinstance(value, list) else [value]:
            if isinstance(path, Path) and path.resolve() in written:
                return path
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        Path(args.out).unlink(missing_ok=True)  # a failed run must not leave an earlier report behind
        doc = run_sample(args) if args.mode == "sample" else run_score(args)
        _write(args.out, doc)
    except Exception as e:  # noqa: BLE001  (a traceback would exit 1, which in score means "below")
        print(f"BAD INPUT: {e if isinstance(e, BadInput) else f'{type(e).__name__}: {e}'}", file=sys.stderr)
        return 2
    if args.mode == "score":
        print(render_score(doc))
        return doc["exit"]
    meta = doc["meta"]
    print(f"kin_review sample: {args.source} kinship pool {meta['pool_size']:,} "
          f"(sha {meta['pool_sha256'][:12]}), {len(doc['items'])} items, seed {meta['seed']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
