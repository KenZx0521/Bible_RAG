"""Freeze the R1 evaluation's question sets before any R1 result exists (prereg.md).

Derived mechanically from the text layer's ``diff_vs_bible_md.tsv`` and GT v2,
never from a retrieval result:

* the damaged slice (受損切片): G01 converter losses, G15 mid-verse headings,
  G02 hand-edited variants, and their union (C3 scores the union only);
* the G-ANS subset: question_type × {legacy_head, expanded}, 8 + 32 per type
  (200), the smallest sha256("r1-gans-200|{question_id}") within a stratum.

GT v2 must be the frozen bytes of config/gold/gt_v2_freeze.json and the tsv
the file its layer manifest lists, of the layer GT v2's slot_universe names;
otherwise nothing is written. ``frozen_r1.json`` is byte-deterministic (sorted
keys and lists, no timestamps). This file has no commit yet, so the record
carries its sha256: any edit to it makes ``--check`` fail. Writing never
replaces a different frozen_r1.json without ``--force``.

    python experiments/2026-10-08_r1/freeze_r1.py            (from evaluation/)
    python experiments/2026-10-08_r1/freeze_r1.py --check    exit 1 if frozen_r1.json differs

Read the result with ``src.r1_frozen.load_frozen``, which accepts only the
bytes ``src.r1_frozen.FROZEN_R1_SHA256`` pins: a re-freeze also needs a new pin.
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

SCRIPT = Path(__file__).resolve()
HERE = SCRIPT.parent
EVAL_ROOT = HERE.parents[1]
REPO = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from src.gt_v2 import (  # noqa: E402
    FREEZE_PATH, GT_V2_PATH, GroundTruthItemV2, GtV2Error, load_ground_truth_v2,
)
from src.r1_frozen import SCHEMA, SUB_SLICES  # noqa: E402
from ragcommon import ids  # noqa: E402  (on sys.path once src is imported)

TEXT_LAYER = Path("/mnt/ollama-data/bible_rag_store/layers/text/text@247eafe44b02")
DIFF_TSV = TEXT_LAYER / "diff_vs_bible_md.tsv"
OUT = HERE / "frozen_r1.json"
TSV_COLUMNS = ("container", "kind", "op", "offset", "layer_text", "md_text", "class")

G01_EXCLUDED = ("converter_speaker_label", "converter_footnotes_glued")
G02_CLASSES = ("hand_edit_ghost_verse", "hand_edit_variant_merged")
SALT = "r1-gans-200"
LEGACY, EXPANDED = "legacy_head", "expanded"
QUOTA = {LEGACY: 8, EXPANDED: 32}

RULES = {
    "slots": "a container is a ragcommon.ids verse key: a slot stands for itself, a merged "
             "unit (gen.24.29-30) for each of its verses",
    "G01": "kind=unit rows whose class starts with converter_, except "
           + " and ".join(G01_EXCLUDED) + "; questions whose gold_slots intersect",
    "G15": "kind=unit rows of class converter_midverse_heading; questions whose gold_slots "
           "intersect",
    "G02": "rows of class " + " or ".join(G02_CLASSES) + " (any kind); questions whose "
           "gold_slots or omitted_slots intersect",
    "union": "G01 ∪ G15 ∪ G02; the only set C3 scores",
    "gans_subset": "strata question_type × (family == legacy_head ? legacy_head : expanded); "
                   "per question_type 8 legacy_head + 32 expanded; within a stratum the "
                   f"questions with the smallest sha256(\"{SALT}|{{question_id}}\") hex digest",
}

Row = dict[str, str]
Items = Iterable[GroundTruthItemV2]
SLICES: tuple[tuple[str, Callable[[Row], bool], tuple[str, ...]], ...] = (
    ("G01", lambda r: (r["kind"] == "unit" and r["class"].startswith("converter_")
                       and r["class"] not in G01_EXCLUDED), ("gold_slots",)),
    ("G15", lambda r: r["kind"] == "unit" and r["class"] == "converter_midverse_heading",
     ("gold_slots",)),
    ("G02", lambda r: r["class"] in G02_CLASSES, ("gold_slots", "omitted_slots")),
)


class FreezeError(ValueError):
    """An input is not the one the prereg pins, or does not have its shape."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    resolved = Path(path).resolve()
    return str(resolved.relative_to(REPO)) if resolved.is_relative_to(REPO) else str(resolved)


def read_diff(path: Path) -> list[Row]:
    """The tsv's rows; cells escape tab and newline, so lines and cells split plainly."""
    lines = Path(path).read_bytes().decode("utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != TSV_COLUMNS:
        raise FreezeError(f"{path}: header is not {TSV_COLUMNS}")
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(TSV_COLUMNS):
            raise FreezeError(f"{path}:{n}: {len(cells)} cells, not {len(TSV_COLUMNS)}")
        rows.append(dict(zip(TSV_COLUMNS, cells)))
    return rows


def text_layer(tsv: Path, slot_universe: str) -> dict:
    """The tsv's layer: its manifest must list the tsv's bytes and be GT v2's slot_universe."""
    try:
        manifest = json.loads((Path(tsv).parent / "layer_manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read the layer manifest next to {tsv}: {exc}") from None
    digest = sha256_of(tsv)
    if manifest.get("files", {}).get(Path(tsv).name) != digest:
        raise FreezeError(f"{tsv}: sha256 {digest} is not the one its layer manifest lists")
    if manifest.get("layer_version") != slot_universe:
        raise FreezeError(f"text layer {manifest.get('layer_version')} is not GT v2's "
                          f"slot_universe {slot_universe}")
    return {"layer_version": manifest["layer_version"], "diff_tsv": str(tsv),
            "diff_tsv_sha256": digest}


def slots_of(container: str) -> list[str]:
    """A diff container's slot keys: a slot is itself, a merged unit each of its verses."""
    try:
        key = ids.parse(container)
    except ids.IdError as exc:
        raise FreezeError(f"container {container!r}: {exc}") from None
    if key.kind not in ("slot", "unit"):
        raise FreezeError(f"container {container!r} is a {key.kind}, not a verse slot or unit")
    return [f"{key.book_id}.{key.chapter}.{v}"
            for v in range(key.verse, (key.verse_end or key.verse) + 1)]


def sub_slice(rows: Iterable[Row], items: Items, keep: Callable[[Row], bool],
              fields: tuple[str, ...]) -> dict:
    containers = sorted({r["container"] for r in rows if keep(r)})
    slots = sorted({s for c in containers for s in slots_of(c)})
    hit = set(slots)
    qids = sorted(q.question_id for q in items
                  if any(hit.intersection(getattr(q, f)) for f in fields))
    return {"containers": containers, "n_containers": len(containers),
            "slots": slots, "n_slots": len(slots),
            "question_ids": qids, "n_questions": len(qids)}


def damaged_slice(rows: list[Row], items: Items) -> dict:
    subs = {name: {"rule": RULES[name], "match_fields": list(fields),
                   **sub_slice(rows, items, keep, fields)}
            for name, keep, fields in SLICES}
    assert tuple(subs) == SUB_SLICES
    union = sorted(set().union(*(s["question_ids"] for s in subs.values())))
    return {"slot_rule": RULES["slots"], "sub_slices": subs,
            "union": {"rule": RULES["union"], "question_ids": union, "n_questions": len(union)}}


def gans_rank(question_id: str) -> str:
    return hashlib.sha256(f"{SALT}|{question_id}".encode("utf-8")).hexdigest()


def gans_subset(items: Items) -> dict:
    pools: dict[tuple[str, str], list[str]] = defaultdict(list)
    for q in items:
        pools[(q.question_type, LEGACY if q.family == LEGACY else EXPANDED)].append(q.question_id)
    chosen: list[str] = []
    strata: dict[str, dict] = {}
    for qtype in sorted({t for t, _ in pools}):
        for group, quota in sorted(QUOTA.items()):
            pool = sorted(pools[(qtype, group)], key=lambda qid: (gans_rank(qid), qid))
            if len(pool) < quota:
                raise FreezeError(f"stratum {qtype}/{group} has {len(pool)} questions, "
                                  f"fewer than {quota}")
            chosen += pool[:quota]
            strata.setdefault(qtype, {})[group] = {"n_pool": len(pool), "n_selected": quota}
    return {"rule": RULES["gans_subset"], "salt": SALT, "quota": dict(QUOTA),
            "strata": strata, "question_ids": sorted(chosen), "n_questions": len(chosen)}


def derive(gt_path: Path = GT_V2_PATH, freeze_path: Path = FREEZE_PATH,
           tsv: Path = DIFF_TSV) -> dict:
    gt = load_ground_truth_v2(Path(gt_path), Path(freeze_path))
    layer = text_layer(Path(tsv), gt.slot_universe)
    rows = read_diff(Path(tsv))
    return {
        "schema": SCHEMA,
        "prereg": _rel(HERE / "prereg.md"),
        "script": {"path": _rel(SCRIPT), "sha256": sha256_of(SCRIPT)},
        "gt": {"path": _rel(gt_path), "sha256": gt.sha256, "freeze_record": _rel(freeze_path),
               "slot_universe": gt.slot_universe, "n_questions": len(gt.items)},
        "text_layer": layer,
        "damaged_slice": damaged_slice(rows, gt.items),
        "gans_subset": gans_subset(gt.items),
    }


def render(frozen: dict) -> bytes:
    return (json.dumps(frozen, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()


def summary(frozen: dict) -> str:
    subs = frozen["damaged_slice"]["sub_slices"]
    lines = [f"{name}: {s['n_containers']} containers, {s['n_slots']} slots, "
             f"{s['n_questions']} questions" for name, s in subs.items()]
    lines.append(f"damaged union: {frozen['damaged_slice']['union']['n_questions']} questions")
    strata = frozen["gans_subset"]["strata"]
    lines.append(f"G-ANS subset: {frozen['gans_subset']['n_questions']} questions; "
                 + ", ".join(f"{t} {s[LEGACY]['n_selected']}+{s[EXPANDED]['n_selected']}"
                             for t, s in sorted(strata.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Freeze the R1 damaged slice and G-ANS subset.")
    ap.add_argument("--gt", type=Path, default=GT_V2_PATH)
    ap.add_argument("--gt-freeze", type=Path, default=FREEZE_PATH)
    ap.add_argument("--tsv", type=Path, default=DIFF_TSV)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true",
                    help="re-derive and exit 1 if --out differs; write nothing")
    ap.add_argument("--force", action="store_true",
                    help="replace an --out whose bytes differ from the re-derivation")
    a = ap.parse_args(argv)
    try:
        frozen = derive(a.gt, a.gt_freeze, a.tsv)
    except (GtV2Error, FreezeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    data = render(frozen)
    if a.check:
        same = a.out.is_file() and a.out.read_bytes() == data
        print(f"{a.out}: {'matches' if same else 'DIFFERS from'} the re-derivation")
        return 0 if same else 1
    if a.out.is_file() and a.out.read_bytes() != data and not a.force:
        print(f"refused: {a.out} (sha256 {sha256_of(a.out)}) differs from the re-derivation "
              f"(sha256 {hashlib.sha256(data).hexdigest()}); pass --force to replace it",
              file=sys.stderr)
        return 2
    a.out.write_bytes(data)
    print(f"{summary(frozen)}\nsaved → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
