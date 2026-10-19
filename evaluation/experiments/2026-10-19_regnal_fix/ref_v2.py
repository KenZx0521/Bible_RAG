"""ref_layer_v2.json: experiment A's reference layer with Solomon taken off the Judah chain.

Kay 2026-10-19: Solomon is a king of all Israel (kingdom 'U' in the regnal layer), not the first
king of Judah. The reference layer has to follow, but its file ref_layer.json (sha 79d57efe...) is
frozen in experiment A (A/inputs_manifest.json, confirm/c_common.py FROZEN_SHA, the confirmation
tests), so the change is a new file derived from it, never an overwrite:

- drop row J00 (Solomon; no synchronism names it, J01 is the only row with it as predecessor);
- J01 (Rehoboam): pred [null, "founder", "1ki.11.43"], the chain-head form of I01; his father
  stays Solomon.

Serialized like the original (indent=1, ensure_ascii=False, no final newline). Writes
store reports/regnal_fix_20261019/ref_layer_v2.json and prints its sha256.

    python3 -B ref_v2.py
"""
from __future__ import annotations

import json

from fix_common import REF, REF_SHA, REF_V2, dump, read_pinned, sha256_file, write_new

DROP = "J00"
HEAD = "J01"


def derive(rows: list[dict]) -> list[dict]:
    """The v2 rows of the reference rows (a new list; ``rows`` is not changed)."""
    if any(s[0] == DROP for r in rows for s in r["sync"]):
        raise SystemExit(f"a synchronism names {DROP}")
    if [r["id"] for r in rows if r["pred"] and r["pred"][0] == DROP] != [HEAD]:
        raise SystemExit(f"{HEAD} is not the only row after {DROP}")
    out = []
    for r in rows:
        if r["id"] == DROP:
            continue
        if r["id"] == HEAD:
            r = {**r, "pred": [None, "founder", r["pred"][2]]}
        out.append(r)
    return out


def main() -> None:
    data = read_pinned(REF, REF_SHA)
    rows = json.loads(data)
    if dump(rows) != data:
        raise SystemExit(f"{REF.name} does not re-serialize to its own bytes")
    v2 = derive(rows)
    sha = write_new(REF_V2, dump(v2))
    if sha256_file(REF) != REF_SHA:
        raise SystemExit(f"{REF} changed")
    print(json.dumps({"ref_layer_v2": str(REF_V2), "sha256": sha, "rows": len(v2),
                      "from": {"file": str(REF), "sha256": REF_SHA},
                      "chains": {kd: sum(r["kingdom"] == kd for r in v2) for kd in ("I", "J")}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
