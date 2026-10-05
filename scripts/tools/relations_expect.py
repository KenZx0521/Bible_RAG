#!/usr/bin/env python3
"""W1 expected file and allowlist fragment for the semantic edges (batch
1A-T4; plan docs/records/2026-10-04_kg_batch1_plan.md §3: expected files
first, one merged allowlist per wave). Run before the staging build.

The semantic layer is check_edge_set's: every Entity-Entity edge but
MENTIONS and CROSS_REFERENCES. From the 6.05 report (--report) and the --a
side (default prod, diff_kg's a) this writes:
  --out        the expected file: {version, pp_version, run_id, report_sha256,
               output_sha256, edge_set_sha256, edges, by_type, by_ee_key} of
               the report's expected_after_10_2, the a side's {target,
               neo4j_uri, edges, by_type, by_ee_key} and every nonzero delta
               (b - a) {relationships: {type: n}, ee_edges: {key: n}}.
               check_edge_set --expect reads its edge_set_sha256.
  --allow-out  1A's relations fragment of the merged W1 allowlist, in
               diff_kg's --allow YAML (diff_kg.render_allowlist):
                 relationships  one exact delta per semantic type whose count
                                changes;
                 ee_edges       one glob '* source=-' without a bound for the
                                old keys: before 1A no semantic edge has a
                                source, and H11 source_null = 0 is hard, so
                                staging holds none of these keys;
                 ee_edges       one exact delta per changed key that has a
                                source (on today's prod: every W1 key, all new).
               No mention_count (residuals_allow.yaml) or CROSS_REFERENCES (1B's
               fragment) entries; diff_kg --merge-out joins the fragments.

The report is checked as check_edge_set checks it (format, the output file
hashing to output.sha256, expected_after_10_2 following from that file), and
its edge set must equal --expect-edge-set-sha, computed by an independent
simulation (W1: the planner's sim2_final.json after_10_2_sha256), never read
off the report: a report regenerated since cannot certify itself (§3). A W1
key without a source is refused, since the unbounded glob would hide it.
Both are decided before the target is read.

The a side is read with diff_kg.read_profile in READ sessions; check_identity's
guards judge the shell the tool started in, as in check_edge_set (--a prod is
refused in a shell that exports staging settings). A type's relationships
delta is its Entity-Entity count change: edges of that type between other
labels (none on prod) are taken as unchanged.

Usage (from the project root, in a shell without the staging exports):
    SIM=docs/records/2026-10-04_kg_fix/batch1/w1_1A/sim2_final.json
    scripts/.venv/bin/python scripts/tools/relations_expect.py \\
        --expect-edge-set-sha "$(jq -r .after_10_2_sha256 "$SIM")" \\
        --out config/kg_expect/batch1_w1/relations_expected.json \\
        --allow-out config/kg_expect/batch1_w1/relations_allow.yaml

Exit codes: 0 both files written; 1 the report's edge set differs from
--expect-edge-set-sha; 2 cannot generate (usage, an invalid report or output
file, a W1 key without a source, an unreadable target or output path).
Nothing is written on 1, and nothing on 2 unless a write itself failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# check_edge_set first: it keeps the shell as the tool started (resolve_shell_target)
# before its relation_postprocess import copies .env into os.environ.
from scripts.tools.check_edge_set import CannotCheck, load_reference, resolve_shell_target  # noqa: E402
from scripts.relation_extraction.relation_postprocess import DEFAULT_REPORT  # noqa: E402
from scripts.tools import diff_kg  # noqa: E402
from check_identity import open_neo4j  # noqa: E402

OLD_KEYS = "* source=-"  # diff_kg's ee_edges keys of the edges without a source
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GLOB = re.compile(r"[*?\[]")
HEADER = (
    "1A relations fragment of the merged W1 allowlist, written by relations_expect.py: regenerate it, "
    "never edit it.",
    "delta = the 6.05 report's expected_after_10_2 - the a side (diff_kg's b - a): one exact entry per",
    "changed semantic relationship type and per changed ee_edges key with a source, one glob without a",
    "bound for the old keys without one (H11 source_null = 0 is hard: staging holds none of them).",
    "No mention_count (residuals_allow.yaml) or CROSS_REFERENCES (1B's fragment) entries.")
REASONS = {
    "relationships": "1A Step 6.05 後的語意邊各型數量（規則邊、反向邊、10.3 共現邊退場；LLM 的 E–E 邊、"
                     "domain/range 與 provenance 閘門丟棄；錨定規則加入）：報告 expected_after_10_2"
                     "（edge set {tag}）減 {a}",
    "old": "1A 之後每條語意邊都帶 source，{a} 上沒有 source 的舊鍵整組消失（H11 source_null = 0 是硬門檻，"
           "staging 不會有這些鍵，故不設上限）",
    "new": "1A Step 6.05 各 TYPE phase source 的語意邊數：報告 expected_after_10_2（edge set {tag}）減 {a}",
}


class Mismatch(Exception):
    """The report's edge set is not the independent simulation's (exit 1)."""


def _sha256_arg(text: str) -> str:
    if not _SHA256.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not 64 lowercase hex")
    return text


def _is_old(key: str) -> bool:
    return key.endswith(" source=-")


def by_type(by_ee_key: dict[str, int]) -> dict[str, int]:
    """Edge counts per relationship type, summed over 'TYPE phase=P source=S' keys."""
    counts: Counter = Counter()
    for key, n in by_ee_key.items():
        counts[key.split(" ", 1)[0]] += n
    return dict(sorted(counts.items()))


# --- inputs ----------------------------------------------------------------------

def load_w1(report_path: Path, expect_sha: str) -> dict:
    """The W1 semantic layer the checked report describes; Mismatch unless its edge set is expect_sha."""
    ref, _ = load_reference(report_path)
    data = report_path.read_bytes()
    report = json.loads(data)
    if ref.sha256 != expect_sha:
        raise Mismatch(f"the report's edge set {ref.sha256} is not the independent simulation's "
                       f"{expect_sha}: a report cannot certify itself (plan §3); find out why first")
    no_source = sorted(key for key in ref.by_ee_key if _is_old(key))
    if no_source:
        raise CannotCheck(f"{report_path}: W1 keys without a source {no_source}; the unbounded "
                          f"'{OLD_KEYS}' glob would allow them")
    types = by_type(ref.by_ee_key)
    if report["expected_after_10_2"].get("by_type") != types:
        raise CannotCheck(f"{report_path}: expected_after_10_2.by_type does not sum its by_ee_key")
    try:
        meta = {name: report[name] for name in ("pp_version", "run_id")}
    except KeyError as e:
        raise CannotCheck(f"{report_path} has no {e}") from e
    return {**meta, "report_sha256": hashlib.sha256(data).hexdigest(),
            "output_sha256": report["output"]["sha256"], "edge_set_sha256": ref.sha256,
            "edges": ref.edges, "by_type": types, "by_ee_key": dict(sorted(ref.by_ee_key.items()))}


def read_a(name: str) -> dict:
    """The a side's semantic counts from diff_kg.read_profile (READ sessions)."""
    try:
        target = resolve_shell_target(name)
        driver = open_neo4j(target)
        try:
            driver.verify_connectivity()  # fail fast instead of retrying a refused connection
            profile = diff_kg.read_profile(driver)
        finally:
            driver.close()
    except Exception as e:  # noqa: BLE001  (an unreadable target cannot give a baseline)
        raise CannotCheck(f"--a {name} not readable: {type(e).__name__}: {e}") from e
    ee = dict(sorted(profile["ee_edges"].items()))
    return {"target": name, "neo4j_uri": target.neo4j_uri, "edges": sum(ee.values()),
            "by_type": by_type(ee), "by_ee_key": ee}


# --- expectation -----------------------------------------------------------------

def deltas(w1: dict, a: dict) -> dict:
    """Every nonzero b - a, by type and by ee key (diff_kg.diff_counts)."""
    return {section: {d["key"]: d["delta"] for d in diff_kg.diff_counts(section, a[field], w1[field])}
            for section, field in (("relationships", "by_type"), ("ee_edges", "by_ee_key"))}


def allow_entries(delta: dict, tag: str, a_name: str) -> list[dict]:
    """The fragment: exact relationships deltas, the old-key glob, exact deltas of keys with a source."""
    def exact(section: str, key: str, n: int, reason: str) -> dict:
        if _GLOB.search(key):
            raise CannotCheck(f"{section} key {key!r} is a glob, not an exact key")
        return {"section": section, "key": key, "delta": n,
                "reason": REASONS[reason].format(tag=tag, a=a_name)}

    ee = delta["ee_edges"]
    old = [{"section": "ee_edges", "key": OLD_KEYS, "reason": REASONS["old"].format(a=a_name)}]
    return ([exact("relationships", t, n, "relationships") for t, n in delta["relationships"].items()]
            + (old if any(_is_old(key) for key in ee) else [])
            + [exact("ee_edges", key, n, "new") for key, n in ee.items() if not _is_old(key)])


def build(w1: dict, a: dict) -> tuple[dict, str]:
    """(the expected file document, the fragment's YAML)."""
    delta = deltas(w1, a)
    entries = allow_entries(delta, w1["edge_set_sha256"][:12], a["target"])
    header = [*HEADER, f"report sha256 {w1['report_sha256']}, run_id {w1['run_id']}, "
                       f"pp_version {w1['pp_version']}, edge set {w1['edge_set_sha256']}",
              f"{a['target']} {a['neo4j_uri']}"]
    return {"version": 1, **w1, "a": a, "deltas": delta}, diff_kg.render_allowlist(entries, header)


# --- output ----------------------------------------------------------------------

def summary(doc: dict, entries: int) -> list[str]:
    a, ee = doc["a"], doc["deltas"]["ee_edges"]
    old = [n for key, n in ee.items() if _is_old(key)]
    keys, total = Counter(), Counter()
    for key, n in ee.items():
        if not _is_old(key):
            source = key.rsplit("source=", 1)[1]
            keys[source] += 1
            total[source] += n
    rel = doc["deltas"]["relationships"]
    return [
        f"relations_expect: report {doc['run_id']} {doc['pp_version']}, edge set "
        f"{doc['edge_set_sha256'][:12]} = --expect-edge-set-sha",
        f"  W1 after 10.2: {doc['edges']:,} edges, {len(doc['by_type'])} types, {len(doc['by_ee_key'])} ee keys",
        f"  {a['target']} ({a['neo4j_uri']}): {a['edges']:,} edges, {len(a['by_type'])} types, "
        f"{len(a['by_ee_key'])} ee keys",
        f"  relationships: {len(rel)} entries, net {sum(rel.values()):+,} ({a['edges']:,} -> {doc['edges']:,})",
        f'  ee_edges: glob "{OLD_KEYS}" covers {len(old)} keys, {sum(old):+,}',
        f"  ee_edges: {sum(keys.values())} exact keys: "
        + ", ".join(f"{s} {keys[s]} ({total[s]:+,})" for s in sorted(keys)),
        f"  fragment: {entries} entries",
    ]


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}  {path}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                        help="the 6.05 report (default: output/relations_clean.report.json)")
    parser.add_argument("--expect-edge-set-sha", type=_sha256_arg, required=True,
                        help="the edge set sha256 an independent simulation computed (not the report's)")
    parser.add_argument("--a", choices=("prod", "staging"), default="prod",
                        help="diff_kg's a side, the graph the deltas are taken from (default prod)")
    parser.add_argument("--out", type=Path, required=True, help="the expected file (JSON) to write")
    parser.add_argument("--allow-out", type=Path, required=True, help="the allowlist fragment (YAML) to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.out.resolve() == args.allow_out.resolve():
        parser.error("--out and --allow-out must be different files")
    try:
        doc, fragment = build(load_w1(args.report, args.expect_edge_set_sha), read_a(args.a))
        written = [_write(args.out, json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"),
                   _write(args.allow_out, fragment)]
    except Mismatch as e:
        print(f"MISMATCH: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  (a traceback would exit 1, which here means "mismatch")
        error = str(e) if isinstance(e, CannotCheck) else f"{type(e).__name__}: {e}"
        print(f"CANNOT GENERATE: {error}", file=sys.stderr)
        return 2
    print("\n".join(summary(doc, len(diff_kg.parse_allowlist(fragment, args.allow_out)))))
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
