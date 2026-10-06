"""Pins of the fixes made before K9 labelling and the W1 staging rebuild (2026-10-06 review).

K9's llm/prior rubric is one rule (a person in the evidence verse may be a
name, a pronoun or an omitted subject fixed by the ±1 context; a relation
stated only in the context does not count) and the pre-registration says
there are two rubric versions. The anchored gate's jq checks that the report
used anchored_kay.jsonl (its sha256 among the inputs, coverage enforced at
--min-spotcheck-extra 10), so a run that dropped both spot-check flags
fails. Nothing destroys the batch-0 staging without R0 item 9's backups: the
W1 R1 item 2 block checks both dumps against bak/$D/SHA256SUMS before dropdb,
check_w1_registration has a row per dump before Step 3, and the backup itself
refuses a PG staging that is not the batch-0 build. A rejection at W1 step 4
reruns the whole W1 chain, so the registration gate runs again. The W1
promotion doc is in the docs indexes and linked from every main-doc mention,
plan §9.1's Q11 note says which debt functions grew, and the W0 record notes
that Kay took W1-0 into W1.
"""
from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path

import pytest
from scripts.tools import kin_review as kr
from test_docs_alignment import (DOC, ROOT, STAGING_DOC, _assert_fail_closed, _blocks, _commands, _first, _in_order,
                                 _rebuild_chain, help_text, mask_code, read, section, staging_text)
from test_docs_alignment_kay1006 import (BATCH0_COUNTS, KAY, NEO4J_DUMP, PG_DUMP, PLAN1, SUMS, _backup, _bash, _calls,
                                         _k9, stub)
from test_docs_alignment_w1 import W1A, _block, _item
from test_kin_review import counted, write_labels, write_sample

W0 = ROOT / "docs" / "records" / "2026-10-05_kg_batch1_w0_results.md"
CREATE = ("docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging",
          "docker exec bible_rag_postgres dropdb -U bible --if-exists bible_rag_staging",
          "docker exec bible_rag_postgres createdb -U bible bible_rag_staging",
          "docker exec -i bible_rag_postgres psql -U bible -d bible_rag_staging -v ON_ERROR_STOP=1 < scripts/db/schema.sql")
CHECKS = (f"test -s {NEO4J_DUMP}", f"test -s {PG_DUMP}",
          *(f"(cd bak/$D && grep -F ' {path}' SHA256SUMS | sha256sum -c -)" for path in SUMS))


# ---------------------------------------------------------------- (1) K9: two rubric versions, one context rule

def test_k9_preregistration_names_two_rubric_versions_and_one_context_rule():
    k9 = _k9()
    assert "同一份 rubric" not in k9 and "用前後一節幫助讀懂" not in k9
    for needle in ("兩個版本", "anchored 一份", "llm、prior 一份", "名字、代名詞或省略的主詞", "前一節與後一節",
                   "確定不了", "只在 context 裡說的關係不算", "id_correct 的判準不變", "`RUBRIC_WITH_CONTEXT`"):
        assert needle in k9, needle
    assert kr.RUBRIC_WITH_CONTEXT["id_correct"] == kr.RUBRIC["id_correct"]
    plan = next(line for line in section(read(PLAN1), "9.1").splitlines() if line.startswith("- **Q8"))
    for needle in ("2026-10-06 標註之前寫成一條規則", "代名詞或省略的主詞", "`RUBRIC_WITH_CONTEXT`"):
        assert needle in plan, needle


# ---------------------------------------------------------------- (2) the anchored gate used the spot-check file

def _gate() -> list[str]:
    return _block(W1A, "--sample $K/anchored.json")


def test_k9_anchored_gate_checks_the_report_used_anchored_kay():
    gate = _gate()
    _in_order(gate, ("kin_review.py --mode score", "S=$(sha256sum < $K/anchored_kay.jsonl | cut -d' ' -f1)",
                     'jq -e --slurpfile kay $K/anchored_kay.jsonl --arg sha "$S"', "echo 'K9 anchored passed'"))
    check = gate[_first(gate, "jq -e")]
    for needle in ("(.inputs.spotcheck.sha256 == $sha)", "(.spotcheck.min_extra == 10)"):
        assert needle in check, needle
    prose = _item(section(staging_text(), W1A), "1")
    for needle in ("一定同時帶 `--spotcheck $K/anchored_kay.jsonl` 與 `--min-spotcheck-extra 10`",
                   "`--min-spotcheck-extra needs --spotcheck`", "inputs.spotcheck.sha256"):
        assert needle in prose, needle


def _k9_dir(tmp_path: Path) -> Path:
    """bak/$D/k9 after labelling: A and B disagree on item003, the adjudication settles it, and
    anchored_kay.jsonl covers it and 10 others."""
    labels = counted(60, 57, 51)
    other = list(labels)
    other[3] = (False, False)
    Path(write_sample(tmp_path, 60)).rename(tmp_path / "anchored.json")
    write_labels(tmp_path, "anchored_a.jsonl", labels, "ai:session-a")
    write_labels(tmp_path, "anchored_b.jsonl", other, "ai:session-b")
    write_labels(tmp_path, "anchored_adj.jsonl", {3: (True, True)}, "ai:session-c")
    write_labels(tmp_path, "anchored_kay.jsonl", {i: (True, True) for i in (3, *range(10, 20))}, "kay")
    write_labels(tmp_path, "other_kay.jsonl", {i: (True, True) for i in (3, *range(20, 30))}, "kay")
    return tmp_path


@pytest.mark.parametrize("case, ok", [("as documented", True), ("both spot-check flags dropped", False),
                                      ("another spot-check file", False)])
def test_k9_gate_check_fails_unless_the_report_used_anchored_kay(tmp_path, case, ok):
    gate, k = _gate(), _k9_dir(tmp_path)
    score = gate[_first(gate, "kin_review.py --mode score")].split("kin_review.py", 1)[1].replace("$K", str(k))
    if case == "both spot-check flags dropped":
        score = score.replace(f"--spotcheck {k}/anchored_kay.jsonl --min-spotcheck-extra 10", "")
    elif case == "another spot-check file":
        score = score.replace("anchored_kay.jsonl", "other_kay.jsonl")

    assert kr.main(shlex.split(score)) == 0          # kin_review alone passes the gate in every case

    lines = [gate[_first(gate, "S=$(sha256sum")], gate[_first(gate, "jq -e")]]
    run = _bash(f"set -e -o pipefail; K={k}; " + "; ".join(lines), tmp_path)
    assert (run.returncode == 0) is ok, run


# ---------------------------------------------------------------- (3a) no dropdb or Step 3 without the backups

def _r1_create() -> list[list[str]]:
    return _blocks(_item(section(staging_text(), "R1"), "2"))


def test_r1_item_2_w1_block_checks_the_batch0_backups_before_dropdb():
    generic, w1 = _r1_create()
    assert generic == list(CREATE), generic
    _assert_fail_closed(w1, "PG staging recreated after the batch-0 backup check")
    assert w1[3:-2] == [*CHECKS, *CREATE], w1
    item = _item(section(staging_text(), "R1"), "2")
    for needle in ("第 1 批 W1", "不貼上面那段", "R0 第 9 項", "`bak/$D/SHA256SUMS`", "Q7", "dropdb 之後"):
        assert needle in item, needle


@pytest.mark.parametrize("case", ["backed up", "never backed up", "neo4j dump changed", "pg dump empty",
                                  "line missing"])
def test_r1_item_2_w1_block_drops_nothing_without_the_recorded_backups(tmp_path, case):
    if case != "never backed up":
        assert _bash(stub() + "\n".join(_backup()), tmp_path).returncode == 0
        (tmp_path / "calls").unlink()
    backup = tmp_path / "bak" / "x"
    neo4j_line = f"{hashlib.sha256(b'NEO').hexdigest()}  {SUMS[0]}\n"   # what the stub's dump hashes to
    if case == "neo4j dump changed":
        (backup / "neo4j_staging" / "neo4j.dump").write_text("other")
    elif case == "pg dump empty":   # empty, with a matching line: sha256sum -c alone would pass it
        (backup / "postgres" / "bible_rag_staging.dump").write_text("")
        (backup / "SHA256SUMS").write_text(neo4j_line + f"{hashlib.sha256(b'').hexdigest()}  {SUMS[1]}\n")
    elif case == "line missing":
        (backup / "SHA256SUMS").write_text(neo4j_line)
    (tmp_path / "scripts" / "db").mkdir(parents=True)
    (tmp_path / "scripts" / "db" / "schema.sql").write_text("-- schema\n")

    result = _bash(stub() + "\n".join(_r1_create()[1]), tmp_path)

    assert (result.returncode == 0) is (case == "backed up"), result
    words = [" ".join(c.split()[1:3]) for c in _calls(tmp_path)]
    assert words == (["compose -f", "exec bible_rag_postgres", "exec bible_rag_postgres", "exec -i"]
                     if case == "backed up" else []), words


def test_the_registration_gate_checks_the_backups_wherever_it_is_described():
    invocation = next(c for c in _commands(section(staging_text(), W1A)) if "check_w1_registration.py" in c)
    assert invocation == "uv run --project scripts python scripts/tools/check_w1_registration.py --backup-dir bak/$D"
    chain = " ".join({row[0]: row for row in _rebuild_chain(read(DOC))[1]}["check_w1_registration"])
    inventory = next(line for line in read(STAGING_DOC).splitlines() if line.startswith("| tools/check_w1_registration"))
    r1 = _item(section(staging_text(), "R1"), "5")
    for text in (chain, inventory, r1):
        for needle in ("R0 第 9 項", "SHA256SUMS", "`--backup-dir bak/$D`"):
            assert needle in text, (needle, text[:60])
    words = " ".join(help_text("check_w1_registration").split())
    for needle in ("--backup-dir", "R0 item 9", "SHA256SUMS"):
        assert needle in words, needle


# ---------------------------------------------------------------- (3b) the backup refuses a non-batch-0 PG staging

def test_r0_item_9_checks_pg_staging_is_the_batch0_build_before_dumping_it():
    block = _backup()
    _in_order(block, ('test "$N" = 0', "C=$(docker exec bible_rag_postgres psql -U bible -d bible_rag_staging -Atc",
                      f"test \"$C\" = '{BATCH0_COUNTS}'", "mkdir -p bak/$D/neo4j_staging", "pg_dump -U bible"))
    query = block[_first(block, "C=$(docker exec bible_rag_postgres psql")]
    assert "FROM entities" in query and "FROM entity_mentions" in query, query
    item = _item(section(staging_text(), "R0"), "9")
    for needle in ("9,124", "173,768", "R1 第 2 項", "Step 3", "唯讀"):
        assert needle in item, needle


# ---------------------------------------------------------------- (4) a rejection reruns the whole W1 chain

def test_a_rejection_reruns_the_whole_w1_chain_so_the_registration_gate_runs_again():
    rejection = next(line for line in section(staging_text(), KAY).splitlines() if line.startswith("Kay 不核可時"))
    plan = next(line for line in section(read(PLAN1), "9.1").splitlines() if line.startswith("- **Q7"))
    for text in (rejection, plan):
        assert "再從 Step 5 重建" not in text, text
        for needle in ("從頭重跑", "6.05 → check_w1_registration → Step 3", "登記檢查", "R1 第 2 項"):
            assert needle in text, (needle, text[:40])
    assert "](build_database.md)" in rejection and "](../build_database.md)" in plan


# ---------------------------------------------------------------- (5) indexes, links, the Q11 note

@pytest.mark.parametrize("index", [ROOT / "docs" / "README.md", ROOT / "docs" / "ARCHITECTURE.md"], ids=lambda p: p.name)
def test_the_docs_indexes_list_the_w1_promotion_runbook(index):
    rows = [line for line in read(index).splitlines() if line.startswith("| [staging_promotion")]
    assert [row.split("]")[0] for row in rows] == ["| [staging_promotion.md", "| [staging_promotion_w1.md"], rows
    assert "(staging_promotion_w1.md)" in rows[1] and "R3" in rows[1]


def test_every_main_doc_mention_of_a_w1_promotion_step_links_the_w1_doc():
    mentions = [line for line in mask_code(read(STAGING_DOC)).splitlines() if re.search(r"升版第 (?:1|2|1、2) 步", line)]
    assert len(mentions) >= 8 and not [m for m in mentions if "](staging_promotion_w1.md)" not in m], mentions


def test_plan_q11_says_which_debt_functions_grew_shrank_or_kept_their_length():
    note = next(line for line in section(read(PLAN1), "9.1").splitlines() if line.startswith("- **Q11"))
    grew, rest = note.split("變長的 4 個：", 1)[1].split("變短的 2 個：", 1)
    shrank, same = rest.split("行數不變的 2 個：", 1)
    for part, functions in ((grew, ("get_cross_references_multi_hop` 65→70", "retrieve_via_cross_references` 58→59",
                                    "import_neo4j.py::main` 119→120", "validate_output` 174→182")),
                            (shrank, ("_export_jsonl` 178→166", "extract_relations.py::main` 119→103")),
                            (same, ("_route_r3` 131", "_route_r5` 167"))):
        for function in functions:
            assert function in part, (function, part)
    assert "其中 4 個在 W1 期間變長：" not in note


# ---------------------------------------------------------------- (6) the W0 record's open question, resolved

def test_w0_results_keeps_the_open_question_and_notes_kays_decision_under_it():
    lines = read(W0).splitlines()
    at = next(i for i, line in enumerate(lines) if "是否納入 W1 待 Kay 決定。" in line)
    assert lines[at] == "  - 不修的話，W1 的 opt-in A/B 無法歸因。是否納入 W1 待 Kay 決定。"   # the original, unchanged
    note = lines[at + 1]
    assert note.startswith("  - **補記（2026-10-06）")
    for needle in ("Kay 2026-10-05", "W1-0", "087ab0d", "3a294a0", "e5fe097", "補記：W1-0 opt-in 決定性"):
        assert needle in note, needle
