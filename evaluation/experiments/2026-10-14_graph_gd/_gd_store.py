"""Store pins, pinned reads, layer loaders and §4 gold resolution (private part of gd_common).

Import through gd_common. Everything is read from the store, never /tmp, and verified
on load: each layer file against its layer_manifest.json, whose digest must give the
pinned layer version (ragdata/store/cas.py rule), the vectors against VECTORS_SHA256,
and the counts the prereg states. A mismatch raises. Loaders are cached and return
immutable values (frozen dataclasses, tuples, read-only mappings, read-only matrix).
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

__all__ = [
    "EXP_DIR", "PREREG_PATH", "HO_PATH", "STORE", "LAYERS_ROOT", "OUT_ROOT", "E7", "WF",
    "PN", "EV", "AT", "FM", "PO", "PRECHECK", "X_ARMS", "X_DATA", "X_METRICS", "R_IMPL", "R_STATS",
    "LAYER_VERSIONS", "VECTORS_SHA256", "N_PASSAGES", "N_VERSE_UNITS", "N_BODY_NAMES", "N_BOOKS",
    "N_EMB_ROWS", "EMB_DIM", "GdError", "IntegrityError", "GoldError", "HalfVerseKeyError",
    "file_sha256", "ids_sha256", "Passage", "VerseIndex", "VerseUnits", "NameSpan", "Kg0Name",
    "EmbLayer", "load_passages", "load_verse_index", "load_verse_units", "load_body_spans",
    "load_book_names", "load_kg0_names", "load_query_aliases", "load_emb", "find_unit",
    "is_half_verse_key", "read_pinned", "resolve_key", "hop_gold", "ACCEPT_DIR", "EV_SEL_IN",
    "EV_SEL_OUT", "ARCHIVE_SHA256"]

EXP_DIR = Path(__file__).resolve().parent
PREREG_PATH = EXP_DIR / "prereg.md"
HO_PATH = EXP_DIR / "heldout_ho.json"
ACCEPT_DIR = EXP_DIR / "accept"            # accept_a.json, accept_b.json (§3)
STORE = Path("/mnt/ollama-data/bible_rag_store")
LAYERS_ROOT = STORE / "layers"
OUT_ROOT = STORE / "reports" / "graph_gd_20261014"
_MH = STORE / "reports" / "multihop_kg_20261012"
E7 = _MH / "session_e73fd5d9"
WF = _MH / "session_15748325_graphsel" / "wf"
PN, EV, AT, FM, PO = (WF / d for d in ("probe_newq", "verify_evidence", "verify_attribution",
                                       "final_merge", "probe_old31"))
PRECHECK = _MH / "session_15748325_graphsel" / "prereg_check"
X_ARMS, X_DATA, X_METRICS = (PRECHECK / d for d in ("x_arms", "x_data", "x_metrics"))
R_IMPL, R_STATS = PRECHECK / "review_impl", PRECHECK / "review_stats"
EV_SEL_IN, EV_SEL_OUT = EV / "ev_sel_in.json", EV / "ev_sel_out.jsonl"
# archived inputs read by more than one script (§3 驗收 A/B, §10 reference pairs)
ARCHIVE_SHA256 = MappingProxyType({
    EV_SEL_IN: "c26500b0f3807aaee8726adb70374c64326198dd0d5ab5e210e89180e21615a5",
    EV_SEL_OUT: "2f9081c37aee92dcb6b6ffb4562d3fcdd0b3d0d83ca1b7748b00a4aecd0069a8",
    EV / "prf_lists.json": "da4f61954a8a1740b57b204ba68e6f5250ac3974023f752fefd0edb56146a89b",
    AT / "prf_lists.json": "1ad6f2f12ce6a2bd53b994ca4871e3e963b044efdd13a21c578663d01a9e6d07",
    PN / "encode_out.jsonl": "1c4f8461ccca0e5cd8551a90b27e9aa7615fc1c679c2e8e5f0b16dbc136e306e",
    PN / "rr_d5_in.json": "5b3133d96812cb9079582d37198dc64d3195a485da3bc446761d68b292eadedf",
    PN / "rr_d5_out.jsonl": "dd1ed56c1c9dcb8b0ab3e903476d18923088531ba030bb94381a8f697c11caa5",
    FM / "gd_hub.json": "092a36062ebdb60ebe08badc18c008fd23e1fb444347e07cff3e153af35e8da3"})

LAYER_VERSIONS = MappingProxyType({"text": "text@247eafe44b02", "struct": "struct@d8d432b4df15",
                                   "emb": "emb@ae5525447eda", "kg0": "kg0@14e68c8344b1",
                                   "route": "route@c31c88e4681e"})
VECTORS_SHA256 = "870ca1fc695585a592fc3b31dbeee8fd90e1e14779e1937aa94b1f8c736e579c"
N_PASSAGES, N_VERSE_UNITS, N_BODY_NAMES, N_BOOKS = 2773, 31021, 2929, 66
N_EMB_ROWS, EMB_DIM = 34058, 1024

_HALF_KEY = re.compile(r"\.\d+[ab](?=-|$)")


class GdError(RuntimeError):
    """Base error of the GD experiment scripts."""


class IntegrityError(GdError):
    """A store file, count, fingerprint, build or image is not the pinned one."""


class GoldError(GdError):
    """A hop slot key cannot be turned into §4 gold passages."""


class HalfVerseKeyError(GoldError):
    """An a/b half-verse key: bt.resolve cannot place it, so §4 gold is undefined."""


# ------------------------------------------------------------------ hashing and pinned reads

def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ids_sha256(ids: Iterable[str]) -> str:
    """§2 question-id sha: sha256 of "\\n".join(sorted(ids)) in UTF-8, no trailing newline."""
    ids = list(ids)
    if len(set(ids)) != len(ids):
        raise IntegrityError("duplicate question ids")
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def read_pinned(path: Path, sha: str) -> bytes:
    """The file's bytes, after checking they hash to `sha` (read once: no check/use race)."""
    if not Path(path).is_file():
        raise IntegrityError(f"{path}: pinned file is missing")
    data = Path(path).read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise IntegrityError(f"{path}: sha256 {got} is not the pinned {sha}")
    return data


def expect(what: str, got: Any, want: Any) -> None:
    if got != want:
        raise IntegrityError(f"{what}: got {got!r}, expected {want!r}")


def _jsonl(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


@functools.cache
def _manifest(root: Path, layer: str) -> Mapping[str, str]:
    """File -> sha256 of a pinned layer, after checking the manifest digest gives its version."""
    version = LAYER_VERSIONS[layer]
    path = root / layer / version / "layer_manifest.json"
    if not path.is_file():
        raise IntegrityError(f"{path}: the pinned {layer} layer version is not in the store")
    m = json.loads(path.read_text(encoding="utf-8"))
    lines = "".join(f"{n}\t{m['files'][n]}\n" for n in sorted(m["files"]))
    digest = hashlib.sha256(lines.encode("utf-8")).hexdigest()
    expect(f"{layer} manifest digest", m["digest"], digest)
    expect(f"{layer} version", (m["layer_version"], f"{layer}@{digest[:12]}"), (version, version))
    return MappingProxyType(dict(m["files"]))


def _layer_bytes(root: Path, layer: str, name: str) -> bytes:
    return read_pinned(root / layer / LAYER_VERSIONS[layer] / name, _manifest(root, layer)[name])


# ------------------------------------------------------------------ layers

@dataclass(frozen=True)
class Passage:
    row: int                           # passages.jsonl line index (the §3 列序)
    passage_id: str
    content: str
    start_key: str
    end_key: str
    title: str


@dataclass(frozen=True)
class VerseIndex:
    passage_of: Mapping[str, str]                 # unit_key -> passage_id
    split_of: Mapping[str, tuple[str, ...]]       # unit_key -> split_passage_ids

    def passages_of(self, unit_key: str) -> frozenset[str]:
        """§4: the unit's passage_id ∪ split_passage_ids."""
        if unit_key not in self.passage_of:
            raise GoldError(f"unit {unit_key} is not in verse_index")
        return frozenset((self.passage_of[unit_key], *self.split_of[unit_key]))


@dataclass(frozen=True)
class VerseUnits:
    order: tuple[str, ...]                        # verse_units.jsonl order
    span: Mapping[str, tuple[int, int]]           # unit_key -> (v_start, v_end)
    index: Mapping[str, int] = field(init=False, repr=False)
    merged: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "index", MappingProxyType({k: i for i, k in enumerate(self.order)}))
        object.__setattr__(self, "merged", tuple(k for k in self.order if "-" in k))


@dataclass(frozen=True)
class NameSpan:
    container_id: str                  # a verse unit_key (every body span's container is one)
    norm_key: str
    surface: str
    start: int
    end: int


@dataclass(frozen=True)
class Kg0Name:
    norm_key: str
    surfaces: tuple[str, ...]


@dataclass(frozen=True)
class EmbLayer:
    matrix: np.ndarray                 # (N_EMB_ROWS, EMB_DIM) float32 as stored, read-only
    record_ids: tuple[str, ...]        # per row
    row_pids: tuple[str, ...]          # per row: payload.passage_id (verse/chunk -> its passage)


@functools.cache
def load_passages(root: Path = LAYERS_ROOT) -> tuple[Passage, ...]:
    rows = _jsonl(_layer_bytes(root, "struct", "passages.jsonl"))
    out = tuple(Passage(i, p["passage_id"], p["content"], p["start_key"], p["end_key"],
                        p.get("title") or "") for i, p in enumerate(rows))
    expect("passages", (len(out), len({p.passage_id for p in out})), (N_PASSAGES, N_PASSAGES))
    return out


@functools.cache
def load_verse_index(root: Path = LAYERS_ROOT) -> VerseIndex:
    rows = _jsonl(_layer_bytes(root, "struct", "verse_index.jsonl"))
    out = VerseIndex(MappingProxyType({r["unit_key"]: r["passage_id"] for r in rows}),
                     MappingProxyType({r["unit_key"]: tuple(r["split_passage_ids"]) for r in rows}))
    expect("verse_index units", (len(rows), len(out.passage_of)), (N_VERSE_UNITS, N_VERSE_UNITS))
    stray = {p for u in out.passage_of for p in out.passages_of(u)}
    stray -= {p.passage_id for p in load_passages(root)}
    expect("verse_index passages outside passages.jsonl", sorted(stray), [])
    return out


@functools.cache
def load_verse_units(root: Path = LAYERS_ROOT) -> VerseUnits:
    rows = _jsonl(_layer_bytes(root, "text", "verse_units.jsonl"))
    out = VerseUnits(tuple(u["unit_key"] for u in rows),
                     MappingProxyType({u["unit_key"]: (u["v_start"], u["v_end"]) for u in rows}))
    expect("verse_units", (len(out.order), len(out.span)), (N_VERSE_UNITS, N_VERSE_UNITS))
    return out


@functools.cache
def load_body_spans(root: Path = LAYERS_ROOT) -> tuple[NameSpan, ...]:
    """name_spans.jsonl rows with region == 'body', file order."""
    rows = _jsonl(_layer_bytes(root, "text", "name_spans.jsonl"))
    out = tuple(NameSpan(s["container_id"], s["norm_key"], s["surface"], s["start"], s["end"])
                for s in rows if s["region"] == "body")
    expect("body norm_keys", len({s.norm_key for s in out}), N_BODY_NAMES)
    vi = load_verse_index(root).passage_of
    expect("body spans outside verse_index", sorted({s.container_id for s in out} - set(vi)), [])
    return out


@functools.cache
def load_book_names(root: Path = LAYERS_ROOT) -> tuple[str, ...]:
    """books.jsonl `name`, file order."""
    out = tuple(b["name"] for b in _jsonl(_layer_bytes(root, "text", "books.jsonl")))
    expect("books", len(out), N_BOOKS)
    return out


@functools.cache
def load_kg0_names(root: Path = LAYERS_ROOT) -> tuple[Kg0Name, ...]:
    """kg0 names.jsonl, file order (the surf_table order of §3 G)."""
    rows = _jsonl(_layer_bytes(root, "kg0", "names.jsonl"))
    return tuple(Kg0Name(n["norm_key"], tuple(n["surfaces"])) for n in rows)


@functools.cache
def load_query_aliases(root: Path = LAYERS_ROOT) -> tuple[tuple[str, str], ...]:
    """route query_aliases.json aliases as (surface, target), file order."""
    data = json.loads(_layer_bytes(root, "route", "query_aliases.json"))
    return tuple((a["surface"], a["target"]) for a in data["aliases"])


@functools.cache
def load_emb(root: Path = LAYERS_ROOT) -> EmbLayer:
    """vectors.npy rows (vector_index row order) with each row's record id and passage."""
    vdir = root / "emb" / f"{LAYER_VERSIONS['emb']}.vectors"
    if not (vdir / "attachment_manifest.json").is_file():
        raise IntegrityError(f"{vdir}: the pinned vectors attachment is not in the store")
    att = json.loads((vdir / "attachment_manifest.json").read_text(encoding="utf-8"))
    expect("vectors attachment", (att["layer_version"], att["files"]["vectors.npy"]),
           (LAYER_VERSIONS["emb"], VECTORS_SHA256))
    matrix = np.load(io.BytesIO(read_pinned(vdir / "vectors.npy", VECTORS_SHA256)), allow_pickle=False)
    matrix.flags.writeable = False
    expect("vectors", (matrix.shape, matrix.dtype), ((N_EMB_ROWS, EMB_DIM), np.dtype(np.float32)))
    idx = sorted(_jsonl(read_pinned(vdir / "vector_index.jsonl", att["files"]["vector_index.jsonl"])),
                 key=lambda r: r["row"])
    expect("vector_index rows", [r["row"] for r in idx], list(range(N_EMB_ROWS)))
    rec_pid = {r["record_id"]: r["payload"]["passage_id"]
               for r in _jsonl(_layer_bytes(root, "emb", "embedding_records.jsonl"))}
    record_ids = tuple(r["record_id"] for r in idx)
    expect("embedding records", set(rec_pid), set(record_ids))
    row_pids = tuple(rec_pid[r] for r in record_ids)
    stray = set(row_pids) - {p.passage_id for p in load_passages(root)}
    expect("emb records outside passages.jsonl", sorted(stray), [])
    return EmbLayer(matrix, record_ids, row_pids)


# ------------------------------------------------------------------ §4 gold (bt.py:43-70)

def find_unit(key: str, units: VerseUnits) -> str | None:
    """bt.find_unit: the unit key itself, else the first merged unit (book.ch.a-b) holding the verse."""
    if key in units.span:
        return key
    book_ch, _, v = key.rpartition(".")
    if not v.isdigit():
        return None
    for k in units.merged:
        lo, hi = units.span[k]
        if k.startswith(book_ch + ".") and lo <= int(v) <= hi:
            return k
    return None


def is_half_verse_key(key: str) -> bool:
    return _HALF_KEY.search(key) is not None


def resolve_key(key: str, units: VerseUnits | None = None) -> tuple[str, ...]:
    """bt.resolve for one slot key -> its unit keys; raises on a half-verse or unresolvable key."""
    units = units or load_verse_units()
    if is_half_verse_key(key):
        raise HalfVerseKeyError(f"half-verse key {key!r} has no §4 gold (bt.resolve cannot place it)")
    parts = key.split("-")
    if len(parts) == 2 and parts[1].count(".") == 2:
        s, e = find_unit(parts[0], units), find_unit(parts[1], units)
        if s is None or e is None or units.index[s] > units.index[e]:
            raise GoldError(f"range key {key!r} does not resolve")
        return units.order[units.index[s]:units.index[e] + 1]
    unit = find_unit(key, units)
    if unit is None:
        raise GoldError(f"slot key {key!r} does not resolve to a verse unit")
    return (unit,)


def hop_gold(slots: Sequence[str], units: VerseUnits | None = None,
             vindex: VerseIndex | None = None) -> frozenset[str]:
    """§4 gold of one hop: ∪ over its slot keys' units of passage_id ∪ split_passage_ids."""
    if not slots:
        raise GoldError("a hop without slot keys has no gold")
    vindex = vindex or load_verse_index()
    return frozenset(p for key in slots for u in resolve_key(key, units) for p in vindex.passages_of(u))
