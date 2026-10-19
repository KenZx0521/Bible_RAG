"""G-REGNAL's expectation of the candidate layer, made by ``gates.regnal.expectation_doc``.

Prints the YAML body (schema, inputs, layer_sha256, chains, conflicts) of
store reports/regnal_fix_20261019/candidate/regnal_layer.json in the layout of
ragdata/src/ragdata/contract/expectations/regnal_expect.yaml, and whether the committed file
already loads to the same document. The file's header comments are written by hand.

    python3 -B expect.py
"""
from __future__ import annotations

import json

from fix_common import CANDIDATE, TEXT, sha256_file

WRAP = {"I": 14, "J": 13}   # names per line, as the hand-written file had them


def flow(names: list[str], wrap: int, indent: int) -> str:
    lines = [", ".join(names[i:i + wrap]) for i in range(0, len(names), wrap)]
    return "[" + (",\n" + " " * indent).join(lines) + "]"


def body(want: dict) -> str:
    out = [f"schema: {want['schema']}", "inputs:", f"  text: {want['inputs']['text']}",
           f"layer_sha256: {want['layer_sha256']}", "chains:"]
    out += [f"  {kd}: {flow(names, WRAP[kd], 6)}" for kd, names in want["chains"].items()]
    out.append(f"conflicts: {want['conflicts']}")
    return "\n".join(out) + "\n"


def main() -> None:
    from ragdata.gates.regnal import expectation_doc, load_regnal_expect
    layer = CANDIDATE / "regnal_layer.json"
    want = expectation_doc(json.loads(layer.read_bytes()), TEXT.name, sha256_file(layer))
    print(body(want), end="")
    print("# committed regnal_expect.yaml loads to this document:", dict(load_regnal_expect()) == want)


if __name__ == "__main__":
    main()
