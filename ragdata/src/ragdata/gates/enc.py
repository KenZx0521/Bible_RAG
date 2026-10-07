"""G-ENC (design §6, §8): the emb layer was encoded by the pinned encoder, reproducibly.

Given the fingerprint stored with the layer and one computed in the running
environment (at build time they are the same), the gate requires:

- both fingerprints name the pinned models and revisions, and their tokenizers
  carry the pinned tokenizer.json sha and probe input_ids sha (the same pins the
  backend and evaluation check, so all three agree), with the ``</s></s>`` pair
  template; BGE-M3 normalises its vectors;
- the running environment computes the stored fingerprint exactly (it holds
  nothing that depends on the device);
- ``probes``: the probe vectors stored in the ``vectors`` attachment and those
  encoded here have cosine >= 0.9999 (an equal ``probe_vectors_sha`` is only
  reported: it differs between devices);
- no record is longer than the model reads (``max_seq_length``, two special
  tokens included);
- ``reencoded``: 200 records sampled with a fixed seed, encoded again here, give
  their stored rows back (cos >= 0.9999): the rows are the encodings of their
  own texts;
- ``legacy``: the legacy check (``gates.emb_legacy``) found no violation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ragcommon import encoder as pins
from ragdata.gates import emb_legacy
from ragdata.gates.base import GateResult, capped
from ragdata.gates.vectors import compare_probes, query_rows, rowwise_cos
from ragdata.stages.s06_emb.encoder import Encoder
from ragdata.stages.s06_emb.fingerprint import encoder_fingerprint, probe_vectors
from ragdata.store.vectors import VectorSet, ints_sha, probe_ints

NAME = "G-ENC"
PROBE_COS = 0.9999
SPECIAL_TOKENS = 2           # <s> … </s>
SECTIONS = {"bge_m3": pins.BGE_M3, "reranker": pins.RERANKER}
REENCODE = 200
SUB_CHECKS = ("probes", "reencoded", "legacy")
Check = tuple[Mapping[str, Any], Sequence[str]]   # (observed, violations) of a sub-check


@dataclass(frozen=True)
class StoredEncoding:
    """What an emb layer holds that G-ENC checks."""

    fingerprint: Mapping[str, Any]            # encoder_fingerprint.json
    vectors: VectorSet | None                 # the vectors attachment (None: unreadable)


@dataclass(frozen=True)
class EncOptions:
    legacy_dir: Path                          # the old output/ (gates.emb_legacy)
    legacy_sample: int = emb_legacy.SAMPLE


def _section(doc: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    found = doc.get(name)
    return found if isinstance(found, Mapping) else {}


def _pins(doc: Mapping[str, Any], which: str) -> list[str]:
    out = []
    for section, spec in SECTIONS.items():
        got = _section(doc, section)
        want = {"model": spec.repo_id, "revision": spec.revision,
                "tokenizer_sha": spec.tokenizer_sha256, "probe_ids_sha": spec.probe_ids_sha,
                "pair_template_ok": True}
        out += [f"{which} {section}.{k}: {got.get(k)!r}, pinned {v!r}"
                for k, v in want.items() if got.get(k) != v]
    if _section(doc, "bge_m3").get("normalize") is not True:
        out.append(f"{which} bge_m3.normalize must be true")
    return out


def _environment(stored: Mapping[str, Any], observed: Mapping[str, Any]) -> list[str]:
    top = sorted((set(stored) | set(observed)) - set(SECTIONS))
    out = [f"{k}: stored {stored.get(k)!r}, here {observed.get(k)!r}"
           for k in top if stored.get(k) != observed.get(k)]
    for section in SECTIONS:
        s, o = _section(stored, section), _section(observed, section)
        out += [f"{section}.{k}: stored {s.get(k)!r}, here {o.get(k)!r}"
                for k in sorted(set(s) | set(o)) if s.get(k) != o.get(k)]
    return out


def check_probes(stored: VectorSet, here: np.ndarray) -> Check:
    """The probe vectors in the attachment against ``here``, the pinned probes encoded now."""
    observed, violations = compare_probes(stored.probes, np.asarray(here, np.float64), PROBE_COS)
    return ({**observed, "sha_equal": stored.probes_sha == ints_sha(probe_ints(here))},
            violations)


def check_reencoded(embed: Callable[[Sequence[str]], np.ndarray], ids: Sequence[str],
                    texts: Sequence[str], vectors: np.ndarray, sample: int = REENCODE) -> Check:
    """Encode a fixed sample of records again and compare with their stored rows."""
    rows = query_rows(len(ids), sample)
    fresh = np.asarray(embed([texts[i] for i in rows]), dtype=np.float32)
    if fresh.shape != (len(rows), vectors.shape[1]):
        return {"sampled": int(rows.size)}, [f"re-encoding gave {fresh.shape} for {rows.size} "
                                             "records"]
    cos = rowwise_cos(vectors[rows], fresh)
    violations = [f"{ids[i]}: stored row has cos {c:.7f} < {PROBE_COS} with its text encoded "
                  "here" for i, c in zip(rows, cos) if c < PROBE_COS]
    return {"sampled": int(rows.size), "min_cos": float(cos.min()) if cos.size else None}, \
        violations


def check_enc(stored: Mapping[str, Any], observed: Mapping[str, Any], max_tokens: int,
              checks: Mapping[str, Check]) -> GateResult:
    """``checks``: the ``probes``, ``reencoded`` and ``legacy`` sub-checks, already run."""
    violations = _pins(stored, "stored") + _pins(observed, "here")
    violations += _environment(stored, observed)
    limit = _section(stored, "bge_m3").get("max_seq_length")
    if not isinstance(limit, int) or max_tokens + SPECIAL_TOKENS > limit:
        violations.append(f"the longest record has {max_tokens} tokens; the model reads "
                          f"{limit} including {SPECIAL_TOKENS} special tokens")
    for name, (_, found) in checks.items():
        violations += [f"{name}: {v}" for v in found]
    observed_doc = {"max_tokens": max_tokens, "max_seq_length": limit,
                    **{name: dict(seen) for name, (seen, _) in checks.items()}}
    expected = {"pins": "ragcommon.encoder", "probe_cos": PROBE_COS, "reencoded": REENCODE,
                "legacy_cos": emb_legacy.MIN_COS, "legacy_sample": emb_legacy.SAMPLE}
    return GateResult(NAME, True, not violations, observed_doc, expected, capped(violations))


def run_enc(recs: Sequence[Any], stored: StoredEncoding, enc: Encoder, options: EncOptions
            ) -> GateResult:
    """G-ENC of embedding records ``recs`` and what the layer stored for them, under the
    encoder ``enc`` (which fingerprints itself and encodes the probes again)."""
    ids, texts = [r.record_id for r in recs], [r.text for r in recs]
    found = stored.vectors
    if found is None or found.matrix.shape[0] != len(recs):
        shape = None if found is None else found.matrix.shape
        missing = ({"sampled": 0}, [f"no vectors with one row per record ({shape})"])
        checks = dict.fromkeys(SUB_CHECKS, missing)
    else:
        checks = {"probes": check_probes(found, probe_vectors(enc)),
                  "reencoded": check_reencoded(enc.embed, ids, texts, found.matrix),
                  "legacy": emb_legacy.check_compat(list(zip(ids, texts)), found.matrix,
                                                    options.legacy_dir, options.legacy_sample)}
    max_tokens = max((r.token_count for r in recs), default=0)
    return check_enc(stored.fingerprint, encoder_fingerprint(enc), max_tokens, checks)
