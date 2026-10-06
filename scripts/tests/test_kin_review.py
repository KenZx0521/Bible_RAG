"""K9 kinship review tool (scripts/tools/kin_review.py, batch 1A-T3).

Sample mode runs on a small 6.05-shaped world built here: relations_clean
rows of the three pooled sources (anchored_rule with a verse, llm with an
evidence span that may cross a verse mark, prior with a 「創 21:3」
citation), entities, mentions at verse, pericope and chunk level, pericopes
with '**N**' verse marks and frozen descriptions. Score mode runs on
hand-made samples and label files, so k and n are chosen exactly.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from scripts.tools import kin_review as kr

GENEALOGY = "1ch:1:0"
FATHERS = [f"person:fu{i}" for i in range(12)]
SONS = [f"person:zi{i}" for i in range(12)]
PERICOPES = [
    {"id": "gen:21:0", "parent_id": "gen:21", "title": "以撒出生",
     "content": "**1** 耶和華眷顧撒拉。\n\n**3** 亞伯拉罕給撒拉所生的兒子起名叫以撒。\n\n"},
    {"id": "rut:4:1", "parent_id": "rut:4", "title": "大衛的家譜",
     "content": "**21** 撒門生波阿斯；波阿斯生俄備得；\n\n**22** 俄備得生耶西；耶西生大衛。"},
    {"id": GENEALOGY, "parent_id": "1ch:1", "title": "家譜",
     "content": "".join(f"**{i + 1}** 父{i}的兒子是子{i}。\n\n" for i in range(12)) + "**13** 子0生孫0。\n\n"},
]
NAMES = {"person:yabolahan": "亞伯拉罕", "person:yisa": "以撒", "person:sala": "撒拉",
         "person:bo": "波阿斯", "person:ebeide": "俄備得", "person:yexi": "耶西",
         **{f: f"父{i}" for i, f in enumerate(FATHERS)}, **{s: f"子{i}" for i, s in enumerate(SONS)},
         "person:sun0": "孫0"}
# The fields and values that would tell a labeller where a row came from.
SOURCE_TELLS = ("source", "sources", "notes", "pattern", "extraction_phase", "run_id", "model",
                "confidence_raw", "pp_version", "evidence_span")


def _row(head, relation, tail, source, **extra) -> dict:
    phase = {"anchored_rule": 6, "llm": 4, "prior": 3}[source]
    return {"head_id": head, "relation": relation, "tail_id": tail, "source": source,
            "sources": [source], "extraction_phase": phase, "run_id": f"run-{source}",
            "pp_version": "pp-test", "notes": "", "evidence_span": "", "source_pericope_id": "",
            **extra}


def _anchored(i) -> dict:
    return _row(SONS[i], "SON_OF", FATHERS[i], "anchored_rule", notes="P1_child_of",
                source_pericope_id=GENEALOGY, verse=i + 1, confidence_raw=None)


ROWS = [
    *(_anchored(i) for i in range(12)),
    # zi0's second row: by (head, relation, tail) it sorts before zi0 SON_OF fu0, by (head, tail,
    # relation) after it, so the pool order the seed draws from depends on the documented key
    _row("person:zi0", "FATHER_OF", "person:sun0", "anchored_rule", notes="P3_begot",
         source_pericope_id=GENEALOGY, verse=13, confidence_raw=None),
    _row("person:yisa", "SON_OF", "person:yabolahan", "anchored_rule", notes="P2_is_child_of",
         source_pericope_id="gen:21:0", verse=3),
    _row("person:bo", "FATHER_OF", "person:ebeide", "llm", source_pericope_id="rut:4:1",
         evidence_span="波阿斯生俄備得；\n\n**22** 俄備得生耶西", model="unknown", confidence_raw=0.8),
    _row("person:yexi", "FATHER_OF", "person:ebeide", "llm", source_pericope_id="rut:4:1",
         evidence_span="不在經文裡的句子", confidence_raw=0.7),
    _row("person:yabolahan", "VISITED", "place:jiana", "llm", source_pericope_id="gen:21:0"),
    _row("person:yabolahan", "FATHER_OF", "person:yisa", "prior", evidence_span="創 21:3",
         sources=["anchored_rule", "prior"], confidence_raw=0.99),
    _row("person:yabolahan", "SPOUSE_OF", "person:sala", "prior", evidence_span="創 99:1"),
]


def _mention(eid, source_id, source_type) -> dict:
    return {"entity_id": eid, "source_id": source_id, "source_type": source_type}


MENTIONS = [
    *(_mention("person:yabolahan", f"gen:21:0:v:{v}", "verse") for v in (1, 3, 3)),
    _mention("person:yabolahan", "gen:21:0", "pericope"),
    _mention("person:yabolahan", "rut:4:1", "pericope"),
    _mention("person:yabolahan", "1ch:1:0:0", "chunk"),
    _mention("person:yabolahan", "1ch:1:0:1", "chunk"),
    _mention("person:yisa", "gen:21:0:v:3", "verse"),
]


def _jsonl(path, rows) -> str:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def world(tmp_path, rows=ROWS) -> list[str]:
    """The sample-mode input flags over the fixture world."""
    entities = [{"entity_id": eid, "type": "Person", "canonical_name": name,
                 "aliases": ["亞伯蘭"] if eid == "person:yabolahan" else []}
                for eid, name in NAMES.items()]
    entities.append({"entity_id": "place:jiana", "type": "Place", "canonical_name": "迦南", "aliases": []})
    descriptions = [{"entity_id": "person:yabolahan", "description": "以色列的先祖。"}]
    return ["--clean", _jsonl(tmp_path / "relations_clean.jsonl", rows),
            "--entities", _jsonl(tmp_path / "entities.jsonl", entities),
            "--mentions", _jsonl(tmp_path / "entity_mentions.jsonl", MENTIONS),
            "--pericopes", _jsonl(tmp_path / "pericopes.jsonl", PERICOPES),
            "--descriptions", _jsonl(tmp_path / "descriptions.jsonl", descriptions)]


def run(argv) -> int:
    """main's exit code, a usage error (argparse's SystemExit) included."""
    try:
        return kr.main(argv)
    except SystemExit as stop:
        return stop.code


def sample(tmp_path, *flags, rows=ROWS, name="sample.json", code=0):
    out = tmp_path / name
    assert run(["--mode", "sample", *world(tmp_path, rows), *flags, "--out", str(out)]) == code
    return json.loads(out.read_text(encoding="utf-8")) if code == 0 else None


def _keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _keys(value)


# --- sample mode ---------------------------------------------------------------

def test_sample_is_deterministic_for_a_seed(tmp_path):
    first = sample(tmp_path, "--source", "anchored_rule", "--n", "5", "--seed", "20261005")
    again = sample(tmp_path, "--source", "anchored_rule", "--n", "5", "--seed", "20261005", name="again.json")
    assert (tmp_path / "sample.json").read_bytes() == (tmp_path / "again.json").read_bytes()

    pool = sorted([r for r in ROWS if r["source"] == "anchored_rule"],
                  key=lambda r: (r["head_id"], r["relation"], r["tail_id"]))
    drawn = random.Random(20261005).sample(pool, 5)
    keys = ["\t".join((r["head_id"], r["relation"], r["tail_id"])) for r in drawn]
    assert [i["item_id"] for i in first["items"]] == [hashlib.sha1(k.encode()).hexdigest()[:12] for k in keys]
    assert first["meta"]["pool_size"] == 14 and first["meta"]["seed"] == 20261005
    assert first["meta"]["pool_sha256"] == hashlib.sha256("".join(
        "\t".join((r["head_id"], r["relation"], r["tail_id"])) + "\n" for r in pool).encode()).hexdigest()
    clean = (tmp_path / "relations_clean.jsonl").read_bytes()
    assert first["meta"]["clean_sha256"] == hashlib.sha256(clean).hexdigest()

    # Row order in the file does not matter (the pool is sorted by key); another seed draws another sample.
    shuffled = random.Random(1).sample(ROWS, len(ROWS))
    moved = sample(tmp_path, "--source", "anchored_rule", "--n", "5", "--seed", "20261005",
                   rows=shuffled, name="moved.json")
    assert moved["items"] == again["items"] and moved["meta"]["pool_sha256"] == again["meta"]["pool_sha256"]
    other = sample(tmp_path, "--source", "anchored_rule", "--n", "5", "--seed", "7", name="other.json")
    assert [i["item_id"] for i in other["items"]] != [i["item_id"] for i in first["items"]]


def test_sample_is_blind(tmp_path):
    doc = sample(tmp_path, "--source", "anchored_rule", "--all", "--seed", "3")
    assert set(doc) == {"format", "meta", "items"}
    assert set(doc["meta"]) == {"seed", "pool_size", "pool_sha256", "clean_sha256", "inputs_sha256", "rubric"}
    assert set(doc["meta"]["rubric"]) == {"text_correct", "id_correct"}
    assert len(doc["items"]) == 14
    for item in doc["items"]:
        assert set(item) == {"item_id", "relation", "head", "tail", "evidence"}
        assert set(item["head"]) == set(item["tail"]) == {
            "id", "canonical_name", "aliases", "description", "top_pericopes", "mention_books"}
        assert set(item["evidence"]) == {"pericope_id", "title", "verse", "verse_text"}
    assert not set(_keys(doc)) & set(SOURCE_TELLS)
    text = json.dumps(doc, ensure_ascii=False)
    for tell in ("anchored_rule", "P1_child_of", "P2_is_child_of", "P3_begot", "run-anchored_rule", "pp-test"):
        assert tell not in text


def test_pool_is_the_kinship_rows_of_the_primary_source(tmp_path):
    pools = {source: sample(tmp_path, "--source", source, "--all", "--seed", "1")["meta"]["pool_size"]
             for source in ("anchored_rule", "llm", "prior")}
    # llm's VISITED row is not kinship; the prior row whose sources include anchored_rule counts as prior.
    assert pools == {"anchored_rule": 14, "llm": 2, "prior": 2}
    assert sample(tmp_path, "--source", "llm", "--n", "3", "--seed", "1", code=2) is None


def test_sample_items_show_the_kg_endpoints_and_the_verse(tmp_path):
    items = {(i["head"]["id"], i["relation"], i["tail"]["id"]): i
             for source in ("anchored_rule", "llm", "prior")
             for i in sample(tmp_path, "--source", source, "--all", "--seed", "1")["items"]}
    abraham = items[("person:yisa", "SON_OF", "person:yabolahan")]["tail"]
    assert abraham["canonical_name"] == "亞伯拉罕" and abraham["aliases"] == ["亞伯蘭"]
    assert abraham["description"] == "以色列的先祖。"
    # Mention rows per pericope (verse ids split at ':v:', chunks roll up to their pericope), ties by id.
    assert abraham["top_pericopes"] == [{"pericope_id": "gen:21:0", "title": "以撒出生", "mentions": 4},
                                        {"pericope_id": "1ch:1:0", "title": "家譜", "mentions": 2},
                                        {"pericope_id": "rut:4:1", "title": "大衛的家譜", "mentions": 1}]
    assert abraham["mention_books"] == [["gen", 4], ["1ch", 2], ["rut", 1]]
    assert items[("person:yisa", "SON_OF", "person:yabolahan")]["head"]["description"] is None

    assert items[("person:yisa", "SON_OF", "person:yabolahan")]["evidence"] == {
        "pericope_id": "gen:21:0", "title": "以撒出生", "verse": 3, "verse_text": "亞伯拉罕給撒拉所生的兒子起名叫以撒。"}
    assert items[("person:bo", "FATHER_OF", "person:ebeide")]["evidence"] == {
        "pericope_id": "rut:4:1", "title": "大衛的家譜", "verse": 21,
        "verse_text": "撒門生波阿斯；波阿斯生俄備得； 俄備得生耶西；耶西生大衛。"}
    assert items[("person:yexi", "FATHER_OF", "person:ebeide")]["evidence"] == {
        "pericope_id": "rut:4:1", "title": "大衛的家譜", "verse": None, "verse_text": "不在經文裡的句子"}
    assert items[("person:yabolahan", "FATHER_OF", "person:yisa")]["evidence"] == {
        "pericope_id": "gen:21:0", "title": "以撒出生", "verse": 3, "verse_text": "亞伯拉罕給撒拉所生的兒子起名叫以撒。"}
    assert items[("person:yabolahan", "SPOUSE_OF", "person:sala")]["evidence"] == {
        "pericope_id": None, "title": None, "verse": None, "verse_text": "創 99:1"}


def test_sample_refuses_inconsistent_inputs(tmp_path, capsys):
    lost = [*ROWS, _row("person:nobody", "SON_OF", "person:yisa", "anchored_rule",
                        source_pericope_id="gen:21:0", verse=3)]
    assert sample(tmp_path, "--source", "anchored_rule", "--all", "--seed", "1", rows=lost, code=2) is None
    assert "1 endpoints are not in" in capsys.readouterr().err
    no_verse = [*ROWS, _row("person:sala", "DAUGHTER_OF", "person:yisa", "anchored_rule",
                            source_pericope_id="gen:21:0", verse=9)]
    assert sample(tmp_path, "--source", "anchored_rule", "--all", "--seed", "1",
                  rows=no_verse, code=2) is None
    assert "verse [9] is not in pericope gen:21:0" in capsys.readouterr().err
    assert run(["--mode", "sample", *world(tmp_path), "--source", "llm", "--all", "--seed", "1",
                "--labels", "x.jsonl", "--out", str(tmp_path / "s.json")]) == 2  # a score-mode flag


# --- score mode ----------------------------------------------------------------

def write_sample(tmp_path, n) -> str:
    items = [{"item_id": f"item{i:03d}", "relation": "SON_OF"} for i in range(n)]
    doc = {"format": kr.SAMPLE_FORMAT, "meta": {"seed": 1, "pool_size": n, "pool_sha256": "0" * 64,
                                                 "clean_sha256": "1" * 64, "inputs_sha256": {},
                                                 "rubric": kr.RUBRIC},
           "items": items}
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def write_labels(tmp_path, name, labels, annotator) -> str:
    """labels: [(text_correct, id_correct)] in item order, or {index: (text, id)} for a subset."""
    pairs = labels.items() if isinstance(labels, dict) else enumerate(labels)
    return _jsonl(tmp_path / name, [{"item_id": f"item{i:03d}", "text_correct": t, "id_correct": d,
                                     "annotator": annotator, "note": ""} for i, (t, d) in pairs])


def counted(n, text_true, id_true) -> list[tuple[bool, bool]]:
    return [(i < text_true, i < id_true) for i in range(n)]


def score(tmp_path, labels_a, labels_b, *flags, n=60, code=0):
    out = tmp_path / "report.json"
    out.unlink(missing_ok=True)
    argv = ["--mode", "score", "--sample", write_sample(tmp_path, n),
            "--labels", write_labels(tmp_path, "a.jsonl", labels_a, "ai:session-a"),
            "--labels", write_labels(tmp_path, "b.jsonl", labels_b, "ai:session-b"),
            *flags, "--out", str(out)]
    assert run(argv) == code
    return json.loads(out.read_text(encoding="utf-8")) if out.exists() else None


@pytest.mark.parametrize("k, n, bound", [(40, 40, 0.912), (39, 40, 0.871), (57, 60, 0.863), (51, 60, 0.739)])
def test_wilson_lower_bound(k, n, bound):
    assert round(kr.wilson_lower_bound(k, n), 3) == bound


def test_cohen_kappa():
    a = [True] * 6 + [False] * 4
    b = [False] + [True] * 5 + [False] * 3 + [True]
    assert round(kr.cohen_kappa(a, b), 4) == 0.5833      # po 0.8, pe 0.52
    assert kr.cohen_kappa([True] * 5, [True] * 5) is None   # pe = 1: κ undefined


def test_disagreement_without_adjudication_exits_2(tmp_path, capsys):
    labels = counted(60, 57, 51)
    other = list(labels)
    other[3] = (False, False)                                  # B: item003 text and id wrong
    assert score(tmp_path, labels, other, code=2) is None      # nothing written
    assert "item003: the labellings disagree" in capsys.readouterr().err

    adjudication = write_labels(tmp_path, "c.jsonl", {3: (True, True)}, "ai:session-c")
    report = score(tmp_path, labels, other, "--adjudication", adjudication)
    assert report["disagreements"] == [{
        "item_id": "item003", "fields": ["id_correct", "text_correct"],
        "labels": [{"text_correct": True, "id_correct": True}, {"text_correct": False, "id_correct": False}],
        "final": {"text_correct": True, "id_correct": True}}]
    assert report["fields"]["text_correct"]["k"] == 57 and report["fields"]["id_correct"]["k"] == 51
    assert report["agreement"]["text_correct"]["raw"] == pytest.approx(59 / 60)
    assert report["agreement"]["text_correct"]["kappa"] == pytest.approx(kr.cohen_kappa(
        [t for t, _ in labels], [t for t, _ in other]))

    agreed = write_labels(tmp_path, "c.jsonl", {3: (True, True), 4: (True, True)}, "ai:session-c")
    assert score(tmp_path, labels, other, "--adjudication", agreed, code=2) is None  # item004 was agreed
    assert "items the labellings agree on: ['item004']" in capsys.readouterr().err


def test_gate_field_and_exit_codes(tmp_path):
    labels = counted(60, 57, 51)
    report = score(tmp_path, labels, labels)                   # default field text_correct (Q1)
    assert report["gate"] == {"field": "text_correct", "min_lb": 0.85, "report_only": False,
                              "wilson_lb": pytest.approx(0.863, abs=5e-4), "pass": True}
    assert report["annotation"] == "非人工（AI 雙盲＋裁決，Kay 抽查）"
    assert report["n"] == 60 and report["fields"]["id_correct"]["wilson_lb"] == pytest.approx(0.739, abs=5e-4)
    assert report["exit"] == 0 and report["disagreements"] == []
    assert report["agreement"]["id_correct"] == {"raw": 1.0, "kappa": 1.0}

    failed = score(tmp_path, labels, labels, "--gate-field", "id_correct", code=1)
    assert failed["gate"]["pass"] is False and failed["exit"] == 1
    assert score(tmp_path, labels, labels, "--min-lb", "0.9", code=1)["gate"]["min_lb"] == 0.9
    only = score(tmp_path, labels, labels, "--gate-field", "id_correct", "--report-only")
    assert only["gate"]["report_only"] is True and only["gate"]["min_lb"] is None and only["exit"] == 0

    assert report["sample"] == {"seed": 1, "pool_size": 60, "pool_sha256": "0" * 64, "clean_sha256": "1" * 64}
    hashes = report["inputs"]
    assert [x["annotator"] for x in hashes["labels"]] == ["ai:session-a", "ai:session-b"]
    assert hashes["sample"]["sha256"] == hashlib.sha256((tmp_path / "sample.json").read_bytes()).hexdigest()
    assert score(tmp_path, labels, labels, "--min-lb", "0.85", "--report-only", code=2) is None


def test_spotcheck_section(tmp_path):
    labels = counted(60, 57, 51)
    # item055: A (T, T) and B (F, F) disagree, the adjudication's (T, F) is final, and Kay's (T, F)
    # agrees with it alone; item052 differs from the final label on id_correct only, item058 on both.
    a, b = list(labels), list(labels)
    a[55], b[55] = (True, True), (False, False)
    adjudication = write_labels(tmp_path, "c.jsonl", {55: (True, False)}, "ai:session-c")
    spot = write_labels(tmp_path, "k.jsonl", {0: (True, True), 52: (True, True), 55: (True, False),
                                              58: (True, True)}, "kay")
    report = score(tmp_path, a, b, "--adjudication", adjudication, "--spotcheck", spot)
    assert report["disagreements"][0]["final"] == {"text_correct": True, "id_correct": False}
    assert report["spotcheck"] == {"n": 4, "agree": 2, "disagree": ["item052", "item058"], "annotator": "kay"}
    assert report["inputs"]["spotcheck"]["path"] == spot
    none = {"n": 0, "agree": 0, "disagree": [], "annotator": None}
    assert score(tmp_path, labels, labels)["spotcheck"] == none
    unknown = write_labels(tmp_path, "k.jsonl", {60: (True, True)}, "kay")
    assert score(tmp_path, labels, labels, "--spotcheck", unknown, code=2) is None


REFUSALS = {"missing": "lacks 1 items", "duplicate": "item000 is labelled twice",
            "same_annotator": "must be double-blind", "not_ai": "is not 'ai:<session>'",
            "id_without_text": "id_correct without text_correct", "not_bool": "needs true/false",
            "one_file": "needs --sample and --labels twice"}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_bad_labels_exit_2(tmp_path, capsys, case):
    good = [{"item_id": f"item{i:03d}", "text_correct": True, "id_correct": True,
             "annotator": "ai:session-b", "note": ""} for i in range(4)]
    bad = [dict(row, annotator="ai:session-a") for row in good]
    if case == "missing":
        bad = bad[:3]
    elif case == "duplicate":
        bad = bad + bad[:1]
    elif case == "same_annotator":
        bad = [dict(row, annotator="ai:session-b") for row in bad]
    elif case == "not_ai":
        bad = [dict(row, annotator="kay") for row in bad]
    elif case == "id_without_text":                            # in both files, so they still agree
        bad[1] = dict(bad[1], text_correct=False)
        good[1] = dict(good[1], text_correct=False)
    elif case == "not_bool":
        bad[2] = dict(bad[2], id_correct="yes")
    argv = ["--mode", "score", "--sample", write_sample(tmp_path, 4),
            "--labels", _jsonl(tmp_path / "a.jsonl", bad), "--out", str(tmp_path / "report.json")]
    if case != "one_file":
        argv[6:6] = ["--labels", _jsonl(tmp_path / "b.jsonl", good)]
    assert run(argv) == 2
    assert not (tmp_path / "report.json").exists()
    assert REFUSALS[case] in capsys.readouterr().err


def test_unwritable_out_exits_2(tmp_path):
    labels = counted(4, 4, 4)
    assert score(tmp_path, labels, labels, "--report-only", n=4)["exit"] == 0
    argv = ["--mode", "score", "--sample", str(tmp_path / "sample.json"), "--report-only",
            "--labels", str(tmp_path / "a.jsonl"), "--labels", str(tmp_path / "b.jsonl"),
            "--out", str(tmp_path / "missing" / "report.json")]
    assert run(argv) == 2                                      # not a traceback's 1 ("below the gate")


def _disagreeing(item3=(False, False)):
    """A's and B's labels of 60 items (text 57, id 51) that differ only on item003."""
    labels = counted(60, 57, 51)
    other = list(labels)
    other[3] = item3
    return labels, other


@pytest.mark.parametrize("case", ["adjudicator_is_a", "adjudicator_is_b", "ai_spotcheck"])
def test_adjudication_by_a_third_session_and_spotcheck_by_kay(tmp_path, capsys, case):
    """C9b: a third session adjudicates, and the spot-check the report calls 「Kay 抽查」 is Kay's."""
    labels, other = _disagreeing()
    who = {"adjudicator_is_a": "ai:session-a", "adjudicator_is_b": "ai:session-b"}.get(case, "ai:session-c")
    flags = ["--adjudication", write_labels(tmp_path, "c.jsonl", {3: (True, True)}, who)]
    if case == "ai_spotcheck":
        flags += ["--spotcheck", write_labels(tmp_path, "k.jsonl", {0: (True, True)}, "ai:session-c")]

    assert score(tmp_path, labels, other, *flags, code=2) is None           # nothing written

    err = capsys.readouterr().err
    assert ("is Kay's" if case == "ai_spotcheck" else "must be a third session") in err, err
    assert score(tmp_path, labels, other, flags[0], write_labels(tmp_path, "c.jsonl", {3: (True, True)},
                                                                 "ai:session-c"))["exit"] == 0


def test_adjudication_replaces_both_fields_of_an_item(tmp_path):
    """Per item, not per field: A and B agree on text_correct and differ on id_correct, and the
    adjudication row still sets both; under the rubric it can only lower text_correct."""
    labels, other = _disagreeing(item3=(True, False))                       # A (T, T), B (T, F)
    adjudication = write_labels(tmp_path, "c.jsonl", {3: (False, False)}, "ai:session-c")

    report = score(tmp_path, labels, other, "--adjudication", adjudication, code=1)

    assert report["disagreements"] == [{
        "item_id": "item003", "fields": ["id_correct"],
        "labels": [{"text_correct": True, "id_correct": True}, {"text_correct": True, "id_correct": False}],
        "final": {"text_correct": False, "id_correct": False}}]
    assert report["fields"]["text_correct"]["k"] == 56                      # 57 agreed true, one overridden
    assert "replaces both fields of the item" in " ".join(kr.__doc__.split())


def _score_argv(tmp_path, out, *flags) -> list[str]:
    labels, other = _disagreeing()
    return ["--mode", "score", "--sample", write_sample(tmp_path, 60),
            "--labels", write_labels(tmp_path, "a.jsonl", labels, "ai:session-a"),
            "--labels", write_labels(tmp_path, "b.jsonl", other, "ai:session-b"), *flags, "--out", str(out)]


def test_failed_rerun_leaves_no_earlier_report(tmp_path, capsys):
    """A report at --out is from this run or not there: K9 evidence is hashed from that path."""
    out = tmp_path / "report.json"
    adjudication = write_labels(tmp_path, "c.jsonl", {3: (True, True)}, "ai:session-c")
    assert run(_score_argv(tmp_path, out, "--adjudication", adjudication)) == 0 and out.exists()

    assert run(_score_argv(tmp_path, out)) == 2                             # the adjudication left out

    assert not out.exists() and not list(tmp_path.glob("*.tmp"))
    assert "--adjudication has no row" in capsys.readouterr().err


def test_failed_write_leaves_no_partial_report(tmp_path, monkeypatch):
    out = tmp_path / "report.json"
    adjudication = write_labels(tmp_path, "c.jsonl", {3: (True, True)}, "ai:session-c")

    def refuse(src, dst):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(kr.os, "replace", refuse)

    assert run(_score_argv(tmp_path, out, "--adjudication", adjudication)) == 2

    assert not out.exists() and not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("which", ["sample", "labels", "adjudication", "temp"])
def test_out_over_an_input_is_a_usage_error(tmp_path, capsys, which):
    """--out is removed before a run and replaced through <out>.tmp: neither may be an input."""
    adjudication = Path(write_labels(tmp_path, "c.tmp", {3: (True, True)}, "ai:session-c"))
    out = {"sample": tmp_path / "sample.json", "labels": tmp_path / "a.jsonl",
           "adjudication": adjudication, "temp": tmp_path / "c"}[which]       # c's temp file is c.tmp
    argv = _score_argv(tmp_path, out, "--adjudication", str(adjudication))
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}

    assert run(argv) == 2

    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert "is an input" in capsys.readouterr().err
