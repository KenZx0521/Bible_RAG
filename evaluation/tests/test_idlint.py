"""G-IDLINT (design §3.2): evaluation never derives an id's meaning by splitting it on ':'.

Ids are read through ragcommon.ids.parse, the payload's fields or table columns.
A ':' split that is not about an id goes in ALLOWED, keyed by file and the exact
source line, with the reason it is not an id. FROZEN holds the id splits of closed
experiments whose code is sha-pinned in their records and so cannot change; each
names its pin and the ids.parse call it stands for. New code never goes there.
"""

import os
import re
from pathlib import Path

import pytest

EVAL_ROOT = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()   # this file's samples below are the scanner's fixtures
COLON_SPLIT = re.compile(r"""\.(?:r?split|r?partition|count)\(\s*(?P<q>['"]):(?P=q)""")
_SKIP_DIRS = {".venv", "__pycache__"}

# (path relative to evaluation/, stripped source line) -> why it is not an id.
_PATH_VAR = "the PATH environment variable, an os.pathsep-joined directory list"
ALLOWED: dict[tuple[str, str], str] = {
    ("experiments/2026-10-14_graph_gd/ho_tools/mech_check.py",
     'out.append(Violation(f"overlap_{owner.split(\':\')[0]}", f"{qid}: {pid} is gold of {owner}"))'):
        "owner is the label f'{qset.name}:{q.qid}' built at mech_check.py:78 (e.g. 'new82:N_KIN_01'); "
        "the split takes the question-set name",
    ("experiments/2026-10-18_graph_qd/qd_eval.py", 'w, l = (int(x) for x in c["unit_W:L"].split(":"))'):
        "the 'W:L' win/loss tally of the frozen IT report (retrieval_iter.json carries only unit_W:L, e.g. '2:0')",
    ("experiments/2026-10-20_gen_confirm/run_qg.py",
     'return {**out, "stopped_why": dict(Counter(d[2].split(":")[0] for d in done if d[0] == "stopped"))}'):
        "stop-reason text f'{type(err).__name__}: {err}' (run_qg.py:284), counted by its exception name",
    ("tests/test_gen_confirm_infra.py",
     'assert env["PATH"].split(":") == [str(tmp_path / "clibin"), str(tmp_path / "hookbin"), str(tmp_path / "bin"),'):
        _PATH_VAR,
    ("tests/test_gen_confirm_infra.py", 'assert str(tmp_path / "bin") not in none["PATH"].split(":")'): _PATH_VAR,
    ("tests/test_gen_confirm_infra.py",
     'assert log["env"]["PATH"].split(":")[:3] == [str(root / d) for d in ("clibin", "hookbin", "bin")]'): _PATH_VAR,
    ("tests/test_gen_confirm_infra.py",
     'assert str(root / "bin") not in log["env"]["PATH"].split(":") and _flag(log["argv"], "--tools") == ""'):
        _PATH_VAR,
    ("tests/test_gen_confirm_qset.py",
     'assert [ln.split(":")[0] for ln in block.splitlines()[1:]] == ["quantity", "people", "scope", "naming"]'):
        "rendered prompt-block lines 'label: text'; the split reads the label",
    ("tests/test_gen_confirm_qset.py",
     'assert got == {} and [v.detail.split(":")[0] for v in bad] == ["q1"]      # a label given twice has no question'):
        "Violation.detail 'q1: given more than once' (mech_qg.py:70); the split reads the slot label",
}

# (path relative to evaluation/, stripped source line) -> the pin that freezes it and the
# ids.parse call it stands for.
FROZEN: dict[tuple[str, str], str] = {
    ("experiments/2026-10-14_graph_gd/ho_tools/annotate.py",
     'books = sorted({p.split(":")[1].split(".")[0] for p in all_pids if ":" in p})'):
        "passage id ps:<book>.<ch>.<v> to its book, ids.parse(p).book_id; "
        "sha-pinned in experiments/2026-10-14_graph_gd/appendix_a_sha256.txt",
    ("experiments/2026-10-18_graph_qd/qd_step2.py", 'kind, _, body = source_id.partition(":")'):
        "source id kind by its prefix (ps/ck/vs/vr), ids.parse(source_id).kind; "
        "sha-pinned in store reports/graph_qd_20261018/step2/lanes2_meta.json",
    ("experiments/2026-10-18_kg_cards/A/k0_prep.py", 'out[(rec[5], rec[4])] = rec[1].split(":")[1].split("#")[0]'):
        "footnote id fn:<unit>#<n> to its unit, ids.parse(fn_id).parent.raw; "
        "sha-pinned in store reports/kg_cards_20261018/A/inputs_manifest.json",
    ("experiments/2026-10-18_kg_cards/B/b_items.py", 'by_book[p.split(":")[1].split(".")[0]].append(p)'):
        "pericope id pc:<book>.<ch>.<v> to its book, ids.parse(p).book_id; "
        "sha-pinned in experiments/2026-10-18_kg_cards/B/appendix_B.md",
}
_EXEMPT = {**ALLOWED, **FROZEN}


def _sources():
    for root, dirs, files in os.walk(EVAL_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith("results")]
        for name in files:
            path = Path(root) / name
            if name.endswith(".py") and path.resolve() != _SELF:
                yield path.relative_to(EVAL_ROOT).as_posix(), path.read_text(encoding="utf-8")


def test_no_id_is_split_on_colon():
    violations = [
        f"{rel}:{n}: {line.strip()}"
        for rel, text in _sources()
        for n, line in enumerate(text.splitlines(), start=1)
        if COLON_SPLIT.search(line) and (rel, line.strip()) not in _EXEMPT
    ]

    assert violations == []


def test_every_allowlisted_split_still_exists_and_says_why():
    texts = dict(_sources())
    stale = [key for key, reason in _EXEMPT.items()
             if not reason.strip() or key[1] not in {ln.strip() for ln in texts.get(key[0], "").splitlines()}]

    assert stale == []


@pytest.mark.parametrize("line, flagged", [
    ('parts = source_id.split(":")', True),
    ("book, rest = rid.split(':', 1)", True),
    ('head, _, tail = rid.rpartition(":")', True),
    ('n = rid.count(":")', True),
    ('items = text.split(",")', False),
    ('a, b = key.split("::")', False),
    ('parsed = ids.parse(rid)', False),
])
def test_the_scan_recognises_colon_splits(line, flagged):
    assert bool(COLON_SPLIT.search(line)) is flagged
