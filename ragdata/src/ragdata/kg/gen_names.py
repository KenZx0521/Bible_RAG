"""``gen_names.json``: the names the GEN card's trigger reads (plan 2026-10-21 §2.1).

A port of the GEN confirmation set's ``names_g.build``
(``evaluation/experiments/2026-10-20_gen_confirm/names_g.py``). Inputs: the ``gen_layer.json``
bytes just built, the text layer's ``name_spans.jsonl``, ``books.jsonl`` and
``layer_manifest.json``, and the route layer's ``routing_lexicon.json``. Schema
``gen_confirm.gen_names.v1``, exactly these keys:

- ``chain``: the chain persons of gen_layer.json, chapter 5 then 11, in chain order (id, name, chapter);
- ``cain_line``: the name_spans of Genesis 4 off the chain, with every name prereg §5.2 rule 4 lists;
- ``abram_family``: the name_spans of gen.11.26–gen.11.32 off the chain, with the rule-4 list;
- ``extra_persons``: every name_spans surface of Genesis 4, 5, 10 and 11, the Cain line and the
  Abram family, off the chain;
- ``other_books`` (rule 2): the names of Luke, 1 Chronicles, Matthew, Hebrews and Jude and their
  abbreviations of two or more characters (books.jsonl), with rule 2's short forms;
- ``lexicon_blockers`` (rule 3): the lexicon's names (kind ``name``; a dotted one also dotless)
  that hold a chain name and are none, with ``BLOCKER_EXTRA``;
- ``text_digest``, ``gen_layer_sha256`` and ``sources``.

``sources`` keys are the store paths of the inputs the set was audited with when it was frozen
(``SOURCES``, in names_g's order): provenance labels, never read. Their values are the sha256 of
the bytes this build read, so G-GEN's pin of the file's sha256 proves those bytes are the
audited ones. Every surface is NFKC; the file holds names only, never scripture text.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from ragdata.contract.registry import ROUTING_LEXICON
from ragdata.kg.gen_layer import CHAPTERS
from ragdata.stages.errors import StageError
from ragdata.store import MANIFEST, LayerData

SCHEMA = "gen_confirm.gen_names.v1"
CAIN_CHAPTER = 4
ABRAM_CHAPTER, ABRAM_VERSES = 11, range(26, 33)          # gen.11.26–gen.11.32
EXTRA_CHAPTERS = (4, 5, 10, 11)
# prereg §5.2 rule 4 and rule 2, as listed there
CAIN_REQUIRED = ("該隱", "以拿", "米戶雅利", "瑪土撒利", "亞大", "洗拉", "雅八", "猶八", "土八該隱", "拿瑪", "挪得")
ABRAM_REQUIRED = ("亞伯蘭", "亞伯拉罕", "哈蘭", "撒萊", "密迦", "羅得")
OTHER_BOOK_IDS = ("luk", "1ch", "mat", "heb", "jud")
BOOK_WORDS = ("路加", "歷代志", "馬太")                   # rule 2's short forms books.jsonl does not list
BLOCKER_EXTRA = ("以諾城",)
DOT = "‧"
_KEY = re.compile(r"gen\.(\d+)\.(\d+)")

# the frozen ``sources`` keys (store paths of the audited inputs, names_g's file order)
SOURCE_GEN_LAYER = "reports/arith_stage0_20261020/gen_layer.json"
SOURCE_NAME_SPANS = "layers/text/text@247eafe44b02/name_spans.jsonl"
SOURCE_BOOKS = "layers/text/text@247eafe44b02/books.jsonl"
SOURCE_MANIFEST = "layers/text/text@247eafe44b02/layer_manifest.json"
SOURCE_LEXICON = "contracts/b20261019_a86f2b06/routing_lexicon.json"
SOURCES = (SOURCE_GEN_LAYER, SOURCE_NAME_SPANS, SOURCE_BOOKS, SOURCE_MANIFEST, SOURCE_LEXICON)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _forms(surfaces: Iterable[str]) -> set[str]:
    """NFKC surfaces, a dotted one also without its dots."""
    out = {nfkc(s) for s in surfaces}
    return out | {s.replace(DOT, "") for s in out if DOT in s}


def _verse(container: str) -> tuple[int, int] | None:
    m = _KEY.match(container)
    return (int(m.group(1)), int(m.group(2))) if m else None


def surfaces_by_verse(spans: Sequence[Mapping[str, Any]]) -> list[tuple[int, int, str]]:
    """(chapter, verse, surface) of every Genesis name span (a range key counts from its first verse)."""
    return [(v[0], v[1], r["surface"]) for r in spans if (v := _verse(r["container_id"]))]


def chain_of(gen: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = sorted((n for n in gen["nodes"] if n["chapter"] in CHAPTERS), key=lambda n: (n["chapter"], n["order"]))
    return [{"id": n["id"], "name": nfkc(n["name"]), "chapter": n["chapter"]} for n in nodes]


def other_books(books: Sequence[Mapping[str, Any]]) -> list[str]:
    out = set(BOOK_WORDS)
    for b in books:
        if b["book_id"] in OTHER_BOOK_IDS:
            out |= {b["name"]} | {s for s in b.get("short_names", []) if len(s) >= 2}
    return sorted(nfkc(s) for s in out)


def lexicon_blockers(lexicon: Mapping[str, Any], chain: set[str]) -> list[str]:
    surfaces = _forms(t["surface"] for t in lexicon["names"] if t["kind"] == "name")
    return sorted({s for s in surfaces if s not in chain and any(n in s for n in chain)} | set(BLOCKER_EXTRA))


def build(gen_layer: bytes, text: LayerData, route: LayerData) -> dict[str, Any]:
    """The names document of ``gen_layer`` (its bytes), built on ``text`` and ``route``'s lexicon."""
    manifest = (text.path / MANIFEST).read_bytes()
    lexicon = (route.path / ROUTING_LEXICON).read_bytes()
    if _sha(lexicon) != route.file_shas.get(ROUTING_LEXICON):
        raise StageError(f"{route.path / ROUTING_LEXICON}: sha256 differs from its manifest")
    gen = json.loads(gen_layer)
    digest = json.loads(manifest)["digest"]
    if digest != gen["text_digest"]:
        raise StageError(f"text layer {digest[:12]} is not the one gen_layer.json was read from")
    spans = surfaces_by_verse(text.rows["name_spans.jsonl"])
    chain = chain_of(gen)
    names = {c["name"] for c in chain}
    try:
        blockers = lexicon_blockers(json.loads(lexicon), names)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:   # e.g. R1's v1 lexicon has no names
        raise StageError(f"{route.path / ROUTING_LEXICON}: not a v2 routing lexicon ({exc!r})") from None
    cain = (_forms(s for c, _v, s in spans if c == CAIN_CHAPTER) | _forms(CAIN_REQUIRED)) - names
    abram = (_forms(s for c, v, s in spans if c == ABRAM_CHAPTER and v in ABRAM_VERSES)
             | _forms(ABRAM_REQUIRED)) - names
    extra = (_forms(s for c, _v, s in spans if c in EXTRA_CHAPTERS) | cain | abram) - names
    read = (_sha(gen_layer), text.file_shas["name_spans.jsonl"], text.file_shas["books.jsonl"], _sha(manifest),
            _sha(lexicon))
    return {"schema": SCHEMA, "text_digest": digest, "gen_layer_sha256": _sha(gen_layer), "chain": chain,
            "cain_line": sorted(cain), "abram_family": sorted(abram), "extra_persons": sorted(extra),
            "other_books": other_books(text.rows["books.jsonl"]),
            "lexicon_blockers": blockers,
            "sources": dict(zip(SOURCES, read))}
