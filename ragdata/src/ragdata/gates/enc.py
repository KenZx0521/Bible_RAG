"""G-ENC (design §6, §8): the emb layer was encoded by the pinned encoder, reproducibly.

Given the fingerprint stored with the layer and one computed in the running
environment (at build time they are the same), the gate requires:

- both fingerprints name the pinned models and revisions, and their tokenizers
  carry the pinned tokenizer.json sha and probe input_ids sha (the same pins the
  backend and evaluation check, so all three agree), with the ``</s></s>`` pair
  template; BGE-M3 normalises its vectors;
- the running environment has the stored tokenizer fingerprints and encode
  settings, and its probe vectors have cosine >= 0.9999 with the stored ones
  (an equal ``probe_vectors_sha`` is only reported);
- no record is longer than the model reads (``max_seq_length``, two special
  tokens included);
- 200 records sampled with a fixed seed, encoded again here, give their stored
  rows back (cos >= 0.9999): the rows are the encodings of their own texts;
- the legacy check (``gates.emb_legacy``) found no violation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ragcommon import encoder as pins
from ragdata.gates import emb_legacy
from ragdata.gates.base import GateResult, capped
from ragdata.gates.vectors import query_rows, rowwise_cos
from ragdata.stages.s06_emb.encoder import Encoder
from ragdata.stages.s06_emb.fingerprint import SCALE, encoder_fingerprint, ints_sha

NAME = "G-ENC"
PROBE_COS = 0.9999
SPECIAL_TOKENS = 2           # <s> … </s>
SECTIONS = {"bge_m3": pins.BGE_M3, "reranker": pins.RERANKER}
TOKENIZER_KEYS = ("tokenizer_sha", "probe_ids_sha", "unk_count", "pair_template_ok")
SETTING_KEYS = ("model", "revision", "dim", "max_seq_length", "normalize", "batch_size")
REENCODE = 200
Check = tuple[Mapping[str, Any], Sequence[str]]   # (observed, violations) of a sub-check


def _pins(doc: Mapping[str, Any], which: str) -> list[str]:
    out = []
    for section, spec in SECTIONS.items():
        got = doc.get(section, {})
        want = {"model": spec.repo_id, "revision": spec.revision,
                "tokenizer_sha": spec.tokenizer_sha256, "probe_ids_sha": spec.probe_ids_sha,
                "pair_template_ok": True}
        out += [f"{which} {section}.{k}: {got.get(k)!r}, pinned {v!r}"
                for k, v in want.items() if got.get(k) != v]
    if doc.get("bge_m3", {}).get("normalize") is not True:
        out.append(f"{which} bge_m3.normalize must be true")
    return out


def _probe_matrix(section: Mapping[str, Any], which: str) -> tuple[np.ndarray | None, list[str]]:
    ints = section.get("probe_vectors_e6")
    try:
        matrix = np.asarray(ints, dtype=np.float64) / SCALE
    except (TypeError, ValueError):
        return None, [f"{which} probe_vectors_e6 is not a matrix"]
    shape = (section.get("probes"), section.get("dim"))
    out = [] if matrix.shape == shape and shape[0] == len(pins.BGE_M3.probes) else \
        [f"{which} probe vectors have shape {matrix.shape}, expected {shape} "
         f"for {len(pins.BGE_M3.probes)} probes"]
    if section.get("probe_vectors_sha") != ints_sha(ints):
        out.append(f"{which} probe_vectors_sha is not the sha of probe_vectors_e6")
    return (None if out else matrix), out


def _environment(stored: Mapping[str, Any], observed: Mapping[str, Any]
                 ) -> tuple[dict[str, Any], list[str]]:
    out = []
    for section, keys in (("bge_m3", TOKENIZER_KEYS + SETTING_KEYS),
                          ("reranker", TOKENIZER_KEYS)):
        s, o = stored.get(section, {}), observed.get(section, {})
        out += [f"{section}.{k}: stored {s.get(k)!r}, here {o.get(k)!r}"
                for k in keys if s.get(k) != o.get(k)]
    a, bad_a = _probe_matrix(stored.get("bge_m3", {}), "stored")
    b, bad_b = _probe_matrix(observed.get("bge_m3", {}), "here")
    out += bad_a + bad_b
    info: dict[str, Any] = {"probe_min_cos": None}
    if a is not None and b is not None and a.shape == b.shape:
        cos = rowwise_cos(a, b)
        info["probe_min_cos"] = float(cos.min())
        out += [f"probe {i}: cos {c:.6f} < {PROBE_COS}" for i, c in enumerate(cos)
                if c < PROBE_COS]
    info["probe_vectors_sha_equal"] = (stored.get("bge_m3", {}).get("probe_vectors_sha")
                                       == observed.get("bge_m3", {}).get("probe_vectors_sha"))
    return info, out


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
    """``checks``: the ``reencoded`` and ``legacy`` sub-checks, already run."""
    violations = _pins(stored, "stored") + _pins(observed, "here")
    info, env = _environment(stored, observed)
    violations += env
    limit = stored.get("bge_m3", {}).get("max_seq_length")
    if not isinstance(limit, int) or max_tokens + SPECIAL_TOKENS > limit:
        violations.append(f"the longest record has {max_tokens} tokens; the model reads "
                          f"{limit} including {SPECIAL_TOKENS} special tokens")
    for name, (_, found) in checks.items():
        violations += [f"{name}: {v}" for v in found]
    observed_doc = {**info, "max_tokens": max_tokens, "max_seq_length": limit,
                    **{name: dict(seen) for name, (seen, _) in checks.items()}}
    expected = {"pins": "ragcommon.encoder", "probe_cos": PROBE_COS, "reencoded": REENCODE,
                "legacy_cos": emb_legacy.MIN_COS, "legacy_sample": emb_legacy.SAMPLE}
    return GateResult(NAME, True, not violations, observed_doc, expected, capped(violations))


def run_enc(recs: Sequence[Any], vectors: np.ndarray | None, stored: Mapping[str, Any],
            enc: Encoder, legacy_dir: Path, legacy_sample: int = emb_legacy.SAMPLE
            ) -> GateResult:
    """G-ENC of embedding records ``recs`` and their ``vectors`` under the encoder ``enc``
    (which fingerprints itself again, probes included)."""
    ids, texts = [r.record_id for r in recs], [r.text for r in recs]
    if vectors is None or vectors.ndim != 2 or vectors.shape[0] != len(recs):
        shape = None if vectors is None else vectors.shape
        missing = ({"sampled": 0}, [f"no vectors with one row per record ({shape})"])
        checks = {"reencoded": missing, "legacy": missing}
    else:
        checks = {"reencoded": check_reencoded(enc.embed, ids, texts, vectors),
                  "legacy": emb_legacy.check_compat(list(zip(ids, texts)), vectors, legacy_dir,
                                                    legacy_sample)}
    max_tokens = max((r.token_count for r in recs), default=0)
    return check_enc(stored, encoder_fingerprint(enc), max_tokens, checks)
