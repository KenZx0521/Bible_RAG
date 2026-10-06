"""Pins of Kay's 2026-10-06 decisions in the W1 runbook (Q6, Q7, Q8, Q9, Q10).

docs/staging_promotion.md sat at the 800-line limit, so R3's W1 promotion
(step 1, the /api/v1/entity before/after, the opt-in A/B window and step 2)
moved to docs/staging_promotion_w1.md; test_docs_alignment's staging_text()
reads the two as one text, and every main-doc reference to a moved section
links the new doc. Q6 confirms O7: W1 staging writes bible_entities_v3, and
check_w1_registration refuses, before Step 3, a HEAD staging.env or a shell
naming anything else, so 8a/8b never --recreate the batch-0 control v2; R0
item 8, the inventory row, the chain row and R1 item 5 say so. Q7 confirms O5
and decides M390: R0 backs up the batch-0 staging (a neo4j-staging dump and a
pg_dump -Fc of bible_rag_staging, fail-closed, once) after E1 and before R1
touches staging, and a rejection at W1 step 4 restores exactly those dumps
before E1 is rerun. Q10 decides M364: K8's P1 control runs after R4 for the
real reason (one staging; :w1 built at R2; the step 1-2 A/B window needs W1
data on staging), not because residuals_expect forbids every earlier slot.
Q8 and Q9 amend K9's pre-registration before any labelling: Kay's spot-check
replaces the final labels before the gate, kin_review refuses a short
spot-check before judging the gate (--min-spotcheck-extra 10, the jq stays as
an independent check), every report gives before/after numbers, the overrides
and the identity rate among the text_correct items, and llm/prior items carry
the verse before and after the evidence as context while anchored samples
and their rubric stay as registered; plan §9.1 notes both.
"""
from __future__ import annotations

import re
import shlex

import pytest
import yaml
from scripts.tools import check_w1_registration as cwr
from scripts.tools import kin_review as kr
from scripts.tools import residuals_expect as rx
from test_docs_alignment import (DOC, ROOT, STAGING_DOC, STAGING_W1_DOC, _assert_fail_closed, _blocks, _commands,
                                 _first, _in_order, _rebuild_chain, headings, help_text, mask_code, read, section,
                                 staging_text)
from test_docs_alignment_w1 import W1A, _bash, _block, _item

MOVED = ("W1 升版第 1 步", "W1 的 /api/v1/entity 比對", "W1 升版第 1、2 步之間", "W1 升版第 2 步")
KAY = "W1 第 4 步：Kay 核可"
K8 = "W1 的 K8 對照組"
PLAN1 = ROOT / "docs" / "records" / "2026-10-04_kg_batch1_plan.md"
W1_README = ROOT / "evaluation" / "experiments" / "2026-10-05_kg_w1" / "README.md"
NEO4J_DUMP = "bak/$D/neo4j_staging/neo4j.dump"
PG_DUMP = "bak/$D/postgres/bible_rag_staging.dump"
SUMS = ("./neo4j_staging/neo4j.dump", "./postgres/bible_rag_staging.dump")
PENDING = ("待 Kay 確認", "PENDING", "一併待 Kay 決定")


# ---------------------------------------------------------------- (0) room: the W1 promotion in its own doc

def test_the_staging_runbook_leaves_room_below_760_lines():
    assert len(read(STAGING_DOC).splitlines()) <= 760
    assert len(read(STAGING_W1_DOC).splitlines()) <= 800


def test_the_w1_promotion_sections_live_in_their_own_doc_in_order():
    main, w1 = headings(read(STAGING_DOC)), headings(read(STAGING_W1_DOC))
    assert not [h for h in main for m in MOVED if h.startswith(m)], main
    at = [next(i for i, h in enumerate(w1) if h.startswith(m)) for m in MOVED]
    assert at == sorted(at) and at[0] == 1, w1   # right under the doc's own title
    assert re.match(r"# \S", read(STAGING_W1_DOC)) and read(STAGING_W1_DOC).count("\n# ") == 0
    intro = read(STAGING_W1_DOC).split("\n## ", 1)[0]
    for needle in ("](staging_promotion.md)", "R3", "2026-10-06", "R4"):
        assert needle in intro, needle


def test_every_reference_to_a_moved_section_links_the_w1_doc():
    named = re.compile("「(?:" + "|".join(map(re.escape, MOVED)) + ")")
    main = [line for line in mask_code(read(STAGING_DOC)).splitlines() if named.search(line)]
    assert main and not [line for line in main if "](staging_promotion_w1.md)" not in line], main
    readme = [line for line in read(W1_README).splitlines() if named.search(line)]
    assert len(readme) >= 3 and all("`docs/staging_promotion_w1.md`" in line for line in readme), readme


# ---------------------------------------------------------------- (1) Q6: O7 confirmed, the v3 pre-flight

@pytest.mark.parametrize("path", (STAGING_DOC, STAGING_W1_DOC, DOC, PLAN1), ids=lambda p: p.name)
def test_no_pending_marker_is_left_on_o7_o5_or_m390(path):
    left = [line for line in read(path).splitlines() if any(mark in line for mark in PENDING)]
    assert not left, left


def test_r0_item_8_states_the_fail_closed_v3_preflight():
    item = _item(section(staging_text(), "R0"), "8")
    for needle in ("Q6", "Kay 2026-10-06", "check_w1_registration", "`scripts/tools/staging.env`",
                   f"`{cwr.COLLECTION_VAR}`", f"`{cwr.W1_COLLECTION}`", f"`{cwr.BATCH0_COLLECTION}`", "HEAD",
                   "INVALID", "結束碼 1", "Step 3 之前", "`--recreate`"):
        assert needle in item, needle


def test_the_inventory_chain_and_r1_name_the_collection_row():
    inventory = next(line for line in read(STAGING_DOC).splitlines() if line.startswith("| tools/check_w1_registration"))
    chain = " ".join({row[0]: row for row in _rebuild_chain(read(DOC))[1]}["check_w1_registration"])
    prereg = next(line for line in section(read(DOC), "執行順序").splitlines() if line.startswith("- **事前登記**"))
    r1 = _item(section(staging_text(), "R1"), "5")
    for text in (inventory, chain, prereg, r1):
        for needle in (cwr.COLLECTION_VAR, cwr.W1_COLLECTION, "staging.env"):
            assert needle in text, (needle, text[:60])
    assert inventory.count("| — ") >= 3, inventory   # still reads no database
    assert (ROOT / cwr.STAGING_ENV).is_file() and cwr.STAGING_ENV == "scripts/tools/staging.env"


# ---------------------------------------------------------------- (2) Q7: back up the batch-0 staging, restore on rejection

def _backup() -> list[str]:
    return _blocks(_item(section(staging_text(), "R0"), "9"))[0]


def _restore() -> list[str]:
    return next(b for b in _blocks(section(staging_text(), KAY)) if any("database load" in c for c in b))


def test_r0_item_9_backs_up_the_batch0_staging_between_e1_and_r1():
    item = _item(section(staging_text(), "R0"), "9")
    for needle in ("Q7", "Kay 2026-10-06", "E1", "R1 第 2 項", "Step 5", f"「{KAY}」", "Qdrant", "`bible_entities_v2`",
                   "乾淨的 shell", "只做一次", "SHA256SUMS", "`.part`", "`docker start bible_rag_neo4j_staging`"):
        assert needle in item, needle
    block = _backup()
    _assert_fail_closed(block, "batch-0 staging backed up")
    _in_order(block, (f"test ! -e {NEO4J_DUMP}", f"test ! -e {PG_DUMP}", 'test "$N" = 0',
                      f"pg_dump -U bible -d bible_rag_staging -Fc > {PG_DUMP}.part", f"test -s {PG_DUMP}.part",
                      "docker stop -t 60 bible_rag_neo4j_staging", f"database dump neo4j --to-stdout > {NEO4J_DUMP}.part",
                      f"test -s {NEO4J_DUMP}.part", "docker start bible_rag_neo4j_staging", f"mv {PG_DUMP}.part {PG_DUMP}",
                      f"mv {NEO4J_DUMP}.part {NEO4J_DUMP}", f"(cd bak/$D && sha256sum {' '.join(SUMS)} >> SHA256SUMS)"))
    # the batch-0 test is residuals_expect's own: no semantic edge with a source
    query = next(c for c in block if c.startswith('Q="'))[3:-1]
    assert " ".join(query.split()) == " ".join(rx.SOURCED_EDGES_CYPHER.split()), query
    assert "R0 第 9 項" in _item(section(staging_text(), "R1"), "2")
    assert "R0 第 9 項" in _item(section(staging_text(), "W1 的關係層檢查"), "2")


def test_backup_and_restore_name_the_staging_container_volume_image_and_database():
    compose = yaml.safe_load(read(ROOT / "docker-compose.staging.yml"))
    neo4j = compose["services"]["neo4j-staging"]
    volume = compose["volumes"][neo4j["volumes"][0].split(":")[0]]["name"]
    assert (neo4j["container_name"], volume, neo4j["image"]) == (
        "bible_rag_neo4j_staging", "bible_rag_neo4j_staging_data", "neo4j:5.15-community")
    assert re.search(r"^export POSTGRES_DB=bible_rag_staging$", read(ROOT / cwr.STAGING_ENV), re.M)
    r3 = _commands(section(read(STAGING_DOC), "R3"))   # the generic dump and load, R3 step 1
    dump = next(c for c in r3 if "database dump" in c).replace("bak/$D/promote/neo4j_staging.dump", f"{NEO4J_DUMP}.part")
    load = next(c for c in r3 if "database load" in c).replace("bible_rag_neo4j_data", volume).replace(
        "bak/$D/promote/neo4j_staging.dump", NEO4J_DUMP)
    assert dump in _backup() and load in _restore(), (dump, load)
    stops = [c for c in _backup() + _restore() if re.match(r"docker (stop|start) ", c)]
    assert len(stops) == 4 and all(c.endswith(" bible_rag_neo4j_staging") for c in stops), stops


def test_kay_rejection_restores_the_backed_up_staging_before_e1_reruns():
    kay = section(staging_text(), KAY)
    for needle in ("M390", "Q7", "Kay 2026-10-06", "不改任何已登記的檔", "prod 不動", "從頭重跑", "R0 第 9 項", "E1",
                   "residuals_expect", "healthy", "`bible_entities_v3`"):
        assert needle in kay, needle
    assert "再從 Step 5 重建" not in kay   # Step 5 alone would skip check_w1_registration
    block = _restore()
    _assert_fail_closed(block, "staging restored to batch 0")
    _in_order(block, (*(f"(cd bak/$D && grep -F ' {path}' SHA256SUMS | sha256sum -c -)" for path in SUMS),
                      "docker-compose.staging.yml stop backend-staging", "docker stop -t 60 bible_rag_neo4j_staging",
                      f"database load neo4j --from-stdin --overwrite-destination=true < {NEO4J_DUMP}",
                      "docker start bible_rag_neo4j_staging", "dropdb -U bible --if-exists bible_rag_staging",
                      "createdb -U bible bible_rag_staging",
                      f"pg_restore -U bible -d bible_rag_staging --exit-on-error < {PG_DUMP}"))


# a stand-in docker: records each call; the staging query prints SOURCED, psql COUNTS (PG staging's
# entities|entity_mentions), pg_dump PG, neo4j-admin NEO
STUB = """docker() {{ echo "docker $*" >> calls
  case "$*" in
    "exec bible_rag_neo4j_staging "*) printf 'n\\n{sourced}\\n';;
    "exec bible_rag_postgres psql "*) printf '{counts}\\n';;
    "exec bible_rag_postgres pg_dump "*) printf '{pg}';;
    "run --rm "*) printf '{neo}';;
  esac; }}
D=x
"""
BATCH0_COUNTS = "9124|173768"   # bible_rag_staging entities|entity_mentions, read 2026-10-06


def _calls(root) -> list[str]:
    path = root / "calls"
    return path.read_text().splitlines() if path.exists() else []


def stub(sourced="0", counts=BATCH0_COUNTS, pg="PG", neo="NEO") -> str:
    return STUB.format(sourced=sourced, counts=counts, pg=pg, neo=neo)


@pytest.mark.parametrize("sourced, counts, pg, neo, ok", [
    ("0", BATCH0_COUNTS, "PG", "NEO", True), ("5616", BATCH0_COUNTS, "PG", "NEO", False),
    ("0", "0|0", "PG", "NEO", False), ("0", "9120|173896", "PG", "NEO", False), ("0", "", "PG", "NEO", False),
    ("0", BATCH0_COUNTS, "", "NEO", False), ("0", BATCH0_COUNTS, "PG", "", False)],
    ids=["batch-0", "w1-build", "pg-dropped", "pg-step3-only", "pg-unreadable", "empty-pg-dump", "empty-neo4j-dump"])
def test_the_backup_keeps_only_complete_dumps_of_a_batch0_staging(tmp_path, sourced, counts, pg, neo, ok):
    result = _bash(stub(sourced, counts, pg, neo) + "\n".join(_backup()), tmp_path)
    assert (result.returncode == 0) is ok, result
    final = [tmp_path / path.replace("$D", "x") for path in (NEO4J_DUMP, PG_DUMP)]
    assert [p.exists() for p in final] == [ok, ok]
    if sourced != "0" or counts != BATCH0_COUNTS:   # never kept as the batch-0 backup, staging never stopped
        assert not [c for c in _calls(tmp_path) if not c.startswith(("docker exec bible_rag_neo4j_staging",
                                                                     "docker exec bible_rag_postgres psql"))]
    if ok:
        sums = (tmp_path / "bak" / "x" / "SHA256SUMS").read_text().splitlines()
        assert [line.split("  ")[1] for line in sums] == list(SUMS), sums
        assert _bash(stub() + "\n".join(_backup()), tmp_path).returncode != 0
        assert len((tmp_path / "bak" / "x" / "SHA256SUMS").read_text().splitlines()) == 2   # once only


@pytest.mark.parametrize("tamper", [None, NEO4J_DUMP, PG_DUMP])
def test_the_restore_loads_only_the_dumps_the_backup_recorded(tmp_path, tamper):
    assert _bash(stub() + "\n".join(_backup()), tmp_path).returncode == 0
    if tamper:
        (tmp_path / tamper.replace("$D", "x")).write_text("other")
    (tmp_path / "calls").unlink()
    result = _bash(stub() + "\n".join(_restore()), tmp_path)
    assert (result.returncode == 0) is (tamper is None), result
    words = [c.split()[1] for c in _calls(tmp_path)]
    assert words == ([] if tamper else ["compose", "stop", "run", "start", "exec", "exec", "exec"]), words


# ---------------------------------------------------------------- (3) Q10: why K8's P1 waits for R4

def test_k8_timing_states_the_real_constraint():
    why = next(line for line in section(staging_text(), K8).splitlines() if line.startswith("- **為什麼排在 R4 之後**"))
    for needle in ("Q10", "Kay 2026-10-06", "staging 只有一個", "`:w1`", "R2 才建", "W1 升版第 1、2 步之間", "xref",
                   "graph_event", "W1 的建置", "dump", "`bak/$D/promote/`", "](staging_promotion_w1.md)"):
        assert needle in why, needle
    assert "residuals_expect" not in why and "第 0 批" not in why, why


# ---------------------------------------------------------------- (4) Q8, Q9: K9's pre-registration, before labelling

def _k9() -> str:
    return _item(section(staging_text(), W1A), "1")


def test_k9_preregistration_states_q8_and_q9():
    k9 = _k9()
    for needle in ("Q8", "Q9", "Kay 2026-10-06", "M381", "M340", "標註開始之前", f"「{kr.ANNOTATION}」",
                   "取代", "兩欄一起", "抽查前、後", "每一筆改動", "item_id", "最終標籤 → Kay 的標籤",
                   "k_id_given_text", "n_text", "條件身分率", "前一節與後一節", "同一卷", "`context`",
                   "anchored 的 sample 與判準不變", "--min-spotcheck-extra 10", "結束碼 2"):
        assert needle in k9, needle
    assert "kin_review 只報告抽查" not in k9 and "報告標明「非人工」（" not in k9


def test_k9_gate_refuses_a_short_spot_check_before_the_gate_and_keeps_the_jq():
    gate = _block(W1A, "--sample $K/anchored.json")
    score = gate[_first(gate, "kin_review.py --mode score")]
    assert "--spotcheck $K/anchored_kay.jsonl --min-spotcheck-extra 10" in score, score
    assert _first(gate, "kin_review.py --mode score") < _first(gate, "jq -e --slurpfile kay $K/anchored_kay.jsonl")
    reports = [c for c in _commands(section(staging_text(), W1A)) if "kin_review.py --mode score" in c and c != score]
    assert reports and not [c for c in reports if "--spotcheck" in c or "--min-spotcheck-extra" in c], reports
    argv = shlex.split(score.split("kin_review.py", 1)[1].replace("$K", "k9"))
    assert kr.parse_args(argv).min_spotcheck_extra == 10    # the documented line parses as written
    words = " ".join(help_text("kin_review").split())
    for needle in ("--min-spotcheck-extra", "replaces its item's final label", "decision Q8"):
        assert needle in words, needle


PLAN_Q8_Q9 = ("Q8", "Q9", "M381", "M340", "Kay 2026-10-06", "照建議", "取代", "兩欄", "閘門", "抽查前、後",
              "條件身分率", "Wilson", "前一節與後一節", "anchored", "標註開始之前", "](../staging_promotion.md)")


def test_plan_9_1_notes_q8_and_q9_in_kays_2026_10_06_block():
    kay = section(read(PLAN1), "9.1").split("**Kay 的決定（2026-10-06）**", 1)[1]
    note = next(line for line in kay.splitlines() if line.startswith("- **Q8"))
    for needle in PLAN_Q8_Q9:
        assert needle in note, needle
    order = [re.match(r"- \*\*(Q\d+)", line)[1] for line in kay.splitlines() if re.match(r"- \*\*Q\d+", line)]
    assert order == ["Q6", "Q7", "Q8", "Q10", "Q11"], order
