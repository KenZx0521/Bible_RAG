"""Routing signals from the v2 lexicon: one matcher pass, distinct targets, data-made types.

The lexicon below is made up in the contract's shape (ids partly real). Its route
types follow the R2 rule K4 applies (kg0 type, untyped names count as Place; the
divine persons count as Person, the titles of Jesus all with 耶穌's target, 耶和華
counts as neither), except 猶大, which is given both types to show that a target
counts wherever its route types say.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ragcommon import routing
from ragcommon.tests.lexicon_doc import document, event, exclusion, name, target, term
from router_fakes import BOOK_TERMS
from utils.signal_detector import QuerySignals, detect_signals, select_route
from utils.verse_parser import VerseRef

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

NAMES = [
    name("亞伯拉罕", "nm:a00000000001", "Place"), name("亞伯", "nm:a00000000002", "Place"),
    name("約翰", "nm:a00000000003", "Place"), name("撒但", "nm:a00000000004", "Place"),
    name("但", "nm:a00000000005", "Place", routable=False), name("何提", "nm:a00000000006", "Place"),
    name("大流士", "nm:6688ae8383df", "Place"), name("塞魯士", "nm:f64cf0ccb922", "Place"),
    name("西門‧彼得", "nm:5c12c8f54d5e", "Place"),
    name("西門彼得", "nm:5c12c8f54d5e", "Place", label="西門‧彼得", kind="dotless"),
    name("猶大", "nm:ed75e384c743", "Person", "Place"),
    name("摩西", "nm:a00000000007", "Person"), name("亞倫", "nm:a00000000008", "Person"),
    name("大衛", "nm:a00000000009", "Place"), name("歌利亞", "nm:a0000000000a", "Place")]
JESUS = target("dr.span.008", "耶穌", "Person")
DIVINE = [*(term(s, "divine", [JESUS]) for s in ("耶穌", "主耶穌", "救主", "基督", "人子")),
          term("耶和華", "divine", [target("dr.span.001", "耶和華")]),
          term("主", "divine", [target("dr.span.014", "主")], routable=False)]
ALIASES = [term("古列", "alias", [target("nm:f64cf0ccb922", "塞魯士", "Place")]),
           term("大利烏", "alias", [target("nm:6688ae8383df", "大流士", "Place")])]
EVENTS = [event("保羅歸主", "ev0002", "掃羅的轉變"), event("十誡", "ev0018", "十誡"),
          event("大衛與歌利亞", "ev0008", "大衛擊殺歌利亞"), event("釘十字架", "ev0027", "耶穌被釘十字架"),
          event("山上寶訓", "ev0016", "山上寶訓"), event("客西馬尼禱告", "ev0011", "在客西馬尼禱告")]
DOC = document(names=NAMES, divine=DIVINE, aliases=ALIASES, events=EVENTS, books=BOOK_TERMS,
               exclusions=[exclusion("何提", "如何提")])


@pytest.fixture(scope="module")
def lexicon():
    return routing.parse_lexicon(DOC)


def _signals(lexicon, text, verse_refs=(), intent="topic", entities=(), keywords=None):
    book_ids = {b.full_name: b.book_id for b in lexicon.books}
    return detect_signals(text, list(verse_refs), intent, list(entities), lexicon, book_ids,
                          keywords)


def test_abraham_is_not_abel(lexicon):
    assert _signals(lexicon, "亞伯拉罕的信心").detected_places == ("亞伯拉罕",)
    assert _signals(lexicon, "亞伯拉罕和亞伯").detected_places == ("亞伯拉罕", "亞伯")


def test_a_book_name_is_not_a_name_inside_it(lexicon):
    s = _signals(lexicon, "約翰福音的主題")

    assert s.detected_places == () and s.detected_book_names == ("約翰福音",)
    assert _signals(lexicon, "約翰在哪裡施洗").detected_places == ("約翰",)


def test_single_characters_never_route(lexicon):
    s = _signals(lexicon, "但是撒但怎樣試探耶穌")

    assert s.detected_places == ("撒但",) and s.detected_persons == ("耶穌",)
    assert _signals(lexicon, "但是主說").route == "fallback"


def test_question_words_are_excluded(lexicon):
    assert _signals(lexicon, "保羅如何提醒提摩太").detected_places == ()
    assert _signals(lexicon, "何提是誰").detected_places == ("何提",)


def test_a_query_alias_counts_as_its_target_once(lexicon):
    assert _signals(lexicon, "大利烏王的詔令").detected_places == ("大流士",)
    assert _signals(lexicon, "大利烏就是大流士嗎").detected_places == ("大流士",)
    assert _signals(lexicon, "古列與大利烏").detected_places == ("塞魯士", "大流士")


def test_a_name_written_without_the_dot_is_the_same_target(lexicon):
    assert _signals(lexicon, "西門彼得認耶穌").detected_places == ("西門‧彼得",)
    assert _signals(lexicon, "西門彼得與西門‧彼得").detected_places == ("西門‧彼得",)


def test_a_target_counts_as_every_type_it_carries(lexicon):
    s = _signals(lexicon, "猶大")

    assert s.detected_persons == ("猶大",) and s.detected_places == ("猶大",)
    assert s.route == "R6"
    assert _signals(lexicon, "猶大和摩西").route == "R3"


def test_divine_titles_count_by_their_route_types(lexicon):
    s = _signals(lexicon, "耶穌與耶和華")

    assert s.detected_persons == ("耶穌",) and s.detected_places == () and s.route == "fallback"
    assert _signals(lexicon, "耶穌和摩西").route == "R3"


@pytest.mark.parametrize("question, entities, event", [
    ("救主耶穌被釘十字架的經過？", [], "ev0027"),
    ("耶穌在山上寶訓中對基督徒有何教導？", [], "ev0016"),
    ("人子耶穌在客西馬尼禱告的內容？", [], "ev0011"),
    ("主耶穌在客西馬尼禱告時說了什麼？", ["耶穌"], "ev0011"),
])
def test_two_titles_of_jesus_are_one_person_and_keep_the_event_route(lexicon, question,
                                                                       entities, event):
    s = _signals(lexicon, question, intent="event", entities=entities)

    assert s.detected_persons == ("耶穌",) and s.detected_events == (event,)
    assert s.route == "R4"


def test_a_name_inside_an_event_phrase_is_not_counted(lexicon):
    s = _signals(lexicon, "大衛與歌利亞的故事")

    assert s.detected_events == ("ev0008",) and s.detected_places == ()
    assert s.route == "R4"


def test_llm_entities_feed_names_and_keywords_feed_events(lexicon):
    s = _signals(lexicon, "他們的關係如何？", intent="person", entities=["摩西", "亞倫", "十誡"],
                 keywords=["十誡", "猶大"])

    assert s.detected_persons == ("摩西", "亞倫")
    assert s.detected_events == ("ev0018",)
    assert s.route == "R3"


def test_an_event_intent_without_an_event_term_keeps_the_llm_keywords(lexicon):
    s = _signals(lexicon, "那件事怎麼發生的", intent="event", keywords=["某事"])

    assert s.detected_events == ("某事",) and s.route == "R4"


def test_book_ids_follow_the_detected_names(lexicon):
    s = _signals(lexicon, "耶利米書的新約預言在希伯來書的應驗")

    assert s.detected_book_names == ("耶利米書", "希伯來書")
    assert s.detected_book_ids == ("jer", "heb")
    assert s.route == "R5"


def test_an_empty_lexicon_routes_on_verse_references_and_intent_only():
    lexicon = routing.parse_lexicon(document())

    assert _signals(lexicon, "亞伯拉罕和大衛").route == "fallback"
    assert _signals(lexicon, "q", intent="cross_reference").route == "R5"


@pytest.mark.parametrize("signals, intent, route", [
    (QuerySignals(has_book_chapter_verse=True, has_multi_book=True), "", "R1"),
    (QuerySignals(has_book_chapter=True, has_multi_book=True), "", "R5"),
    (QuerySignals(has_book_chapter=True), "", "R2"),
    (QuerySignals(), "cross_reference", "R5"),
    (QuerySignals(has_multi_person=True, has_event_keyword=True), "", "R3"),
    (QuerySignals(has_event_keyword=True, has_place=True), "", "R4"),
    (QuerySignals(has_place=True), "", "R6"),
    (QuerySignals(), "topic", "fallback"),
])
def test_route_priority(signals, intent, route):
    assert select_route(signals, intent) == route


def test_verse_references_set_the_verse_signals(lexicon):
    assert _signals(lexicon, "q", [VerseRef("jhn", "約翰福音", 3, 16, 16)]).route == "R1"
    assert _signals(lexicon, "q", [VerseRef("jhn", "約翰福音", 3)]).route == "R2"


def test_detected_signals_are_identical_across_hash_seeds(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_bytes(routing.render_lexicon(DOC))
    code = (
        "from ragcommon import routing\n"
        "from utils.signal_detector import detect_signals\n"
        f"lex = routing.load_lexicon({str(path)!r})\n"
        "ids = {b.full_name: b.book_id for b in lex.books}\n"
        "s = detect_signals('摩西和亞倫在亞伯拉罕與猶大經歷十誡、大衛與歌利亞', [], 'event',\n"
        "                   ['摩西', '大利烏', '古列'], lex, ids, ['十誡', '保羅歸主'])\n"
        "print(s.detected_events, s.detected_places, s.detected_persons)\n"
    )
    pythonpath = os.pathsep.join([str(BACKEND), str(REPO / "packages")])
    outputs = {subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=True, text=True,
                              capture_output=True,
                              env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": pythonpath}
                              ).stdout for seed in ("1", "2", "3", "4")}
    assert len(outputs) == 1, outputs
