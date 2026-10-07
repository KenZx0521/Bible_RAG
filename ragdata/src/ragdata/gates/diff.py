"""G-DIFF: the text layer's differences to the corpora it replaces are all explained.

Build-time gate (it needs bible_md and canonical_full, which a stored layer
does not). Hard conditions: no difference is classified ``other`` in either
diff; canonical_full and the layer cover the same records; and the numbers the
audit measured (REPORT G01/G02: 268 verses / 4,446 characters lost, 116
superscriptions, 10 ghost verses …) are reproduced exactly. The expectations
live in ``expectations/diff_expect.yaml`` as dotted paths into each summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from ragdata.contract.counts import CountsError
from ragdata.gates.base import GateResult, capped

NAME = "G-DIFF"
SCHEMA = "ragdata.diff_expect.v1"
REFERENCES = ("bible_md", "canonical_full")
EXPECT_PATH = Path(__file__).resolve().parents[1] / "contract" / "expectations" / \
    "diff_expect.yaml"
_MISSING = object()


class DiffExpectError(CountsError):
    """The diff expectation file is malformed."""


def load_expect(path: Path | str = EXPECT_PATH) -> dict[str, dict[str, int]]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DiffExpectError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise DiffExpectError(f"{path}: schema must be {SCHEMA}")
    sections = {k: v for k, v in doc.items() if k != "schema"}
    if not set(sections) <= set(REFERENCES):
        unknown = sorted(set(sections) - set(REFERENCES))
        raise DiffExpectError(f"{path}: unknown references {unknown}")
    for ref, values in sections.items():
        if not isinstance(values, dict) or not all(
                isinstance(v, int) and not isinstance(v, bool) for v in values.values()):
            raise DiffExpectError(f"{path}: {ref} must map metric paths to integers")
    return {ref: dict(values) for ref, values in sections.items()}


def metric(summary: Mapping[str, Any], path: str, default: Any = _MISSING) -> Any:
    """The value at a dotted ``path`` of a summary, or ``default`` when there is none."""
    node: Any = summary
    for step in path.split("."):
        if not isinstance(node, Mapping) or step not in node:
            return default
        node = node[step]
    return node


def _other(summary: Mapping[str, Any]) -> int:
    value = summary["by_class"]["other"]
    return value["rows"] if isinstance(value, Mapping) else value


def check_diff(summaries: Mapping[str, Mapping[str, Any]],
               expect: Mapping[str, Mapping[str, int]]) -> GateResult:
    details = [f"{ref}: {_other(s)} differences classified other"
               for ref, s in summaries.items() if _other(s)]
    canonical = summaries["canonical_full"]
    if canonical["records_compared"] != canonical["layer_records"]:
        details.append(f"canonical_full: records_compared {canonical['records_compared']}, "
                       f"layer records {canonical['layer_records']}")
    observed: dict[str, dict[str, Any]] = {}
    for ref, values in expect.items():
        observed[ref] = {}
        for path, value in values.items():
            got = metric(summaries[ref], path)
            if got is _MISSING:
                details.append(f"{ref}: {path}: no such metric in the summary")
                continue
            observed[ref][path] = got
            if got != value:
                details.append(f"{ref}: {path}: observed {got}, expected {value}")
    return GateResult(NAME, True, not details, observed,
                      {ref: dict(v) for ref, v in expect.items()}, capped(details))
