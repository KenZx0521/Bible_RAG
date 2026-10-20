"""The names file of the GEN confirmation set (prereg §5.1) -> store gen_names.json. Host python, stdlib only.

Built by program, never by hand, from stage-0's frozen gen_layer.json (sha256 46d87abb2900…), the text
layer's name_spans.jsonl and books.jsonl (text@247eafe44b02, the layer gen_layer.json was read from) and
the release's routing lexicon (b20261019_a86f2b06). Schema ``gen_confirm.gen_names.v1``, exactly these keys:

- ``chain``: the 19 chain persons of gen_layer.json, chapter 5 then 11, in chain order (id, name, chapter);
- ``cain_line`` (prereg §5.2 rule 4): the name_spans of Genesis 4 off the chain, with every name rule 4
  lists (``CAIN_REQUIRED``);
- ``abram_family`` (rule 4): the name_spans of gen.11.26–gen.11.32 off the chain, with the rule-4 list;
- ``extra_persons`` (mech_g's extra_name, prereg §3.4): every name_spans surface of Genesis 4, 5, 10 and 11,
  the Cain line and the Abram family, off the chain;
- ``other_books`` (rule 2): the names of Luke, 1 Chronicles, Matthew, Hebrews and Jude and their
  abbreviations of two or more characters (books.jsonl), with 路加, 歷代志 and 馬太;
- ``lexicon_blockers`` (rule 3): the lexicon's names (kind ``name``; a dotted one also dotless, as prod's
  dotless kind) that hold a chain name and are none, with 以諾城;
- ``text_digest``, ``gen_layer_sha256`` and ``sources`` (sha256 of every input, by store path).

Every surface is NFKC; a surface written with ‧ also comes without it (土八‧該隱, 土八該隱). The file holds
names only, never scripture text. ``python names_g.py`` writes it (``g_common.write_json``) and prints its
sha256; ``--check`` rebuilds and compares with the stored file without writing. Nothing calls an LLM.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import g_common as GC

SCHEMA = "gen_confirm.gen_names.v1"
OUT = GC.GEN_NAMES
TEXT_DIR = GC.TEXT_LAYER
TEXT_DIGEST = "247eafe44b02ed27f49d244ba525d02b87bd7c8402ca03ce38cb97972a12e75a"
LEXICON = GC.ROUTING_LEXICON
CHAPTERS = (5, 11)
CAIN_CHAPTER = 4
ABRAM_CHAPTER, ABRAM_VERSES = 11, range(26, 33)          # gen.11.26–gen.11.32
EXTRA_CHAPTERS = (4, 5, 10, 11)
# prereg §5.2 rule 4 and rule 2, as listed there
CAIN_REQUIRED = ("該隱", "以拿", "米戶雅利", "瑪土撒利", "亞大", "洗拉", "雅八", "猶八", "土八該隱", "拿瑪", "挪得")
ABRAM_REQUIRED = ("亞伯蘭", "亞伯拉罕", "哈蘭", "撒萊", "密迦", "羅得")
OTHER_BOOK_IDS = ("luk", "1ch", "mat", "heb", "jud")
BOOK_WORDS = ("路加", "歷代志", "馬太")                   # rule 2's short forms books.jsonl does not list
BOOKS_REQUIRED = ("路加", "路加福音", "歷代志", "歷代志上", "代上", "馬太", "馬太福音", "希伯來書", "猶大書")
BLOCKER_EXTRA = ("以諾城",)
BLOCKERS_REQUIRED = ("希伯來", "希伯崙", "法勒斯", "以利法勒", "沙拉音", "瑪挪亞", "亞施他拉", "以諾城")
DOT = "‧"
_KEY = re.compile(r"gen\.(\d+)\.(\d+)")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]


def _source_key(p: Path) -> str:
    p = Path(p).resolve()
    return str(p.relative_to(GC.STORE.resolve())) if GC.STORE.resolve() in p.parents else p.name


def _forms(surfaces) -> set[str]:
    """NFKC surfaces, a dotted one also without its dots."""
    out = {nfkc(s) for s in surfaces}
    return out | {s.replace(DOT, "") for s in out if DOT in s}


def _verse(container: str) -> tuple[int, int] | None:
    m = _KEY.match(container)
    return (int(m.group(1)), int(m.group(2))) if m else None


def surfaces_by_verse(spans: list[dict]) -> list[tuple[int, int, str]]:
    """(chapter, verse, surface) of every Genesis name span (a range key counts from its first verse)."""
    return [(v[0], v[1], r["surface"]) for r in spans if (v := _verse(r["container_id"]))]


def chain_of(gen: dict) -> list[dict]:
    nodes = sorted((n for n in gen["nodes"] if n["chapter"] in CHAPTERS), key=lambda n: (n["chapter"], n["order"]))
    return [{"id": n["id"], "name": nfkc(n["name"]), "chapter": n["chapter"]} for n in nodes]


def other_books(books: list[dict], book_words=BOOK_WORDS) -> list[str]:
    out = set(book_words)
    for b in books:
        if b["book_id"] in OTHER_BOOK_IDS:
            out |= {b["name"]} | {s for s in b.get("short_names", []) if len(s) >= 2}
    return sorted(nfkc(s) for s in out)


def lexicon_blockers(lexicon: dict, chain: set[str], extra=BLOCKER_EXTRA) -> list[str]:
    surfaces = _forms(t["surface"] for t in lexicon["names"] if t["kind"] == "name")
    return sorted({s for s in surfaces if s not in chain and any(n in s for n in chain)} | set(extra))


def build(gen_layer: Path | str = GC.GEN_LAYER, text_dir: Path | str = TEXT_DIR, lexicon: Path | str = LEXICON, *,
          cain_required=CAIN_REQUIRED, abram_required=ABRAM_REQUIRED, book_words=BOOK_WORDS,
          blocker_extra=BLOCKER_EXTRA) -> dict:
    gen_layer, text_dir, lexicon = Path(gen_layer), Path(text_dir), Path(lexicon)
    gen = GC.read_json(gen_layer)
    manifest = text_dir / "layer_manifest.json"
    digest = GC.read_json(manifest)["digest"]
    if digest != gen["text_digest"]:
        raise SystemExit(f"text layer {digest[:12]} is not the one gen_layer.json was read from")
    spans = surfaces_by_verse(jsonl(text_dir / "name_spans.jsonl"))
    chain = chain_of(gen)
    names = {c["name"] for c in chain}
    cain = (_forms(s for c, _v, s in spans if c == CAIN_CHAPTER) | _forms(cain_required)) - names
    abram = (_forms(s for c, v, s in spans if c == ABRAM_CHAPTER and v in ABRAM_VERSES) | _forms(abram_required)) - names
    extra = (_forms(s for c, _v, s in spans if c in EXTRA_CHAPTERS) | cain | abram) - names
    files = (gen_layer, text_dir / "name_spans.jsonl", text_dir / "books.jsonl", manifest, lexicon)
    return {"schema": SCHEMA, "text_digest": digest, "gen_layer_sha256": GC.sha256_file(gen_layer), "chain": chain,
            "cain_line": sorted(cain), "abram_family": sorted(abram), "extra_persons": sorted(extra),
            "other_books": other_books(jsonl(text_dir / "books.jsonl"), book_words),
            "lexicon_blockers": lexicon_blockers(GC.read_json(lexicon), names, blocker_extra),
            "sources": {_source_key(p): GC.sha256_file(p) for p in files}}


def problems(doc: dict, *, cain_required=CAIN_REQUIRED, abram_required=ABRAM_REQUIRED, books_required=BOOKS_REQUIRED,
             blockers_required=BLOCKERS_REQUIRED, store: bool = True) -> list[str]:
    """Contract problems of a names document (empty = ok); ``store`` adds the real inputs' pins."""
    keys = ["schema", "text_digest", "gen_layer_sha256", "chain", "cain_line", "abram_family", "extra_persons",
            "other_books", "lexicon_blockers", "sources"]
    if list(doc) != keys:
        return [f"keys {list(doc)} are not the contract's"]
    out = [] if doc["schema"] == SCHEMA else [f"schema {doc['schema']}"]
    for key, want in (("cain_line", cain_required), ("abram_family", abram_required),
                      ("other_books", books_required), ("lexicon_blockers", blockers_required)):
        missing = sorted(set(map(nfkc, want)) - set(doc[key]))
        out += [f"{key} misses {len(missing)} required names"] if missing else []
    if store:
        out += [] if doc["text_digest"] == TEXT_DIGEST else ["text digest is not text@247eafe44b02"]
        out += [] if doc["gen_layer_sha256"].startswith(GC.GEN_LAYER_SHA256_PREFIX) else ["gen_layer.json sha256"]
        out += [] if len(doc["chain"]) == 19 else [f"{len(doc['chain'])} chain persons, not 19"]
    return out


def main(argv: list[str]) -> int:
    doc = build()
    bad = problems(doc)
    if bad:
        print("gen_names.json not written:", bad)
        return 1
    if "--check" in argv:
        same = OUT.is_file() and GC.read_json(OUT) == doc
        print("gen_names.json", "matches a rebuild" if same else "differs from a rebuild or is missing")
        return 0 if same else 1
    GC.write_json(OUT, doc)
    print("gen_names.json sha256", GC.sha256_file(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
