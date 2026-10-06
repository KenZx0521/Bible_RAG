"""K9 kinship review after Kay's 2026-10-06 decisions Q8 and Q9 (scripts/tools/kin_review.py).

Q8 (M381, option a): a --spotcheck row replaces the final label (A and B's
agreement, or the adjudication) of its item, both fields, before the Wilson
bounds and the gate are computed; the report keeps the numbers before the
spot-check, lists every override, and --min-spotcheck-extra N refuses (exit 2,
nothing written) a spot-check that misses an adjudicated item or has fewer
than N others. Q9 (M340): every report gives the identity rate among the final
text_correct items, before and after the spot-check; llm and prior samples
carry the verse before and the verse after the evidence (same book) as a
context field, with a rubric that says so, while anchored_rule samples and
their rubric stay byte-identical to the pre-registered gate protocol.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tools import kin_review as kr
from test_kin_review import (PERICOPES, ROWS, SOURCE_TELLS, _keys, counted, run, sample, score, world,
                             write_labels, write_sample)

# Written by the pre-Q9 kin_review (HEAD a761b19) over test_kin_review's world:
# --source anchored_rule --all --seed 20261007.
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "kin_review" / "anchored_all_seed20261007.json"
SEED = "20261007"
# Neighbours across a pericope, a chapter and a verse gap; another book's verses are never a neighbour.
CONTEXT_PERICOPES = [
    {"id": "1sa:1:0", "parent_id": "1sa:1", "title": "撒母耳出生", "content": "**1** 以法蓮山地有一個以法蓮人。\n\n"},
    {"id": "gen:22:0", "parent_id": "gen:22", "title": "試驗亞伯拉罕", "content": "**1** 這些事以後，上帝要試驗亞伯拉罕。\n\n"},
    *PERICOPES,
    {"id": "rut:4:0", "parent_id": "rut:4", "title": "波阿斯贖產", "content": "**20** 亞米拿達生拿順；拿順生撒門；\n\n"},
]
ITEM_KEYS = {"item_id", "relation", "head", "tail", "evidence"}


def _by_key(doc) -> dict:
    return {(i["head"]["id"], i["relation"], i["tail"]["id"]): i for i in doc["items"]}


# --- Q9 (2): the samples ---------------------------------------------------------

def test_anchored_sample_is_byte_identical_to_the_pre_registered_protocol(tmp_path):
    sample(tmp_path, "--source", "anchored_rule", "--all", "--seed", SEED)

    assert (tmp_path / "sample.json").read_bytes() == GOLDEN.read_bytes()


def test_anchored_items_get_no_context_even_when_neighbours_exist(tmp_path):
    doc = sample(tmp_path, "--source", "anchored_rule", "--all", "--seed", SEED, pericopes=CONTEXT_PERICOPES)

    assert all(set(item) == ITEM_KEYS for item in doc["items"])
    assert doc["meta"]["rubric"] == kr.RUBRIC


def test_llm_and_prior_items_carry_the_verse_before_and_after_the_evidence(tmp_path):
    items = {**_by_key(sample(tmp_path, "--source", "llm", "--all", "--seed", SEED, pericopes=CONTEXT_PERICOPES)),
             **_by_key(sample(tmp_path, "--source", "prior", "--all", "--seed", SEED, pericopes=CONTEXT_PERICOPES,
                              name="prior.json"))}

    assert all(set(item) == ITEM_KEYS | {"context"} for item in items.values())
    # the span covers rut 4:21-22: before is 4:20 in the pericope before; 1sa 1:1 is another book
    assert items[("person:bo", "FATHER_OF", "person:ebeide")]["context"] == {
        "before": {"pericope_id": "rut:4:0", "title": "波阿斯贖產", "verse": 20, "verse_text": "亞米拿達生拿順；拿順生撒門；"},
        "after": None}
    # 創 21:3: the text has no 21:2, so before is 21:1; after crosses into chapter 22
    assert items[("person:yabolahan", "FATHER_OF", "person:yisa")]["context"] == {
        "before": {"pericope_id": "gen:21:0", "title": "以撒出生", "verse": 1, "verse_text": "耶和華眷顧撒拉。"},
        "after": {"pericope_id": "gen:22:0", "title": "試驗亞伯拉罕", "verse": 1,
                  "verse_text": "這些事以後，上帝要試驗亞伯拉罕。"}}
    # evidence that cannot be placed (a span not in the text, an unknown citation) has no neighbours
    for key in (("person:yexi", "FATHER_OF", "person:ebeide"), ("person:yabolahan", "SPOUSE_OF", "person:sala")):
        assert items[key]["context"] == {"before": None, "after": None}, key
    # the evidence itself is what it was
    assert items[("person:bo", "FATHER_OF", "person:ebeide")]["evidence"]["verse"] == 21


def test_a_genealogy_verse_has_no_neighbour_before_the_book_starts(tmp_path):
    rows = [*ROWS, {**ROWS[0], "source": "llm", "sources": ["llm"], "relation": "FATHER_OF",
                    "head_id": "person:fu0", "tail_id": "person:zi0", "verse": None, "notes": "",
                    "evidence_span": "父0的兒子是子0"}]

    item = _by_key(sample(tmp_path, "--source", "llm", "--all", "--seed", SEED, rows=rows))[
        ("person:fu0", "FATHER_OF", "person:zi0")]

    assert item["evidence"]["verse"] == 1
    assert item["context"]["before"] is None and item["context"]["after"]["verse"] == 2


def test_llm_and_prior_rubric_reads_the_evidence_with_its_context(tmp_path):
    rubric = sample(tmp_path, "--source", "prior", "--all", "--seed", SEED)["meta"]["rubric"]

    assert rubric["id_correct"] == kr.RUBRIC["id_correct"]
    text = rubric["text_correct"]
    assert text != kr.RUBRIC["text_correct"] and "evidence" in text
    for needle in ("context", "前一節", "後一節", "同一卷", "只在 context"):
        assert needle in text, needle


def test_context_samples_are_deterministic_and_blind(tmp_path):
    first = sample(tmp_path, "--source", "llm", "--all", "--seed", SEED, pericopes=CONTEXT_PERICOPES)
    sample(tmp_path, "--source", "llm", "--all", "--seed", SEED, pericopes=CONTEXT_PERICOPES, name="again.json")

    assert (tmp_path / "sample.json").read_bytes() == (tmp_path / "again.json").read_bytes()
    assert set(first["meta"]) == {"seed", "pool_size", "pool_sha256", "clean_sha256", "inputs_sha256", "rubric"}
    assert not set(_keys(first)) & set(SOURCE_TELLS)
    text = json.dumps(first, ensure_ascii=False)
    for tell in ("llm", "run-llm", "pp-test", "unknown", "0.8"):
        assert f'"{tell}"' not in text and f": {tell}," not in text, tell


# --- Q8: the spot-check replaces the final label --------------------------------

def test_spotcheck_replaces_the_final_label_before_the_gate(tmp_path):
    labels = counted(60, 57, 51)                     # 57/60: lower bound 0.863, passes without the spot-check
    spot = write_labels(tmp_path, "k.jsonl", {0: (False, False), 10: (True, True), 52: (True, True)}, "kay")

    report = score(tmp_path, labels, labels, "--spotcheck", spot, code=1)

    before, after = report["fields_before_spotcheck"], report["fields"]
    assert (before["text_correct"]["k"], before["id_correct"]["k"]) == (57, 51)
    assert (after["text_correct"]["k"], after["id_correct"]["k"]) == (56, 51)
    assert before["text_correct"]["wilson_lb"] == pytest.approx(0.863, abs=5e-4)
    assert after["text_correct"]["wilson_lb"] == pytest.approx(0.841, abs=5e-4)
    assert report["gate"]["wilson_lb"] == after["text_correct"]["wilson_lb"] and report["gate"]["pass"] is False
    assert report["spotcheck"]["overrides"] == [
        {"item_id": "item000", "field": "text_correct", "final": True, "kay": False},
        {"item_id": "item000", "field": "id_correct", "final": True, "kay": False},
        {"item_id": "item052", "field": "id_correct", "final": False, "kay": True}]
    assert report["spotcheck"]["n"] == 3 and report["spotcheck"]["agree"] == 1
    assert report["spotcheck"]["disagree"] == ["item000", "item052"]


def test_spotcheck_can_lift_the_gate(tmp_path):
    labels = counted(60, 56, 50)                     # 56/60: lower bound 0.841, fails without the spot-check
    spot = write_labels(tmp_path, "k.jsonl", {57: (True, False)}, "kay")

    report = score(tmp_path, labels, labels, "--spotcheck", spot)

    assert report["fields_before_spotcheck"]["text_correct"]["k"] == 56 and report["fields"]["text_correct"]["k"] == 57
    assert report["gate"]["pass"] is True and report["exit"] == 0


def test_spotcheck_overrides_an_adjudicated_label(tmp_path):
    labels = counted(60, 57, 51)
    other = list(labels)
    other[3] = (False, False)                        # A (T, T), B (F, F); the adjudication says (T, T)
    adjudication = write_labels(tmp_path, "c.jsonl", {3: (True, True)}, "ai:session-c")
    spot = write_labels(tmp_path, "k.jsonl", {3: (True, False)}, "kay")

    report = score(tmp_path, labels, other, "--adjudication", adjudication, "--spotcheck", spot)

    assert report["disagreements"][0]["final"] == {"text_correct": True, "id_correct": True}   # before Kay
    assert report["spotcheck"]["overrides"] == [
        {"item_id": "item003", "field": "id_correct", "final": True, "kay": False}]
    assert report["fields_before_spotcheck"]["id_correct"]["k"] == 51 and report["fields"]["id_correct"]["k"] == 50


def test_without_a_spotcheck_before_and_after_are_the_same(tmp_path):
    report = score(tmp_path, counted(60, 57, 51), counted(60, 57, 51))

    assert report["fields_before_spotcheck"] == report["fields"]
    assert report["identity_given_text_before_spotcheck"] == report["identity_given_text"]
    assert report["spotcheck"]["overrides"] == [] and report["spotcheck"]["min_extra"] is None


# --- Q9 (1): the identity rate among the text_correct items ----------------------

def test_identity_rate_given_text_before_and_after_the_spotcheck(tmp_path):
    labels = counted(60, 57, 51)
    spot = write_labels(tmp_path, "k.jsonl", {0: (False, False), 52: (True, True)}, "kay")

    report = score(tmp_path, labels, labels, "--spotcheck", spot, "--report-only")

    before, after = report["identity_given_text_before_spotcheck"], report["identity_given_text"]
    assert before == {"k_id_given_text": 51, "n_text": 57, "p": pytest.approx(51 / 57),
                      "wilson_lb": pytest.approx(kr.wilson_lower_bound(51, 57))}
    assert after == {"k_id_given_text": 51, "n_text": 56, "p": pytest.approx(51 / 56),
                     "wilson_lb": pytest.approx(kr.wilson_lower_bound(51, 56))}


def test_identity_rate_is_undefined_without_a_text_correct_item(tmp_path):
    report = score(tmp_path, counted(4, 0, 0), counted(4, 0, 0), "--report-only", n=4)

    assert report["identity_given_text"] == {"k_id_given_text": 0, "n_text": 0, "p": None, "wilson_lb": None}


def test_the_rendered_summary_shows_before_after_and_the_identity_rate(tmp_path, capsys):
    labels = counted(60, 57, 51)
    score(tmp_path, labels, labels, "--spotcheck", write_labels(tmp_path, "k.jsonl", {0: (False, False)}, "kay"),
          code=1)

    out = capsys.readouterr().out
    for needle in ("before spot-check 57/60", "56/60", "identity given text", "50/56", "before spot-check 51/57",
                   "overrides 2"):
        assert needle in out, (needle, out)


# --- Q8: coverage, enforced by the tool when asked -------------------------------

def _coverage_argv(tmp_path, kay: dict, *flags) -> list[str]:
    labels = counted(60, 57, 51)
    other = list(labels)
    other[3], other[4] = (False, False), (True, False)             # two adjudicated items
    return ["--mode", "score", "--sample", write_sample(tmp_path, 60),
            "--labels", write_labels(tmp_path, "a.jsonl", labels, "ai:session-a"),
            "--labels", write_labels(tmp_path, "b.jsonl", other, "ai:session-b"),
            "--adjudication", write_labels(tmp_path, "c.jsonl", {3: (True, True), 4: (True, True)}, "ai:session-c"),
            "--spotcheck", write_labels(tmp_path, "k.jsonl", kay, "kay"), *flags,
            "--out", str(tmp_path / "report.json")]


@pytest.mark.parametrize("spot, code, err", [
    ([3, 4, *range(10, 20)], 0, None),                              # both adjudicated items and 10 others
    ([3, *range(10, 21)], 2, "does not cover the adjudicated items ['item004']"),
    ([3, 4, *range(10, 19)], 2, "9 items beyond the adjudicated ones, --min-spotcheck-extra wants 10"),
])
def test_min_spotcheck_extra_wants_every_adjudicated_item_plus_n(tmp_path, capsys, spot, code, err):
    argv = _coverage_argv(tmp_path, {i: (True, True) for i in spot}, "--min-spotcheck-extra", "10")

    assert run(argv) == code

    report = tmp_path / "report.json"
    assert report.exists() is (code == 0)
    if err:
        assert err in capsys.readouterr().err
    else:
        cover = json.loads(report.read_text(encoding="utf-8"))["spotcheck"]
        assert (cover["extra"], cover["adjudicated_missing"], cover["min_extra"]) == (10, [], 10)


def test_without_min_spotcheck_extra_the_coverage_is_reported_not_enforced(tmp_path):
    assert run(_coverage_argv(tmp_path, {3: (True, True), 10: (True, True)})) == 0

    cover = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["spotcheck"]
    assert (cover["extra"], cover["adjudicated_missing"], cover["min_extra"]) == (1, ["item004"], None)


@pytest.mark.parametrize("extra, spotcheck, err", [("-1", True, "--min-spotcheck-extra must be >= 0"),
                                                    ("10", False, "--min-spotcheck-extra needs --spotcheck")])
def test_min_spotcheck_extra_usage_errors(tmp_path, capsys, extra, spotcheck, err):
    argv = _coverage_argv(tmp_path, {3: (True, True)}, "--min-spotcheck-extra", extra)
    if not spotcheck:
        at = argv.index("--spotcheck")
        del argv[at:at + 2]

    assert run(argv) == 2

    assert not (tmp_path / "report.json").exists()
    assert err in capsys.readouterr().err


def test_min_spotcheck_extra_is_a_score_flag(tmp_path, capsys):
    argv = ["--mode", "sample", *world(tmp_path), "--source", "llm", "--all", "--seed", SEED,
            "--min-spotcheck-extra", "10", "--out", str(tmp_path / "s.json")]

    assert run(argv) == 2

    assert "--mode sample does not take --min-spotcheck-extra" in capsys.readouterr().err
