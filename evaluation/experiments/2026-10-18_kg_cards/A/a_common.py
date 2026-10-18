"""Paths and store readers shared by experiment A (prereg.md §2). Host python3 -B, stdlib only.

Data (layers, items, prompts, outputs) go to store reports/kg_cards_20261018/A/ only; the
repo holds code and text-free notes. Nothing here calls Ollama.
"""
from __future__ import annotations

import functools
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import cards_common as cc  # noqa: E402

REPO = HERE.parents[3]
GD_DIR = REPO / "evaluation/experiments/2026-10-14_graph_gd"
EVAL_DIR = REPO / "evaluation"
K5 = cc.KS / "probe_C5"
POWER_A = cc.KS / "synth/powerA_strong.py"
STRUCT = cc.STORE / "layers/struct/struct@d8d432b4df15"
TEXT = cc.TEXT_LAYER
LANES = cc.STORE / "reports/graph_qd_20261018/lanes.json"
REALKG_INPUTS = cc.MH / "realkg/inputs_nogold.json"
OUT = cc.OUT_ROOT / "A"

LAYER_AUTO = OUT / "layer_auto.json"
LAYER_REF = OUT / "ref_layer.json"
ITEMS = OUT / "items.json"
MANIFEST = OUT / "inputs_manifest.json"
GEN_SEED = OUT / "gen_seed.jsonl"
GEN_ARMS = OUT / "gen_arms.jsonl"
ARMS_JOBS = OUT / "arms_jobs.json"
ARMS_META = OUT / "arms_meta.json"
SCORES = OUT / "scores.json"
REPORT_JSON, REPORT_MD = OUT / "report.json", OUT / "report.md"

KNAME = {"I": "以色列", "J": "猶大"}
SEED = 20261018
CAP_CHARS = 900


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def prompts_sha256(jobs: list[dict]) -> str:
    """One sha256 over the (job_id, system, user) of a job list, in order."""
    return sha256_text(json.dumps([[j["job_id"], j["system"], j["user"]] for j in jobs], ensure_ascii=False))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jsonl(p: Path):
    with Path(p).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


@functools.cache
def verse_units() -> dict:
    """unit_key -> verse_units.jsonl row (text layer)."""
    return {r["unit_key"]: r for r in jsonl(TEXT / "verse_units.jsonl")}


def verse_text(key: str) -> str | None:
    r = verse_units().get(key)
    return r["text"] if r else None


@functools.cache
def books() -> dict:
    return {r["book_id"]: r for r in jsonl(TEXT / "books.jsonl")}


def short_ref(key: str) -> str:
    """'2ki.15.8' -> '王下15:8' (books.jsonl short_names[0])."""
    b, c, v = key.split(".")
    return f"{books()[b]['short_names'][0]}{c}:{v}"


@functools.cache
def footnotes() -> dict:
    out: dict[str, list] = {}
    for r in jsonl(TEXT / "footnotes.jsonl"):
        out.setdefault(r["unit_key"], []).append(r)
    return out


@functools.cache
def passages() -> dict:
    return {r["passage_id"]: r for r in jsonl(STRUCT / "passages.jsonl")}


@functools.cache
def verse_passage() -> dict:
    return {r["unit_key"]: r["passage_id"] for r in jsonl(STRUCT / "verse_index.jsonl")}


def passage_source(pid: str) -> dict:
    """prod postgres._passage fields used by build_context_blocks, from the struct layer."""
    p = passages()[pid]
    book_id, chapter = p["chapter_key"].split(".")
    return {"id": pid, "book_name": books()[book_id]["name"], "chapter_num": int(chapter),
            "title": p["title"] or "", "verse_range": p["verse_range"], "content": p["content"],
            "from": f"struct@d8d432b4df15 passages.jsonl {pid}"}


def realkg_source(src: dict) -> dict:
    """MH realkg gen_in_container.base_dict: prod-returned context minus its header line."""
    _header, _, content = src["context"].partition("\n")
    return {"id": src["id"], "book_name": src.get("book") or "", "chapter_num": src.get("chapter"),
            "title": src.get("title") or "", "verse_range": src.get("verse_range") or "",
            "content": content, "from": "MH/realkg/inputs_nogold.json dk_sources"}
