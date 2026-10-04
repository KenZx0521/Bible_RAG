"""
Staged Step 1: NER half / frozen grounded half / merge (plan M6).

Phase 4 LLM verdicts have no per-candidate cache, so the grounded
Event/Object/Theme half of entities.jsonl is frozen once and rebuilds only
re-run NER (--stage ner) before merging the two halves again.

The monolithic writer (extract_entities.save_entities/save_mentions) emits NER
mentions first and sorts entities with entity_sort_key(); with disjoint types
per half that only interleaves whole type blocks, so merge(split(build)) ==
build byte for byte. Everything here works on raw lines and never
re-serialises a record.

Both halves carry a manifest (frozen/grounded_manifest.json,
ner_manifest.json) so that a partial, sampled, wiped, edited or stale half is
refused (or overridden with --force) instead of silently becoming the input
of every later rebuild.
"""

import hashlib
import json
import logging
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .models import EntityType

logger = logging.getLogger(__name__)

# Types each half of Step 1 can emit. NERExtractor maps dictionary hits and
# CKIP labels only onto NER_TYPES; _candidates_to_entities() keeps only
# GROUNDED_TYPES. normalize_and_merge() merges strictly within a type, so the
# halves never interact and can be produced, frozen and merged separately.
NER_TYPES = frozenset({EntityType.PERSON, EntityType.PLACE, EntityType.GROUP})
GROUNDED_TYPES = frozenset({EntityType.EVENT, EntityType.OBJECT, EntityType.THEME})
_IS_GROUNDED_TYPE = {t.value: t in GROUNDED_TYPES for t in NER_TYPES | GROUNDED_TYPES}

ENTITIES_FILE = "entities.jsonl"
MENTIONS_FILE = "entity_mentions.jsonl"
NER_ENTITIES_FILE = "ner_entities.jsonl"
NER_MENTIONS_FILE = "ner_mentions.jsonl"
GROUNDED_ENTITIES_FILE = "grounded_entities.jsonl"
GROUNDED_MENTIONS_FILE = "grounded_mentions.jsonl"
# Prefixed, not plain manifest.json: output/frozen/ is shared with other
# frozen caches (e.g. descriptions) that may carry manifests of their own.
GROUNDED_MANIFEST_FILE = "grounded_manifest.json"
# Next to ner_*.jsonl. A sampled or hand-made NER half lands in the same
# canonical files as a full --stage ner; without provenance, merge would
# silently make it the Person/Place/Group half of every later rebuild.
NER_MANIFEST_FILE = "ner_manifest.json"

# How far a re-freeze may move the grounded half's line counts against the
# snapshot it replaces. A Phase 4 re-run is not deterministic, so a small move
# is expected; a large one means the source build is partial or wiped
# (--sample, --phase, --ner-only --force) and would replace the only LLM-free
# copy of Phase 4 with a fragment.
GROUNDED_DRIFT_TOLERANCE = 0.05


def entity_sort_key(type_value: str, mention_count: int) -> Tuple[str, int]:
    """Order of entities.jsonl: by type name, then most-mentioned first.

    Ties keep their incoming order (sorted() is stable); merge relies on that
    to reproduce the monolithic file byte-for-byte.
    """
    return (type_value, -mention_count)


class StageError(Exception):
    """A staged Step 1 run refused to proceed; the message says what to do."""


@dataclass(frozen=True)
class Halves:
    """Raw lines of one build, split by the extractor that produced them."""
    ner_entities: Tuple[bytes, ...]
    ner_mentions: Tuple[bytes, ...]
    grounded_entities: Tuple[bytes, ...]
    grounded_mentions: Tuple[bytes, ...]


def read_jsonl_lines(path: Path) -> List[bytes]:
    """Raw newline-terminated lines, split on b"\\n" only: str.splitlines()
    also breaks on U+2028, which json.dumps(ensure_ascii=False) leaves raw."""
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise StageError(f"{path}: last line is not newline-terminated (truncated?)")
    return [line + b"\n" for line in data.split(b"\n")[:-1]]


def _parse_record(line: bytes, label: str, lineno: int) -> dict:
    try:
        return json.loads(line)
    except ValueError as e:
        raise StageError(f"{label} line {lineno} is not valid JSON: {e}") from e


def _is_grounded(record: dict, label: str, lineno: int) -> bool:
    """An entity's half, by its type field: ids are opaque keys rather than
    type tags, and a type neither extractor emits must not default to NER."""
    if record.get("type") not in _IS_GROUNDED_TYPE:
        raise StageError(f"{label} line {lineno}: unknown entity type {record.get('type')!r}")
    return _IS_GROUNDED_TYPE[record["type"]]


def split_halves(entity_lines: List[bytes], mention_lines: List[bytes]) -> Halves:
    """Split a build into NER and grounded halves, keeping line order. A mention
    goes with its entity; repeated ids or dangling mentions are refused."""
    grounded_ids: Dict[str, bool] = {}
    halves: Dict[bool, Tuple[List[bytes], List[bytes]]] = {False: ([], []), True: ([], [])}
    for lineno, line in enumerate(entity_lines, 1):
        record = _parse_record(line, "entities", lineno)
        entity_id = record.get("entity_id")
        if entity_id in grounded_ids:
            raise StageError(f"entities line {lineno}: duplicate entity_id {entity_id!r}")
        grounded_ids[entity_id] = _is_grounded(record, "entities", lineno)
        halves[grounded_ids[entity_id]][0].append(line)
    for lineno, line in enumerate(mention_lines, 1):
        entity_id = _parse_record(line, "entity_mentions", lineno).get("entity_id")
        if entity_id not in grounded_ids:
            raise StageError(f"entity_mentions line {lineno}: entity_id "
                             f"{entity_id!r} is not in entities")
        halves[grounded_ids[entity_id]][1].append(line)
    (ner_e, ner_m), (grd_e, grd_m) = halves[False], halves[True]
    return Halves(tuple(ner_e), tuple(ner_m), tuple(grd_e), tuple(grd_m))


def merge_halves(halves: Halves) -> Tuple[List[bytes], List[bytes]]:
    """Rebuild lines as the monolithic writer does: entities stably sorted by
    entity_sort_key() over NER-then-grounded, mentions NER-then-grounded.

    Re-splitting must give the same halves back. That refuses a file in the
    wrong slot and an id in both halves, which normalize_and_merge() resolves
    (NER wins, counts add, renormalise) in a way serialised output can't replay.
    """
    entity_lines = [*halves.ner_entities, *halves.grounded_entities]
    mention_lines = [*halves.ner_mentions, *halves.grounded_mentions]
    try:
        resplit = split_halves(entity_lines, mention_lines)
    except StageError as e:
        raise StageError(f"cannot merge (lines numbered NER half first): {e}") from e
    if resplit != halves:
        raise StageError("cannot merge: a half holds lines of the other half's "
                         "types (wrong file passed?)")
    records = [json.loads(line) for line in entity_lines]
    order = sorted(range(len(records)), key=lambda i: entity_sort_key(
        records[i]["type"], records[i].get("mention_count", 0)))
    return [entity_lines[i] for i in order], mention_lines


def _digest(lines) -> Dict:
    return {"sha256": hashlib.sha256(b"".join(lines)).hexdigest(), "lines": len(lines)}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace path in one step so a crash never leaves a truncated file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _git_state() -> Tuple[Optional[str], Optional[bool]]:
    """HEAD commit and whether tracked files differ from it (None outside git)."""
    def git(*cmd: str) -> str:
        return subprocess.run(["git", *cmd], cwd=Path(__file__).resolve().parent,
                              capture_output=True, text=True, check=True).stdout
    try:
        return (git("rev-parse", "HEAD").strip(),
                bool(git("status", "--porcelain", "--untracked-files=no").strip()))
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _provenance() -> Dict:
    git_commit, git_dirty = _git_state()
    return {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit, "git_dirty": git_dirty}


def _write_manifest(path: Path, manifest: Dict) -> None:
    _write_atomic(path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                  .encode("utf-8"))


def _load_manifest(path: Path) -> Dict:
    """A damaged manifest is a clean refusal naming the file, not a traceback."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StageError(f"{path} is unreadable ({e})") from e
    if not isinstance(manifest, dict):
        raise StageError(f"{path} is unreadable (not a JSON object)")
    return manifest


# Valid JSON of the wrong shape (hand edits, partial restores) must be the
# same clean refusal as broken JSON: a stray AttributeError/TypeError escapes
# _guard(), so not even --force would get past it.

def _is_digest(value: object) -> bool:
    """A {sha256, lines} record as _digest() writes it."""
    return (isinstance(value, dict) and isinstance(value.get("sha256"), str)
            and type(value.get("lines")) is int and value["lines"] >= 0)


def _require(path: Path, ok: bool, what: str) -> None:
    if not ok:
        raise StageError(f"{path} is unreadable ({what})")


def _require_digests(path: Path, manifest: Dict, names: Tuple[str, ...]) -> Dict:
    """manifest["files"], checked to hold a digest record for each name."""
    files = manifest.get("files")
    _require(path, isinstance(files, dict), "'files' is not an object")
    for name in names:
        _require(path, _is_digest(files.get(name)),
                 f"files[{name!r}] is not a sha256/line-count record")
    return files


def _load_grounded_manifest(path: Path) -> Dict:
    """grounded_manifest.json with every field merge reads shape-checked."""
    manifest = _load_manifest(path)
    _require_digests(path, manifest, (GROUNDED_ENTITIES_FILE, GROUNDED_MENTIONS_FILE))
    ner_half = manifest.get("ner_half")
    if ner_half is None:    # optional: only feeds the NER-drift report
        return manifest
    _require(path, isinstance(ner_half, dict), "'ner_half' is not an object")
    for key in ("entities", "mentions"):
        _require(path, ner_half.get(key) is None or _is_digest(ner_half[key]),
                 f"ner_half[{key!r}] is not a sha256/line-count record")
    counts = ner_half.get("type_counts")
    counts_ok = counts is None or (isinstance(counts, dict)
                                   and all(type(n) is int for n in counts.values()))
    _require(path, counts_ok, "ner_half['type_counts'] is not an object of counts")
    return manifest


def _type_counts(entity_lines) -> Dict[str, int]:
    return dict(sorted(Counter(json.loads(line)["type"] for line in entity_lines).items()))


def _count_change(label: str, before: Optional[int], after: int) -> str:
    if before is None:
        return f"{label} ? -> {after:,}"
    return f"{label} {before:,} -> {after:,} ({after - before:+,})"


def _replaced_counts(frozen_dir: Path) -> Optional[Dict[str, int]]:
    """Grounded line counts of the snapshot a re-freeze would replace.

    None when there is none. The manifest is written last, so a first freeze
    that crashed midway, or a restore that left the manifest out, leaves frozen
    files without one; their own line counts then stand in, or a plain --force
    would replace the only copy of Phase 4 unchecked.
    """
    paths = {"entities": frozen_dir / GROUNDED_ENTITIES_FILE,
             "mentions": frozen_dir / GROUNDED_MENTIONS_FILE}
    manifest_path = frozen_dir / GROUNDED_MANIFEST_FILE
    if manifest_path.exists():
        files = _require_digests(manifest_path, _load_manifest(manifest_path),
                                 tuple(p.name for p in paths.values()))
        return {key: files[path.name]["lines"] for key, path in paths.items()}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if len(missing) == len(paths):
        return None
    if missing:
        raise StageError(f"{manifest_path} and {', '.join(missing)} not found")
    logger.warning(f"{manifest_path} not found; checking drift against the line counts "
                   f"of the frozen files it would replace")
    return {key: len(read_jsonl_lines(path)) for key, path in paths.items()}


def _check_grounded_plausible(halves: Halves, frozen_dir: Path, force: bool,
                              accept_drift: bool) -> None:
    """Refuse to freeze a grounded half that looks partial or wiped.

    A full build always has all three grounded types, so a missing one (or an
    empty half) needs --force. Re-freezing already needs --force to overwrite,
    so drift against the snapshot being replaced has its own override, or a
    plain --force would wave a wiped half straight through.
    """
    present = _type_counts(halves.grounded_entities)
    missing = sorted(t.value for t in GROUNDED_TYPES if t.value not in present)
    if missing:
        what = "is empty" if not present else f"has no {', '.join(missing)} entities"
        if not force:
            raise StageError(f"the grounded half {what}: the source build looks partial or "
                             f"wiped (--ner-only --force, --phase, --sample). Pass --force "
                             f"to freeze it anyway.")
        logger.warning(f"--force: freezing although the grounded half {what}")

    if accept_drift:
        return
    try:
        before = _replaced_counts(frozen_dir)
    except StageError as e:
        raise StageError(f"cannot compare against the snapshot being replaced ({e}); "
                         f"pass --accept-grounded-drift to replace it unchecked") from e
    if before is None:
        return
    after = {"entities": len(halves.grounded_entities),
             "mentions": len(halves.grounded_mentions)}
    drifted = [_count_change(k, before[k], after[k]) for k in after
               if abs(after[k] - before[k]) > GROUNDED_DRIFT_TOLERANCE * max(before[k], 1)]
    if drifted:
        raise StageError(f"the grounded half moved more than {GROUNDED_DRIFT_TOLERANCE:.0%} "
                         f"against the snapshot it would replace ({', '.join(drifted)}); "
                         f"a partial or wiped source would overwrite the only copy of the "
                         f"Phase 4 output. Pass --accept-grounded-drift if this is intended.")


def freeze_grounded(entities_path: Path, mentions_path: Path, frozen_dir: Path,
                    force: bool = False, dry_run: bool = False,
                    accept_drift: bool = False) -> Dict:
    """Freeze the grounded (Event/Object/Theme) half of an existing build.

    Phase 4 has no per-candidate cache, so this is the only LLM-free rebuild
    source: never replaced without force, written only once it round-trips
    and looks complete (_check_grounded_plausible).
    """
    for path in (entities_path, mentions_path):
        if not path.exists():
            raise StageError(f"{path} not found; nothing to freeze")
    names = (GROUNDED_ENTITIES_FILE, GROUNDED_MENTIONS_FILE, GROUNDED_MANIFEST_FILE)
    existing = [str(frozen_dir / n) for n in names if (frozen_dir / n).exists()]
    if existing and not force:
        raise StageError(f"frozen grounded snapshot already exists ({', '.join(existing)}); "
                         f"it may be the only copy of the Phase 4 LLM output. "
                         f"Pass --force to overwrite it.")

    entity_lines = read_jsonl_lines(entities_path)
    mention_lines = read_jsonl_lines(mentions_path)
    halves = split_halves(entity_lines, mention_lines)
    merged = merge_halves(halves)
    if merged != (entity_lines, mention_lines):
        which = entities_path if merged[0] != entity_lines else mentions_path
        raise StageError(f"{which}: split->merge round-trip differs from the source; it "
                         f"lacks the layout extract_entities writes (NER mentions first, "
                         f"entities sorted by type then mention_count)")
    _check_grounded_plausible(halves, frozen_dir, force, accept_drift)

    manifest = {
        **_provenance(),
        "grounded_types": sorted(t.value for t in GROUNDED_TYPES),
        "source": {
            "entities": {"path": str(entities_path), **_digest(entity_lines)},
            "entity_mentions": {"path": str(mentions_path), **_digest(mention_lines)},
        },
        "files": {GROUNDED_ENTITIES_FILE: _digest(halves.grounded_entities),
                  GROUNDED_MENTIONS_FILE: _digest(halves.grounded_mentions)},
        # Not frozen (NER is re-run); compare a fresh ner_*.jsonl against it
        # to see whether NER reproduced the build this snapshot came from.
        "ner_half": {"entities": _digest(halves.ner_entities),
                     "mentions": _digest(halves.ner_mentions),
                     "type_counts": _type_counts(halves.ner_entities)},
    }
    logger.info(f"Grounded half: {len(halves.grounded_entities)} entities, "
                f"{len(halves.grounded_mentions)} mentions (round-trip verified)")
    if dry_run:
        logger.info(f"[dry-run] Would write {', '.join(names)} to {frozen_dir}")
        return manifest

    if existing:
        logger.warning(f"Overwriting frozen grounded snapshot in {frozen_dir} (--force)")
    frozen_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(frozen_dir / GROUNDED_ENTITIES_FILE, b"".join(halves.grounded_entities))
    _write_atomic(frozen_dir / GROUNDED_MENTIONS_FILE, b"".join(halves.grounded_mentions))
    # Manifest last: merge refuses a snapshot without one, so a crash midway
    # cannot leave a partial snapshot that looks valid.
    _write_manifest(frozen_dir / GROUNDED_MANIFEST_FILE, manifest)
    logger.info(f"Froze grounded half to {frozen_dir}")
    return manifest


def write_ner_manifest(output_dir: Path, input_path: Path, sample: Optional[int],
                       input_sha256: Optional[str] = None) -> Dict:
    """Record where ner_*.jsonl came from; --stage ner writes it last.

    `sample` is what --sample was given; a falsy value means the whole queue
    (extract_ner_half() truncates only on a truthy sample). `input_sha256` is
    the queue's digest taken before NER started: hashing after the ~30-minute
    run would vouch for a queue rewritten mid-run that NER never read.
    """
    manifest = {
        **_provenance(),
        "sampled": bool(sample),
        "sample": sample or None,
        "input": {"path": str(input_path),
                  "sha256": input_sha256 or file_sha256(input_path)},
        "files": {name: _digest(read_jsonl_lines(output_dir / name))
                  for name in (NER_ENTITIES_FILE, NER_MENTIONS_FILE)},
    }
    _write_manifest(output_dir / NER_MANIFEST_FILE, manifest)
    logger.info(f"Wrote {output_dir / NER_MANIFEST_FILE}")
    return manifest


def _read_frozen(frozen_dir: Path, name: str, manifest: Dict) -> Tuple[bytes, ...]:
    """Read one frozen file, refusing it if it no longer matches the manifest
    (shape-checked by _load_grounded_manifest)."""
    path = frozen_dir / name
    if not path.exists():
        raise StageError(f"{path} not found; run --stage freeze-grounded first")
    lines = read_jsonl_lines(path)
    if _digest(lines) != manifest["files"][name]:
        raise StageError(f"{path} does not match its sha256/line count in "
                         f"{GROUNDED_MANIFEST_FILE} (modified or partially copied)")
    return tuple(lines)


def _queue_problem(manifest: Dict, queue_path: Path) -> Optional[str]:
    """ner_*.jsonl are stale once the embedding queue they came from changes
    (e.g. Step 0 re-run): the rebuild chain only re-runs merge, and a stale
    half that still equals the frozen build's is invisible to _ner_change()."""
    record = manifest.get("input")
    recorded = record.get("sha256") if isinstance(record, dict) else None
    if not isinstance(recorded, str):
        return f"{NER_MANIFEST_FILE} does not record the embedding queue NER read"
    if not queue_path.exists():
        return (f"{queue_path} not found, so the NER half cannot be checked against the "
                f"current embedding queue (pass it with -i)")
    current = file_sha256(queue_path)
    if current != recorded:
        return (f"ner_*.jsonl were extracted from a different embedding queue than "
                f"{queue_path} (sha256 {recorded[:12]}... recorded, {current[:12]}... now)")
    return None


def _ner_provenance_problems(output_dir: Path, ner: Tuple[Tuple[bytes, ...], ...],
                             queue_path: Path) -> List[str]:
    path = output_dir / NER_MANIFEST_FILE
    if not path.exists():
        return [f"{path} not found: ner_*.jsonl were not written by --stage ner "
                f"(or predate it), so their source is unknown"]
    try:
        manifest = _load_manifest(path)
        files = _require_digests(path, manifest, (NER_ENTITIES_FILE, NER_MENTIONS_FILE))
    except StageError as e:
        return [str(e)]
    problems = []
    sampled = manifest.get("sampled")
    if sampled is True:
        problems.append(f"ner_*.jsonl come from a sampled run (--sample "
                        f"{manifest.get('sample')}) and hold only part of the NER half")
    elif sampled is not False:
        # Only an explicit false vouches for the whole queue: unknown is not full.
        problems.append(f"{NER_MANIFEST_FILE} does not say whether the run was sampled "
                        f"(sampled={sampled!r}), so ner_*.jsonl may hold only part of "
                        f"the NER half")
    for name, lines in zip((NER_ENTITIES_FILE, NER_MENTIONS_FILE), ner):
        if _digest(lines) != files[name]:
            problems.append(f"{name} does not match its sha256/line count in "
                            f"{NER_MANIFEST_FILE} (changed after --stage ner)")
    queue_problem = _queue_problem(manifest, queue_path)
    if queue_problem:
        problems.append(queue_problem)
    return problems


def _check_ner_provenance(output_dir: Path, ner: Tuple[Tuple[bytes, ...], ...],
                          queue_path: Path) -> None:
    """Refuse an NER half that --stage ner did not write in full, as is, from
    the current embedding queue."""
    problems = _ner_provenance_problems(output_dir, ner, queue_path)
    if problems:
        raise StageError("refusing this NER half: " + "; ".join(problems) + ". Re-run "
                         "--stage ner on the current queue without --sample, or pass "
                         "--force to merge it anyway.")


def _check_grounded_guards(entities_path: Path, frozen_entities: Tuple[bytes, ...]) -> None:
    """Refuse a merge that would drop or blank a grounded half.

    No early exit on an empty half on either side: an empty snapshot writes a
    build with no Event/Object/Theme, and a current build without them was
    wiped (--ner-only --force, a partial run) and deserves a look first.
    """
    if not frozen_entities:
        raise StageError("the frozen grounded snapshot is empty; merging would write a build "
                         "with no Event/Object/Theme. Re-freeze from a full build, or pass "
                         "--force.")
    if not entities_path.exists():
        return
    current = tuple(line for i, line in enumerate(read_jsonl_lines(entities_path), 1)
                    if _is_grounded(_parse_record(line, "entities", i), "entities", i))
    if not current:
        raise StageError(f"{entities_path} has no Event/Object/Theme entities although the "
                         f"frozen snapshot has {len(frozen_entities):,}; it was likely wiped "
                         f"by --ner-only --force or a partial run. Check how, then pass "
                         f"--force to restore the frozen half.")
    if current != frozen_entities:
        raise StageError(f"{entities_path} holds a grounded half that differs from the "
                         f"frozen snapshot; merging would discard it. Run --stage "
                         f"freeze-grounded --force first, or pass --force to overwrite.")


def _ner_change(ner: Tuple[Tuple[bytes, ...], ...], frozen_ner: Dict) -> Optional[str]:
    """None if the NER half equals the frozen build's, else a count summary."""
    now = {"entities": _digest(ner[0]), "mentions": _digest(ner[1])}
    if all(now[k] == frozen_ner.get(k) for k in now):
        return None
    totals = ", ".join(_count_change(k, (frozen_ner.get(k) or {}).get("lines"),
                                     now[k]["lines"]) for k in now)
    before, after = frozen_ner.get("type_counts"), _type_counts(ner[0])
    if before is None:
        return f"{totals}; per-type counts not in the manifest"
    by_type = [_count_change(t, before.get(t, 0), after.get(t, 0))
               for t in sorted(set(before) | set(after)) if before.get(t, 0) != after.get(t, 0)]
    return f"{totals}; " + (f"by type: {', '.join(by_type)}" if by_type
                            else "same type counts, different content")


def _guard(check: Callable[..., None], force: bool, *args) -> None:
    """Run a refusal check; under --force log what was overridden instead."""
    try:
        check(*args)
    except StageError as e:
        if not force:
            raise
        logger.warning(f"--force: proceeding although {e}")


def merge_stage(output_dir: Path, frozen_dir: Path, queue_path: Path, force: bool = False,
                dry_run: bool = False) -> Dict:
    """Write entities.jsonl / entity_mentions.jsonl from ner_*.jsonl + frozen half.

    queue_path is the current embedding queue; ner_manifest.json must name it
    (by sha256) as the input of --stage ner. Structural problems (unverifiable
    snapshot, a half in the wrong slot) always refuse; provenance and grounded
    guards yield to --force.
    """
    ner_paths = (output_dir / NER_ENTITIES_FILE, output_dir / NER_MENTIONS_FILE)
    for path in ner_paths:
        if not path.exists():
            raise StageError(f"{path} not found; run --stage ner first")
    manifest_path = frozen_dir / GROUNDED_MANIFEST_FILE
    if not manifest_path.exists():
        raise StageError(f"{manifest_path} not found; run --stage freeze-grounded first")
    manifest = _load_grounded_manifest(manifest_path)

    frozen = (_read_frozen(frozen_dir, GROUNDED_ENTITIES_FILE, manifest),
              _read_frozen(frozen_dir, GROUNDED_MENTIONS_FILE, manifest))
    ner = tuple(tuple(read_jsonl_lines(p)) for p in ner_paths)
    entity_lines, mention_lines = merge_halves(Halves(*ner, *frozen))
    entities_path, mentions_path = output_dir / ENTITIES_FILE, output_dir / MENTIONS_FILE
    _guard(_check_ner_provenance, force, output_dir, ner, queue_path)
    _guard(_check_grounded_guards, force, entities_path, frozen[0])

    logger.info(f"Merged {len(ner[0])} NER + {len(frozen[0])} grounded entities, "
                f"{len(ner[1])} + {len(frozen[1])} mentions")
    # Not a refusal: 1C changes NER on purpose. Loud, so an accidental change
    # (stale or partial NER half) cannot hide in an INFO line.
    change = _ner_change(ner, manifest.get("ner_half") or {})
    if change:
        logger.warning(f"NER half differs from the frozen build's: {change}")
    else:
        logger.info("NER half identical to the frozen build's")
    ner_reproduced = change is None
    if dry_run:
        logger.info(f"[dry-run] Would write {entities_path} and {mentions_path}")
    else:
        _write_atomic(entities_path, b"".join(entity_lines))
        _write_atomic(mentions_path, b"".join(mention_lines))
        logger.info(f"Saved {entities_path} and {mentions_path}")
    return {"entities": len(entity_lines), "mentions": len(mention_lines),
            "ner_reproduced": ner_reproduced}
