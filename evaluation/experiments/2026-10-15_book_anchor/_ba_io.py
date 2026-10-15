"""JSON lines, resume keys and the context hash of the book_anchor ablation.

prereg.md in this directory is the only spec (§6 I7, §9, §10). Stdlib only: ba_driver.py
imports it inside the batch container (sys.path[0] = /exp) and the host scripts import it
too. Every line carries a string "kind"; a reader raises BaIoError on any line that is not
a JSON object with one, and on an unterminated last line: run_ba.sh cuts each file back to
its last newline (truncate_to_last_newline) before a resumed run appends to it.

ctx_sha(results, build_blocks) = sha256("\\n\\n".join(build_blocks(results))): in the
container build_blocks is backend utils.generator.build_context_blocks, the function the
prod generator joins with "\\n\\n" (generator._build_context); on the host it is
_ba_export.host_blocks (evaluation/src/context_blocks.format_context_block).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = ["BaIoError", "json_default", "dumps_line", "to_jsonable", "parse_lines", "read_jsonl",
           "truncate_to_last_newline", "done_questions", "gen_key", "latest_gens", "done_gens",
           "context_text", "ctx_sha", "messages_sha", "sha256_bytes", "sha256_file"]

BuildBlocks = Callable[[Sequence[Mapping[str, Any]]], Sequence[str]]
GenKey = tuple[str, str, int]


class BaIoError(ValueError):
    """A JSON-lines file or record that does not follow the experiment's line format."""


def json_default(obj: Any) -> Any:
    """numpy scalars as Python numbers, sets as sorted lists; anything else is refused."""
    if type(obj).__module__ == "numpy" and hasattr(obj, "item"):
        return obj.item()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, default=json_default)


def dumps_line(record: Mapping[str, Any]) -> str:
    """One JSON line (with its newline); the record must carry a string "kind"."""
    if not isinstance(record.get("kind"), str):
        raise BaIoError(f"record without a string 'kind': {sorted(record)[:5]}")
    return _dumps(record) + "\n"


def to_jsonable(obj: Any) -> Any:
    """obj as it reads back from JSON (tuples become lists, numpy scalars numbers)."""
    return json.loads(_dumps(obj))


def parse_lines(text: str, source: str = "<text>") -> list[dict]:
    """Every line as a dict with a string "kind"; a bad, empty or cut line raises."""
    if not text:
        return []
    if not text.endswith("\n"):
        raise BaIoError(f"{source}: the last line has no newline (truncate it first)")
    rows: list[dict] = []
    for number, line in enumerate(text[:-1].split("\n"), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BaIoError(f"{source}: line {number} is not JSON ({exc})") from None
        if not isinstance(row, dict) or not isinstance(row.get("kind"), str):
            raise BaIoError(f"{source}: line {number} is not an object with a string 'kind'")
        rows.append(row)
    return rows


def read_jsonl(path: Path | str, missing_ok: bool = False) -> list[dict]:
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return []
        raise BaIoError(f"{path} does not exist")
    return parse_lines(path.read_text(encoding="utf-8"), str(path))


def truncate_to_last_newline(path: Path | str) -> int:
    """Cut the file back to its last newline; the number of bytes removed (0: nothing cut)."""
    path = Path(path)
    if not path.exists():
        return 0
    data = path.read_bytes()
    keep = data.rfind(b"\n") + 1
    if keep == len(data):
        return 0
    with open(path, "r+b") as handle:
        handle.truncate(keep)
    return len(data) - keep


def done_questions(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Resume key of retrieval.jsonl: the qids that already have a "q" record."""
    return {row["qid"] for row in rows if row.get("kind") == "q"}


def gen_key(row: Mapping[str, Any]) -> GenKey:
    return (str(row["qid"]), str(row["arm"]), int(row["rep"]))


def latest_gens(rows: Iterable[Mapping[str, Any]]) -> dict[GenKey, dict]:
    """The last "gen" record of every (qid, arm, rep): a later run's line supersedes."""
    latest: dict[GenKey, dict] = {}
    for row in rows:
        if row.get("kind") == "gen":
            latest[gen_key(row)] = dict(row)
    return latest


def done_gens(rows: Iterable[Mapping[str, Any]], retry_failed: bool = False) -> set[GenKey]:
    """Resume key of gen.jsonl; with retry_failed a key whose latest record failed is not done."""
    return {key for key, row in latest_gens(rows).items() if row.get("ok") or not retry_failed}


def context_text(results: Sequence[Mapping[str, Any]], build_blocks: BuildBlocks) -> str:
    """The generator's context string: its blocks joined by a blank line."""
    return "\n\n".join(build_blocks(results))


def ctx_sha(results: Sequence[Mapping[str, Any]], build_blocks: BuildBlocks) -> str:
    return sha256_bytes(context_text(results, build_blocks).encode("utf-8"))


def messages_sha(messages: Sequence[Mapping[str, Any]]) -> str:
    """sha256 of the chat messages as canonical JSON (keys sorted, no spaces)."""
    canonical = json.dumps(list(messages), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())
