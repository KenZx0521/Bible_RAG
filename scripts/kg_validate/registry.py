"""Gate configuration (baseline, probes), the run Context, and the check registry."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable

from check_identity import Target

from .model import KG, read_jsonl

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EMBEDDING_QUEUE = PROJECT_ROOT / "output" / "embedding_queue.jsonl"
RELATION_SCHEMA = PROJECT_ROOT / "config" / "relations" / "biblical_relations.yaml"

BASELINE_FORMAT = "kg_quality_baseline/v1"
# A split baseline is a directory: index.json (format, description, and the
# part files in merge order) plus one kg_quality_baseline/v1 file per check family.
BASELINE_INDEX = "index.json"
# subset: the value is a list of ids (failing probes) that may only shrink.
DIRECTIONS = {"down", "up", "equal", "none", "subset"}
# target_from "<source>:<key>": a hard target kept in another tracked file.
TARGET_SOURCES = {"step0_sha"}
PROBE_KINDS = {"relation", "mention", "event_anchor", "alias", "xref", "book_region"}


def load_baseline(path: Path) -> dict:
    """The baseline as one document {format, description, checks}. `path` is a
    single file, or a split directory whose parts merge in index order, so a
    split baseline scores exactly like the one file it was split from."""
    path = Path(path)
    if not path.is_dir():
        return _read_doc(path)
    index, parts = _split_parts(path)
    head = {key: value for key, value in index.items() if key != "parts"}
    return {**head, "checks": [check for _, part in parts for check in part["checks"]]}


def save_baseline(path: Path, doc: dict) -> list[Path]:
    """Write `doc` (load_baseline's document, e.g. after apply_ratchet) back to
    where it was read; return the files rewritten. A split directory keeps its
    layout: each check goes back to the part that holds it, and a part whose
    checks did not change is left as it is. index.json is edited by hand."""
    path = Path(path)
    if not path.is_dir():
        _write_doc(path, doc)
        return [path]
    by_id = {check["id"]: check for check in doc["checks"]}
    _, parts = _split_parts(path)
    held = sorted(check["id"] for _, part in parts for check in part["checks"])
    if held != sorted(by_id):
        raise ValueError(f"{path}: its parts hold {held}, not the checks to write {sorted(by_id)}")
    written = []
    for part_path, part in parts:
        checks = [by_id[check["id"]] for check in part["checks"]]
        if checks != part["checks"]:
            _write_doc(part_path, {**part, "checks": checks})
            written.append(part_path)
    return written


def _write_doc(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _split_parts(directory: Path) -> tuple[dict, list[tuple[Path, dict]]]:
    """index.json and its parts in merge order. A layout in which a check could
    drop out of the gate (a part not listed, a listed part missing) or be
    written back twice (one id in two parts) is refused."""
    index_path = directory / BASELINE_INDEX
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("format") != BASELINE_FORMAT:
        raise ValueError(f"{index_path}: expected format {BASELINE_FORMAT}")
    listed = index.get("parts") or []
    present = {p.name for p in directory.glob("*.json")} - {BASELINE_INDEX}
    missing, unlisted = sorted(set(listed) - present), sorted(present - set(listed))
    if missing or unlisted or len(set(listed)) != len(listed):
        raise ValueError(f"{index_path}: parts {listed} do not match the files present "
                         f"(missing {missing}, not listed {unlisted})")
    parts, owner = [], {}
    for name in listed:
        part = _read_doc(directory / name)
        for check in part["checks"]:
            if check["id"] in owner:
                raise ValueError(f"{directory}: check {check['id']} is in both {owner[check['id']]} and {name}")
            owner[check["id"]] = name
        parts.append((directory / name, part))
    return index, parts


def _read_doc(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != BASELINE_FORMAT:
        raise ValueError(f"{path}: expected format {BASELINE_FORMAT}")
    for check in doc["checks"]:
        if check.get("severity") not in ("hard", "record", "warn") or "metrics" not in check:
            raise ValueError(f"{path}: check {check.get('id')} needs a severity and metrics")
        for name, m in check["metrics"].items():
            source = (m.get("target_from") or "").partition(":")[0]
            if m.get("direction") not in DIRECTIONS or (source and source not in TARGET_SOURCES):
                raise ValueError(f"{path}: {check['id']}.{name} has an unknown direction or target_from")
            if "count_of" in m:
                _check_count(path, check, name, m)
    return doc


def _check_count(path: Path, check: dict, name: str, m: dict) -> None:
    """count_of: the metric counts the ids of a subset metric of the same check,
    so its baseline must be exactly len(those ids) (None while they are None)."""
    ids = check["metrics"].get(m["count_of"])
    if ids is None or ids.get("direction") != "subset":
        raise ValueError(f"{path}: {check['id']}.{name} count_of {m['count_of']!r} is not a subset metric")
    expected = None if ids["value"] is None else len(ids["value"])
    if m["value"] != expected:
        raise ValueError(f"{path}: {check['id']}.{name}={m['value']} but {m['count_of']} holds "
                         f"{expected} ids; the count is len(ids)")


def load_probes(path: Path) -> dict:
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    seen = set()
    for fact in doc.get("facts", []):
        if fact.get("kind") not in PROBE_KINDS or fact.get("id") in seen:
            raise ValueError(f"{path}: probe {fact.get('id')!r} has an unknown kind or a duplicate id")
        if fact["kind"] != "book_region" and fact.get("expect") not in ("present", "absent"):
            raise ValueError(f"{path}: probe {fact['id']} needs expect: present|absent")
        seen.add(fact["id"])
    return doc


@dataclass
class Context:
    baseline: dict
    probes: dict
    embedding_queue: Path = DEFAULT_EMBEDDING_QUEUE
    target: Target | None = None
    relation_schema: Path = RELATION_SCHEMA

    def params(self, check_id: str) -> dict:
        spec = next((c for c in self.baseline["checks"] if c["id"] == check_id), {})
        return spec.get("params", {})

    @cached_property
    def texts(self) -> dict[str, str]:
        return {r["id"]: r["text"] for r in read_jsonl(Path(self.embedding_queue))}

    @cached_property
    def verses_of(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for item_id in self.texts:
            if ":v:" in item_id:
                out[item_id.split(":v:")[0]].append(item_id)
        return out

    def body(self, label: str, anchor_id: str) -> str | None:
        """Text after the K0 header (書名 第N章 標題 (…節)：); a chunked pericope
        has no item of its own, so its verses are joined."""
        def strip_header(text: str) -> str:
            return text[text.find("：") + 1:]
        if anchor_id in self.texts:
            return strip_header(self.texts[anchor_id])
        if label == "Pericope" and anchor_id in self.verses_of:
            return "\n".join(strip_header(self.texts[v]) for v in self.verses_of[anchor_id])
        return None

    @cached_property
    def schema(self):
        from relation_extraction.schema_loader import RelationSchema
        return RelationSchema.load(Path(self.relation_schema))


@dataclass
class CheckResult:
    metrics: dict[str, object]
    detail: dict = field(default_factory=dict)
    samples: list = field(default_factory=list)
    error: str | None = None
    # metric -> why None is the expected value here ("*" = every metric), e.g.
    # D1 on a snapshot. A None metric WITHOUT a reason is "unmeasured" and fails
    # the gate: a check that did not run must never read as a pass.
    not_applicable: dict[str, str] = field(default_factory=dict)

    def na_reason(self, name: str) -> str | None:
        return self.not_applicable.get(name) or self.not_applicable.get("*")


CheckFn = Callable[[KG, Context], CheckResult]
CHECKS: dict[str, CheckFn] = {}
NEEDS: dict[str, tuple[str, ...]] = {}  # snapshot files a check reads beyond entities.jsonl
_EXTERNAL: set[str] = set()   # checks that call other stores/processes; their errors are reported, not raised


def check(check_id: str, external: bool = False, needs: tuple[str, ...] = ()):
    def register(fn: CheckFn) -> CheckFn:
        CHECKS[check_id] = fn
        NEEDS[check_id] = needs
        if external:
            _EXTERNAL.add(check_id)
        return fn
    return register


def run_checks(kg: KG, ctx: Context, only: set[str] | None = None) -> dict[str, CheckResult]:
    results = {}
    for check_id, fn in CHECKS.items():
        if only is not None and check_id not in only:
            continue
        lacking = [name for name in NEEDS.get(check_id, ()) if name in kg.missing]
        if lacking:
            results[check_id] = CheckResult({}, not_applicable={"*": f"partial snapshot lacks {', '.join(lacking)}"})
            continue
        try:
            results[check_id] = fn(kg, ctx)
        except Exception as e:  # noqa: BLE001
            if check_id not in _EXTERNAL:
                raise  # a bug in an offline check must fail loudly, not read as "n/a"
            results[check_id] = CheckResult(metrics={}, error=f"{type(e).__name__}: {e}")
    return results
