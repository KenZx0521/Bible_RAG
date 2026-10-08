"""R2 freeze (experiments/2026-10-09_r2/freeze_r2.py): the offline route simulation that
fixes C3's route-change slice before any R2 result exists.

Unit tests drive the simulation with fake arms; the R1 arm itself is the R1 commit's
code from git, checked against itself on GT v2 when the store is mounted. The R2 run
happens in the integration phase, on the built R2 contracts.
"""

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.heldout import IdMap

_SCRIPT = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-09_r2" / "freeze_r2.py"
_SPEC = importlib.util.spec_from_file_location("freeze_r2", _SCRIPT)
fz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fz)

R1_CONTRACTS = Path("/mnt/ollama-data/bible_rag_store/contracts") / fz.R1_BUILD
needs_store = pytest.mark.skipif(not (R1_CONTRACTS / "manifest.json").is_file(),
                                 reason=f"R1 contracts not mounted ({R1_CONTRACTS})")


@dataclass(frozen=True)
class Signals:
    has_multi_person: bool = False
    has_event_keyword: bool = False
    has_place: bool = False
    detected_book_ids: tuple = ()
    route: str = "fallback"


def select(s, intent=""):
    """The backend's priority, cut down to what the fakes signal."""
    if intent == "cross_reference":
        return "R5"
    if s.has_multi_person:
        return "R3"
    if s.has_event_keyword:
        return "R4"
    return "R6" if s.has_place else "fallback"


def fake_arm(name, vocab, registry=(), books=()):
    """``vocab`` maps a word to the flag it raises; ``registry`` (id, triggers, anchors)."""
    def detect(query, verse_refs, intent_type, entity_names, lexicon, book_ids):
        flags = {flag: True for word, flag in vocab.items() if word in query}
        s = Signals(**flags, detected_book_ids=tuple(b for b in books if b in query))
        return Signals(**{**s.__dict__, "route": select(s, intent_type)})

    events = tuple(SimpleNamespace(id=i, triggers=t, anchors=a) for i, t, a in registry)

    def match_events(query, evs, book_names):
        hits = [(len(e.anchors), n, e) for n, e in enumerate(evs)
                if any(t in query for t in e.triggers)]
        return [e for *_, e in sorted(hits, key=lambda h: h[:2])]

    return fz.Arm(name, None, detect, select, events, match_events, {}, (),
                  {e.id: e.id.replace("event:", "ev") for e in events})


R1_VOCAB = {"摩西": "has_place", "約翰福音": "has_multi_person", "受洗": "has_event_keyword",
            "十災": "has_event_keyword"}
R2_VOCAB = {"摩西": "has_place", "十災": "has_event_keyword", "以利亞": "has_place"}
R1_REG = (("event:0019", ("十災",), ("ps:exo.7.14", "ps:exo.8.1")),)
R2_REG = (("event:0019", ("十災",), ("ps:exo.7.14", "ps:exo.8.1", "ps:exo.8.16")),)


def sim(question, observed=None):
    r1 = fake_arm("R1", R1_VOCAB, R1_REG, books=("約翰福音",))
    r2 = fake_arm("R2", R2_VOCAB, R2_REG, books=("約翰福音", "尼希米記"))
    return fz.simulate(question, [], observed, r1, r2)


# ---------------------------------------------------------------- one question

def test_a_dense_relabel_without_a_lane_changes_nothing():
    row = sim("約翰福音裏的摩西")             # R1: book name read as a person -> R3; R2: R6
    assert (row["R1"]["route"], row["R2"]["route"], row["causes"]) == ("R3", "R6", [])


def test_leaving_a_dense_route_is_a_route_change():
    row = sim("耶穌受洗以後")                 # 受洗 is an orphan keyword in R1 only
    assert (row["R1"]["route"], row["R2"]["route"], row["causes"]) == ("R4", "fallback",
                                                                       ["route"])


def test_new_anchors_change_the_lane_on_the_same_route():
    row = sim("十災是哪十個")
    assert row["R1"]["route"] == row["R2"]["route"] == "R4"
    assert row["causes"] == ["lane"] and row["R2"]["lane"][-1] == "ps:exo.8.16"
    assert row["R1"]["events"] == row["R2"]["events"] == ["ev0019"]


def test_a_book_only_r2_detects_is_a_books_change():
    assert sim("尼希米記怎麼重建城牆")["causes"] == ["books"]


def test_the_observed_llm_contribution_carries_over_to_r2():
    row = sim("以利亞為什麼逃跑", observed="R4")    # R1 query-only fallback; the LLM said event
    assert (row["llm"], row["R1"]["route"], row["R2"]["route"]) == ("event", "R4", "R4")
    assert row["causes"] == []                   # query-only R2 would be R6: no lane either way


def test_an_observation_no_single_contribution_explains_falls_back_to_query_only():
    row = sim("約翰福音裏的摩西", observed="fallback")   # the LLM cannot remove a signal
    assert row["llm"] == "unexplained"
    assert (row["R1"]["route"], row["R2"]["route"]) == ("R3", "R6")


def test_infer_llm_checks_the_contribution_reproduces_the_observation():
    assert fz.infer_llm(None, "R6", lambda c: "x") == ""
    assert fz.infer_llm("R6", "R6", lambda c: "x") == ""
    assert fz.infer_llm("R5", "R6", lambda c: "R5" if c == "xref" else "R6") == "xref"
    assert fz.infer_llm("R4", "R3", lambda c: "R3") is None
    assert fz.infer_llm("R1", "R6", lambda c: "R6") is None


# ---------------------------------------------------------------- the freeze

def test_slice_doc_unions_the_causes_without_the_excluded_ids():
    rows = {"A": {"causes": ["route"], "llm": "", "R1": {"route": "R4"}, "R2": {"route": "R6"}},
            "B": {"causes": ["lane", "books"], "llm": "", "R1": {"route": "R4"},
                  "R2": {"route": "R4"}},
            "C": {"causes": [], "llm": "unexplained", "R1": {"route": "R3"},
                  "R2": {"route": "R6"}},
            "VERSE_LOOKUP_035": {"causes": ["books"], "llm": "", "R1": {"route": "R1"},
                                 "R2": {"route": "R1"}}}
    doc = fz.slice_doc(rows, {"A": "x", "B": "disambiguation", "C": "x",
                              "VERSE_LOOKUP_035": "x"})
    block = doc["route_change_slice"]
    assert block["union"]["question_ids"] == ["A", "B"]
    assert block["sub_slices"]["books"]["question_ids"] == ["B"]
    assert doc["excluded"]["question_ids"] == ["TOPIC_QUESTION_034", "VERSE_LOOKUP_035"]
    assert list(doc["excluded"]["rows"]) == ["VERSE_LOOKUP_035"]
    assert doc["disambiguation"]["question_ids"] == ["B"] and doc["unexplained"] == ["C"]
    assert doc["transitions"] == {"R3->R6": 1, "R4->R6": 1}


def test_observed_routes_take_the_mode_and_only_r1_runs(tmp_path):
    def write(name, routes, build=fz.R1_BUILD):
        path = tmp_path / name
        path.write_text(json.dumps({"meta": {"data_build_id": build, "gt_version": "v2"},
                                    "per_question": {q: {"route": r} for q, r in routes.items()}}))
        return path
    l1 = write("l1.json", {"A": "R4", "B": "R3"})
    l2 = write("l2.json", {"A": "R6", "B": "R3"})
    l3 = write("l3.json", {"A": "R6"})
    assert fz.observed_routes([l1, l2], fz.R1_BUILD)[0] == {"A": "R4", "B": "R3"}  # tie: L1
    assert fz.observed_routes([l1, l2, l3], fz.R1_BUILD)[0]["A"] == "R6"
    with pytest.raises(fz.FreezeError, match="the R1 arm's runs are"):
        fz.observed_routes([write("x.json", {}, build="legacy-20261004")], fz.R1_BUILD)


# ---------------------------------------------------------------- the real R1 arm

def test_the_verse_parser_is_still_r1s():
    fz.check_verse_parser()


@needs_store
def test_the_r1_arm_against_itself_changes_nothing_on_gt_v2():
    from src.gt_v2 import load_ground_truth_v2
    from utils.verse_parser import find_verse_references

    reg = json.loads((R1_CONTRACTS / "event_registry.json").read_text(encoding="utf-8"))
    r1 = fz.r1_arm(R1_CONTRACTS, IdMap({}, frozenset(e["event_id"] for e in reg["events"])))
    rows = [fz.simulate(q.question, list(find_verse_references(q.question).refs), None, r1, r1)
            for q in load_ground_truth_v2().items]
    assert not any(row["causes"] for row in rows)
    assert sum(bool(row["R1"]["lane"]) for row in rows) > 0      # the lane fires somewhere
