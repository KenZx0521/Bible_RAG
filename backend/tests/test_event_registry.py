"""Event registry auxiliary lane, read from the build's contract (event_registry.json v2).

An event fires on a legacy trigger literally in the question (book names masked);
its anchors are passage ids. The lane appends one anchor the top-k lacks, after
the finished top-k, on R4/R5 only.
"""

import json
from pathlib import Path

import pytest

from utils.retrieval import event_registry as reg

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_build"
BUILD_ID = json.loads((FIXTURE / "build.json").read_text(encoding="utf-8"))["build_id"]
DOC = json.loads((FIXTURE / "contracts" / BUILD_ID / "event_registry.json").read_text("utf-8"))
BOOKS = ("使徒行傳", "以弗所書", "約翰一書", "約翰福音")


def _ev(eid, triggers, anchors):
    return reg.RegistryEvent(id=eid, event_id="ev0001", name=eid, triggers=tuple(triggers),
                             anchors=tuple(anchors))


def test_the_contract_registry_parses_with_legacy_ids_and_passage_anchors():
    events = reg.parse_registry(DOC)

    assert [e.id for e in events] == ["event:kemu", "event:tianguo", "event:saoluo"]
    assert events[2].event_id == "ev0003"
    assert events[2].triggers == ("保羅歸主",)
    assert events[2].anchors == ("ps:act.9.1", "ps:act.9.3b")


def test_anchor_passages_are_listed_for_the_startup_check():
    events = reg.parse_registry(DOC)

    assert reg.anchor_passages(events) == ("ps:psa.42.1", "ps:mat.18.1", "ps:act.9.1",
                                           "ps:act.9.3b")


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema="ragdata.event_registry.v1"), "schema"),
    (lambda d: d["events"][0].update(anchors=[]), "anchors"),
    (lambda d: d["events"][0].update(legacy_triggers=[]), "triggers"),
    (lambda d: d["events"][0]["anchors"][0].update(passage_id="psa:42:0"), "passage"),
    (lambda d: d["events"].append(dict(d["events"][0])), "duplicate"),
    (lambda d: d.update(events="none"), "events"),
])
def test_a_malformed_registry_raises(mutate, message):
    doc = json.loads(json.dumps(DOC))
    mutate(doc)

    with pytest.raises(reg.RegistryError, match=message):
        reg.parse_registry(doc)


def test_book_names_are_masked_before_matching():
    events = (_ev("e:john", ["約翰"], ["ps:jhn.1.1"]),)

    assert reg.match_events("約翰福音第一章說什麼", events, BOOKS) == []
    assert reg.match_events("約翰在哪裡施洗", events, BOOKS) == [events[0]]
    assert reg.mask_book_names("約翰一書與約翰福音", BOOKS) == "□□□□與□□□□"


def test_most_specific_event_first():
    wide = _ev("e:wide", ["天國"], ["ps:mat.5.1", "ps:mat.13.1"])
    narrow = _ev("e:narrow", ["最大"], ["ps:mat.18.1"])

    assert reg.match_events("天國裏誰最大", (wide, narrow), BOOKS) == [narrow, wide]


def test_aux_picks_the_first_anchor_the_core_lacks():
    events = [_ev("e:a", ["x"], ["ps:act.9.1", "ps:act.9.3b"]), _ev("e:b", ["y"], ["ps:mat.18.1"])]

    assert reg.select_aux_anchors(events, ["ps:act.9.1"], 1) == [("e:a", "ps:act.9.3b")]
    assert reg.select_aux_anchors(events, [], 2) == [("e:a", "ps:act.9.1"), ("e:b", "ps:mat.18.1")]
    assert reg.select_aux_anchors(events, ["ps:act.9.1", "ps:act.9.3b", "ps:mat.18.1"], 2) == []
