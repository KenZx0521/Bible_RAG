"""G-EMB (design §6, §8): the emb layer is S6 of its struct and text layers, under a
declared template, and its vectors are one unit row per record.

Checked against the text and struct records the layer was built on (the snapshot
holds all three layers):

- formula: one verse record per unit (merged units once, omitted slots never),
  one passage record per unchunked passage, one chunk record per chunk — no
  more, no fewer; passage and chunk token counts are those S5 counted;
- template: ``emb_report.json`` declares a known template exactly as built, and
  every record names it; the whole report is what S6 writes for these records
  and the layers the emb layer was built on;
- records: every record is what S6 derives from the layers (text, hashes, token
  and <unk> counts under the pinned tokenizer, point id, payload), in file order;
- vectors (the attachment): one finite unit row per record, and the index names
  each row's record, text sha and float32 sha.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ragdata.contract import record_to_dict
from ragdata.gates.base import GateResult, Snapshot, capped
from ragdata.stages.errors import StageError
from ragdata.stages.s06_emb import records as s6
from ragdata.stages.s06_emb.template import TEMPLATES, Template
from ragdata.store.vectors import row_sha

NAME = "G-EMB"
NORM_TOLERANCE = 1e-3


@dataclass(frozen=True)
class EmbFiles:
    """What G-EMB reads of an emb layer besides its records."""

    report: Mapping[str, Any]                 # emb_report.json
    vectors: np.ndarray | None                # the attachment's matrix (None: missing)
    index: Sequence[Mapping[str, Any]]        # vector_index.jsonl rows
    depends_on: Mapping[str, str]             # the struct and text versions it was built on
    vectors_error: str | None = None          # why the attachment could not be read


def _set_diff(what: str, want: set[str], got: Sequence[str]) -> list[str]:
    dup = sorted(k for k, n in Counter(got).items() if n > 1)
    return ([f"{what}: no record for {k}" for k in sorted(want - set(got))]
            + [f"{what}: {k} is not to be embedded" for k in sorted(set(got) - want)]
            + [f"{what}: {k} embedded twice" for k in dup])


def _formula(snapshot: Snapshot, recs: Sequence[Any]) -> tuple[dict[str, int], list[str]]:
    units = {u.unit_key for u in snapshot.of("verse_units")}
    passages = {p.passage_id: p for p in snapshot.of("passages")}
    unchunked = {k for k, p in passages.items() if not p.requires_chunking}
    chunks = {c.chunk_id: c for c in snapshot.of("chunks")}
    by_kind = {kind: [r.source_id for r in recs if r.kind == kind] for kind in s6.KINDS}
    out = (_set_diff("verse", units, by_kind["verse"])
           + _set_diff("passage", unchunked, by_kind["passage"])
           + _set_diff("chunk", set(chunks), by_kind["chunk"]))
    struct_tokens = {**{k: p.token_count for k, p in passages.items()},
                     **{k: c.token_count for k, c in chunks.items()}}
    out += [f"{r.record_id}: {r.token_count} tokens, S5 counted {struct_tokens[r.source_id]}"
            for r in recs if r.kind != "verse" and r.source_id in struct_tokens
            and r.token_count != struct_tokens[r.source_id]]
    return {"units": len(units), "unchunked_passages": len(unchunked), "chunks": len(chunks)}, out


def _template(report: Mapping[str, Any], recs: Sequence[Any]) -> tuple[Template | None, list[str]]:
    declared = report.get("template") if isinstance(report, Mapping) else None
    tid = declared.get("template_id") if isinstance(declared, Mapping) else None
    if tid not in TEMPLATES:
        return None, [f"emb_report.json declares no known template ({tid!r})"]
    out = [] if declared == TEMPLATES[tid].declaration() else \
        [f"the declared {tid} template is not {tid} as S6 renders it"]
    out += [f"{r.record_id}: template {r.template_id}, declared {tid}"
            for r in recs if r.template_id != tid]
    return TEMPLATES[tid], out


def _report(files: EmbFiles, template: Template, recs: Sequence[Any]) -> list[str]:
    want = s6.emb_report(files.depends_on.get("struct"), files.depends_on.get("text"), template,
                         [record_to_dict(r) for r in recs])
    got = dict(files.report)
    return [f"emb_report.json {k}: {got.get(k)!r}, expected {want.get(k)!r}"
            for k in sorted(set(want) | set(got)) if got.get(k) != want.get(k)]


def _field_diff(want: Mapping[str, Any], got: Mapping[str, Any]) -> list[str]:
    keys = sorted(set(want) | set(got))
    top = [k for k in keys if k != "payload" and want.get(k) != got.get(k)]
    payload_w, payload_g = want.get("payload", {}), got.get("payload", {})
    sub = [f"payload.{k}" for k in sorted(set(payload_w) | set(payload_g))
           if payload_w.get(k) != payload_g.get(k)]
    return top + sub


def _derived(snapshot: Snapshot, template: Template, stats: s6.TokenStats,
             recs: Sequence[Any]) -> list[str]:
    try:
        expected = s6.emb_records(snapshot, template, stats)
    except StageError as exc:
        return [f"S6 cannot derive the records from these layers: {exc}"]
    actual = {r.record_id: record_to_dict(r) for r in recs}
    want = {r["record_id"]: r for r in expected}
    out = [f"{rid}: differs in {', '.join(_field_diff(want[rid], actual[rid]))}"
           for rid in want if rid in actual and want[rid] != actual[rid]]
    if [r["record_id"] for r in expected] != [r.record_id for r in recs] and set(want) == set(actual):
        out.append("records are not in S6 file order")
    return out


def _index_violations(got: Sequence[Mapping[str, Any]], want: Sequence[Mapping[str, Any]]
                      ) -> list[str]:
    if len(got) != len(want):
        return [f"vector_index has {len(got)} rows for {len(want)} records"]
    return [f"vector_index row {i}: {g} is not {w}"
            for i, (g, w) in enumerate(zip(got, want)) if g != w][:10]


def _vectors(recs: Sequence[Any], files: EmbFiles) -> tuple[dict[str, Any], list[str]]:
    m = files.vectors
    if m is None:
        return {"rows": None}, [f"no vectors: {files.vectors_error or 'attachment missing'}"]
    if m.ndim != 2 or m.shape[0] != len(recs):
        return {"rows": int(m.shape[0])}, [f"vectors {m.shape} are not one row per record "
                                            f"({len(recs)})"]
    want = [{"record_id": r.record_id, "row": i, "text_sha": r.text_sha, "vec_sha": row_sha(m[i])}
            for i, r in enumerate(recs)]
    out = _index_violations([dict(row) for row in files.index], want)
    norms = np.linalg.norm(m.astype(np.float64), axis=1)
    bad = np.flatnonzero(~np.isfinite(norms) | (np.abs(norms - 1) > NORM_TOLERANCE))
    out += [f"{recs[i].record_id}: vector norm {norms[i]:.6f} is not 1" for i in bad[:10]]
    return {"rows": int(m.shape[0]), "dim": int(m.shape[1])}, out


def check_emb(snapshot: Snapshot, files: EmbFiles, stats: s6.TokenStats) -> GateResult:
    recs = snapshot.of("embedding_records")
    observed_counts = s6.counts([r.kind for r in recs])
    formula, violations = _formula(snapshot, recs)
    template, bad = _template(files.report, recs)
    violations += bad
    if template is not None:
        violations += _report(files, template, recs)
        violations += _derived(snapshot, template, stats, recs)
    vec, bad = _vectors(recs, files)
    violations += bad
    observed = {"records": observed_counts, "formula": formula, "vectors": vec,
                "template_id": None if template is None else template.template_id}
    expected = {"records": {"verse": formula["units"], "passage": formula["unchunked_passages"],
                            "chunk": formula["chunks"]}, "violations": 0}
    return GateResult(NAME, True, not violations, observed, expected, capped(violations))
