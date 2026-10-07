"""Table-driven tests for Chinese scripture-reference parsing (G63, G05 examples)."""

import pytest

from ragcommon import refs
from ragcommon.refs import RefParseError, VerseRef


def R(book_id, ch, v_start=None, v_end=None, ch_end=None):
    """Expected ref; v_end defaults to v_start and ch_end to ch."""
    if v_start is not None and v_end is None:
        v_end = v_start
    return VerseRef(book_id, ch, v_start, v_end, ch if ch_end is None else ch_end)


JHN_3_16 = [R("jhn", 3, 16)]

# (text, default_book, expected refs)
PARSE_OK = [
    ("約翰福音3:16", None, JHN_3_16),
    ("約翰福音 3:16", None, JHN_3_16),
    ("約翰福音3：16", None, JHN_3_16),
    ("約翰福音３：１６", None, JHN_3_16),
    ("約3‧16", None, JHN_3_16),
    ("約3·16", None, JHN_3_16),
    ("約 3:16", None, JHN_3_16),
    ("約翰福音 3 : 16", None, JHN_3_16),
    ("約翰福音3:16。", None, JHN_3_16),
    ("（約翰福音3:16）", None, JHN_3_16),
    ("(約3:16)", None, JHN_3_16),
    ("約翰福音3章16節", None, JHN_3_16),
    ("約翰福音第3章16節", None, JHN_3_16),
    ("約翰福音第3章第16節", None, JHN_3_16),
    ("約翰福音第三章十六節", None, JHN_3_16),
    ("約3:16a", None, JHN_3_16),
    ("約翰3:16", None, JHN_3_16),
    ("約3:16-18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16－18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16–18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16—18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16~18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16～18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16至18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16到18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16 - 18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16b-18", None, [R("jhn", 3, 16, 18)]),
    ("約3:16-18a", None, [R("jhn", 3, 16, 18)]),
    ("約3章16至18節", None, [R("jhn", 3, 16, 18)]),
    ("約3章16節至4章2節", None, [R("jhn", 3, 16, 2, 4)]),
    ("約3:16、18", None, [R("jhn", 3, 16), R("jhn", 3, 18)]),
    ("約3:16，18", None, [R("jhn", 3, 16), R("jhn", 3, 18)]),
    ("約3:16,18", None, [R("jhn", 3, 16), R("jhn", 3, 18)]),
    ("約3:16、18節", None, [R("jhn", 3, 16), R("jhn", 3, 18)]),
    ("約3:16-18，20-21", None, [R("jhn", 3, 16, 18), R("jhn", 3, 20, 21)]),
    ("約3:16，18-20節", None, [R("jhn", 3, 16), R("jhn", 3, 18, 20)]),
    ("猶大書3-5節", None, [R("jud", 1, 3, 5)]),
    ("約3:16；4:1", None, [R("jhn", 3, 16), R("jhn", 4, 1)]),
    ("約3:16；路2:1", None, [R("jhn", 3, 16), R("luk", 2, 1)]),
    ("約3:16，路2:1", None, [R("jhn", 3, 16), R("luk", 2, 1)]),
    ("太5:3；路6:20", None, [R("mat", 5, 3), R("luk", 6, 20)]),
    ("創世記第3章3、5節", None, [R("gen", 3, 3), R("gen", 3, 5)]),
    ("創1:1-2:3", None, [R("gen", 1, 1, 3, 2)]),
    ("創世記1:1－2:3", None, [R("gen", 1, 1, 3, 2)]),
    ("創1:1至2:3", None, [R("gen", 1, 1, 3, 2)]),
    ("創1:31-2:1", None, [R("gen", 1, 31, 1, 2)]),
    ("但以理書7-8章", None, [R("dan", 7, ch_end=8)]),
    ("但以理書7至8章", None, [R("dan", 7, ch_end=8)]),
    ("但以理書7章-8章", None, [R("dan", 7, ch_end=8)]),
    ("但7-8章", None, [R("dan", 7, ch_end=8)]),
    ("但以理書第7至8章", None, [R("dan", 7, ch_end=8)]),
    ("創世記第1章", None, [R("gen", 1)]),
    ("創世記1", None, [R("gen", 1)]),
    ("創世記1-3", None, [R("gen", 1, ch_end=3)]),
    ("詩23篇", None, [R("psa", 23)]),
    ("詩篇23篇", None, [R("psa", 23)]),
    ("詩篇第23篇", None, [R("psa", 23)]),
    ("詩篇23:1", None, [R("psa", 23, 1)]),
    ("詩篇一百一十九篇", None, [R("psa", 119)]),
    ("詩篇一百十九篇", None, [R("psa", 119)]),
    ("詩篇一百零五篇", None, [R("psa", 105)]),
    ("詩篇一百五十篇", None, [R("psa", 150)]),
    ("詩篇 120-134", None, [R("psa", 120, ch_end=134)]),
    ("詩篇 16, 110篇", None, [R("psa", 16), R("psa", 110)]),
    ("詩篇 32篇; 51篇", None, [R("psa", 32), R("psa", 51)]),
    ("詩3篇", None, [R("psa", 3)]),
    ("詩119:176", None, [R("psa", 119, 176)]),
    ("撒上17:45", None, [R("1sa", 17, 45)]),
    ("撒母耳記上17章", None, [R("1sa", 17)]),
    ("王上18:20-40", None, [R("1ki", 18, 20, 40)]),
    ("列王紀上 18:20-40", None, [R("1ki", 18, 20, 40)]),
    ("列王記上18章", None, [R("1ki", 18)]),
    ("代下7:14", None, [R("2ch", 7, 14)]),
    ("林前13:4-7", None, [R("1co", 13, 4, 7)]),
    ("林後5:17", None, [R("2co", 5, 17)]),
    ("約壹1:9", None, [R("1jn", 1, 9)]),
    ("約一1:9", None, [R("1jn", 1, 9)]),
    ("約翰一書1:9", None, [R("1jn", 1, 9)]),
    ("約翰壹書1:9", None, [R("1jn", 1, 9)]),
    ("猶大書3", None, [R("jud", 1, 3)]),
    ("猶大書3-5", None, [R("jud", 1, 3, 5)]),
    ("猶大書 1:3-23", None, [R("jud", 1, 3, 23)]),
    ("猶大書1章", None, [R("jud", 1)]),
    ("猶3", None, [R("jud", 1, 3)]),
    ("腓利門書1:15-16", None, [R("phm", 1, 15, 16)]),
    ("俄巴底亞書1:15", None, [R("oba", 1, 15)]),
    ("約翰三書1:2", None, [R("3jn", 1, 2)]),
    ("以斯拉記; 尼希米記", None, [R("ezr", 1, ch_end=10), R("neh", 1, ch_end=13)]),
    ("腓利門書", None, [R("phm", 1)]),
    ("尼西米記2:1", None, [R("neh", 2, 1)]),
    ("尼希米記2:1", None, [R("neh", 2, 1)]),
    ("創世記 37章; 41章; 45-46章", None, [R("gen", 37), R("gen", 41), R("gen", 45, ch_end=46)]),
    ("馬太福音 5-7章, 10章, 13章, 18章, 24-25章", None,
     [R("mat", 5, ch_end=7), R("mat", 10), R("mat", 13), R("mat", 18), R("mat", 24, ch_end=25)]),
    ("以賽亞書 11:1, 10", None, [R("isa", 11, 1), R("isa", 11, 10)]),
    ("申命記 8:3; 6:16; 6:13", None, [R("deu", 8, 3), R("deu", 6, 16), R("deu", 6, 13)]),
    ("約拿書 1:17-2:10", None, [R("jon", 1, 17, 10, 2)]),
    ("啟示錄 21:1-22:5", None, [R("rev", 21, 1, 5, 22)]),
    ("啓示錄1:8", None, [R("rev", 1, 8)]),
    ("啟22:21", None, [R("rev", 22, 21)]),
    ("瑪拉基書 4:5-6", None, [R("mal", 4, 5, 6)]),
    ("羅馬書 3:23", None, [R("rom", 3, 23)]),
    ("羅3:23-24", None, [R("rom", 3, 23, 24)]),
    ("提前3:16", None, [R("1ti", 3, 16)]),
    ("提後3:16-17", None, [R("2ti", 3, 16, 17)]),
    ("帖前4:16-17", None, [R("1th", 4, 16, 17)]),
    ("來11:1", None, [R("heb", 11, 1)]),
    ("雅1:5", None, [R("jas", 1, 5)]),
    ("彼前2:9", None, [R("1pe", 2, 9)]),
    ("馬可福音 16:9-20", None, [R("mrk", 16, 9, 20)]),
    ("可16:9－20", None, [R("mrk", 16, 9, 20)]),
    ("路加福音 15章", None, [R("luk", 15)]),
    ("徒2:38", None, [R("act", 2, 38)]),
    ("使徒行傳 2:14-36; 約珥書 2章; 詩篇 16, 110篇", None,
     [R("act", 2, 14, 36), R("jol", 2), R("psa", 16), R("psa", 110)]),
    ("撒迦利亞書 9:9; 11:12-13; 12:10; 馬太福音 21章, 27章", None,
     [R("zec", 9, 9), R("zec", 11, 12, 13), R("zec", 12, 10), R("mat", 21), R("mat", 27)]),
    ("以斯拉記 4章; 5:1-2; 哈該書 1章", None, [R("ezr", 4), R("ezr", 5, 1, 2), R("hag", 1)]),
    ("（太14‧13－21；路9‧10－17；約6‧1－14）", None,
     [R("mat", 14, 13, 21), R("luk", 9, 10, 17), R("jhn", 6, 1, 14)]),
    ("（太26‧69－70；可14‧66－68；路22‧55－57)", None,
     [R("mat", 26, 69, 70), R("mrk", 14, 66, 68), R("luk", 22, 55, 57)]),
    ("（賽38‧1－8；21－22；代下32‧24－26）", None,
     [R("isa", 38, 1, 8), R("isa", 38, 21, 22), R("2ch", 32, 24, 26)]),
    ("（代下34‧3－7；29－33）", None, [R("2ch", 34, 3, 7), R("2ch", 34, 29, 33)]),
    ("（代上13‧1－14；15‧25－16‧6，43）", None,
     [R("1ch", 13, 1, 14), R("1ch", 15, 25, 6, 16), R("1ch", 16, 43)]),
    ("（詩105‧1－15；96‧1－13；106‧1，47－48）", None,
     [R("psa", 105, 1, 15), R("psa", 96, 1, 13), R("psa", 106, 1), R("psa", 106, 47, 48)]),
    ("（王下25‧18－21，27－30）", None, [R("2ki", 25, 18, 21), R("2ki", 25, 27, 30)]),
    ("（詩14）", None, [R("psa", 14)]),
    ("（拉2‧1－70）", None, [R("ezr", 2, 1, 70)]),
    ("（8‧1－10‧22）", "ezk", [R("ezk", 8, 1, 22, 10)]),
    ("（22‧6－16；26‧12－18）", "act", [R("act", 22, 6, 16), R("act", 26, 12, 18)]),
    ("二十九章十節", "ezk", [R("ezk", 29, 10)]),
    ("以賽亞十八章一節", None, [R("isa", 18, 1)]),
    ("歷代下九章十四節", None, [R("2ch", 9, 14)]),
    ("撒母耳上十六章九節", None, [R("1sa", 16, 9)]),
    ("列王下二十四章八節", None, [R("2ki", 24, 8)]),
    ("馬太十六章十七節", None, [R("mat", 16, 17)]),
    ("約珥三章十八節", None, [R("jol", 3, 18)]),
    ("路加福音四章二十六節", None, [R("luk", 4, 26)]),
    ("創世記第四十六章十三節", None, [R("gen", 46, 13)]),
    ("路17:36", None, [R("luk", 17, 36)]),
    ("太18:11", None, [R("mat", 18, 11)]),
]


@pytest.mark.parametrize("text, default_book, expected", PARSE_OK)
def test_parse_refs_accepts(text, default_book, expected):
    result = refs.parse_refs(text, strict=True, default_book=default_book)
    assert result.ok and result.reason is None
    assert list(result.refs) == expected


PARSE_BAD = [
    ("約3天", None),
    ("拿5個餅", None),
    ("提前", None),
    ("王上", None),
    ("撒上", None),
    ("約", None),
    ("", None),
    ("   ", None),
    ("。", None),
    ("創世記51章", None),
    ("創1:32", None),
    ("創0:1", None),
    ("創1:0", None),
    ("約3:18-16", None),
    ("但以理書8-7章", None),
    ("創2:3-1:1", None),
    ("提摩太3:16", None),
    ("哥林多前13:4", None),
    ("約翰福音3:16；", None),
    ("約翰福音3:", None),
    ("約翰福音:16", None),
    ("3:16", None),
    ("創世記3篇", None),
    ("約3:16xyz", None),
    ("John 3:16", None),
    ("約翰福音3:16；外傳", None),
    ("猶大書3章", None),
    ("約7:54", None),
    ("約翰福音二二章", None),
    ("創1-2:3", None),
    ("5節", "gen"),
    ("約3:16-", None),
    ("約3:16,,18", None),
    ("創世記1:1-2:3:4", None),
    ("大約3章", None),
    ("這卷書3章", None),
    ("多加一肘", None),
    ("七十人加五萬人", None),
    ("約3天之後", None),
    ("(約3:16", None),
    ("約3:16 18", None),
    ("創世記 第", None),
    ("詩篇百篇", None),
    ("詩篇二二十篇", None),
    ("詩篇一百零篇", None),
]


@pytest.mark.parametrize("text, default_book", PARSE_BAD)
def test_parse_refs_strict_raises(text, default_book):
    with pytest.raises(RefParseError) as info:
        refs.parse_refs(text, strict=True, default_book=default_book)
    assert info.value.reason


@pytest.mark.parametrize("text, default_book", PARSE_BAD)
def test_parse_refs_lenient_returns_empty_with_reason(text, default_book):
    result = refs.parse_refs(text, default_book=default_book)
    assert result.refs == ()
    assert not result.ok and result.reason


def test_alias_resolves_jhn_7_53_and_reports_it():
    result = refs.parse_refs("約7:53", strict=True)
    assert result.refs == (R("jhn", 8, 1),)
    assert result.aliases_applied == ("jhn.7.53->jhn.8.1",)
    span = refs.parse_refs("約翰福音7:53-8:11", strict=True)
    assert span.refs == (R("jhn", 8, 1, 11),)


def test_to_dicts_shape():
    result = refs.parse_refs("創1:1-2:3；但7-8章", strict=True)
    assert result.to_dicts() == [
        {"book_id": "gen", "ch": 1, "v_start": 1, "v_end": 3, "ch_end": 2},
        {"book_id": "dan", "ch": 7, "v_start": None, "v_end": None, "ch_end": 8},
    ]


def test_parse_refs_rejects_unknown_default_book():
    with pytest.raises(ValueError):
        refs.parse_refs("3:16", default_book="xyz")


def test_parse_refs_rejects_non_string():
    with pytest.raises(RefParseError):
        refs.parse_refs(None, strict=True)


# (text, [(raw, refs)])
FIND_OK = [
    ("根據約翰福音3:16，神如何愛世人？", [("約翰福音3:16", JHN_3_16)]),
    ("約3:16說了什麼", [("約3:16", JHN_3_16)]),
    ("請解釋羅馬書3:23", [("羅馬書3:23", [R("rom", 3, 23)])]),
    ("詩篇23篇的意思", [("詩篇23篇", [R("psa", 23)])]),
    ("詩篇23說什麼", [("詩篇23", [R("psa", 23)])]),
    ("撒上17:45大衛說", [("撒上17:45", [R("1sa", 17, 45)])]),
    ("王上18章以利亞", [("王上18章", [R("1ki", 18)])]),
    ("比較太5:3與路6:20", [("太5:3", [R("mat", 5, 3)]), ("路6:20", [R("luk", 6, 20)])]),
    ("約翰福音第三章十六節", [("約翰福音第三章十六節", JHN_3_16)]),
    ("創1:1-2:3的創造記述", [("創1:1-2:3", [R("gen", 1, 1, 3, 2)])]),
    ("但以理書7-8章的異象", [("但以理書7-8章", [R("dan", 7, ch_end=8)])]),
    ("約翰福音7:53", [("約翰福音7:53", [R("jhn", 8, 1)])]),
    ("使徒行傳2:38；徒2:41", [("使徒行傳2:38", [R("act", 2, 38)]), ("徒2:41", [R("act", 2, 41)])]),
    ("約壹1:9的應許", [("約壹1:9", [R("1jn", 1, 9)])]),
    ("林前13章愛的真諦", [("林前13章", [R("1co", 13)])]),
    ("猶大書3提到", [("猶大書3", [R("jud", 1, 3)])]),
    ("見以賽亞十八章一節", [("以賽亞十八章一節", [R("isa", 18, 1)])]),
    ("在撒母耳下四章四節是米非波設", [("撒母耳下四章四節", [R("2sa", 4, 4)])]),
    ("約翰在馬太十六章十七節稱約拿", [("馬太十六章十七節", [R("mat", 16, 17)])]),
    ("（太14‧13－21；路9‧10－17）",
     [("太14‧13－21", [R("mat", 14, 13, 21)]), ("路9‧10－17", [R("luk", 9, 10, 17)])]),
    ("約翰福音 3 : 16", [("約翰福音 3 : 16", JHN_3_16)]),
    ("路17:36說什麼", [("路17:36", [R("luk", 17, 36)])]),
    ("約3:16-18，20", [("約3:16-18，20", [R("jhn", 3, 16, 18), R("jhn", 3, 20)])]),
    ("約3:16，18歲的人", [("約3:16", JHN_3_16)]),
    ("詩23篇和詩篇第一百篇", [("詩23篇", [R("psa", 23)]), ("詩篇第一百篇", [R("psa", 100)])]),
    ("創世記1:1到了", [("創世記1:1", [R("gen", 1, 1)])]),
    ("約3:16。", [("約3:16", JHN_3_16)]),
    ("正如詩篇第二篇上記着", [("詩篇第二篇", [R("psa", 2)])]),
    ("撒勒法與路加福音四章二十六節同", [("路加福音四章二十六節", [R("luk", 4, 26)])]),
    ("列王下八章二十六節是二十二歲", [("列王下八章二十六節", [R("2ki", 8, 26)])]),
    ("馬太福音五章三到十二節", [("馬太福音五章三到十二節", [R("mat", 5, 3, 12)])]),
    ("馬太福音5章3節到12節", [("馬太福音5章3節到12節", [R("mat", 5, 3, 12)])]),
    ("詩篇 23 說什麼", [("詩篇 23", [R("psa", 23)])]),
]


@pytest.mark.parametrize("text, expected", FIND_OK)
def test_find_refs_in_free_text(text, expected):
    found = refs.find_refs(text)
    assert [(m.raw, list(m.refs)) for m in found.matches] == expected
    for match in found.matches:
        assert text[match.start:match.end] == match.raw
    assert found.rejected == ()
    assert list(found.refs) == [r for _, rs in expected for r in rs]


FIND_NONE = [
    "約3天", "大約3天後", "拿5個餅", "提前", "提前3天出發", "他作王上任", "王上",
    "耶穌拿5個餅和2條魚", "約有3章", "大約3章", "本書3章", "這卷書3章", "提摩太3:16",
    "加拉太書", "使身量多加一肘呢", "原文是七十人加五萬人", "約三章", "太3", "可以",
    "約翰福音3天", "約翰福音 3 天", "詩篇二十三", "撒母耳上十六章九", "約十章", "太五章", "創世記", "約 3:16", "創世記3篇", "約第3章", "撒上",
    "王上5", "約3:16天", "3:16", "第3章16節", "", "約翰福音3.16",
]


@pytest.mark.parametrize("text", FIND_NONE)
def test_find_refs_ignores_non_references(text):
    found = refs.find_refs(text)
    assert found.matches == () and found.rejected == ()


@pytest.mark.parametrize(
    "text, raw",
    [("創世記51章", "創世記51章"), ("約3:99是什麼", "約3:99"), ("約翰福音3:18-16", "約翰福音3:18-16"),
     ("約7:54", "約7:54")],
)
def test_find_refs_reports_invalid_references(text, raw):
    found = refs.find_refs(text)
    assert found.matches == ()
    assert [r.raw for r in found.rejected] == [raw]
    assert found.rejected[0].reason


def test_find_refs_rejects_non_string():
    with pytest.raises(TypeError):
        refs.find_refs(None)


def test_expand_slots_crosses_chapters():
    (ref,) = refs.parse_refs("創1:30-2:2", strict=True).refs
    assert refs.expand_slots(ref) == ("gen.1.30", "gen.1.31", "gen.2.1", "gen.2.2")
    (whole,) = refs.parse_refs("猶大書1章", strict=True).refs
    assert len(refs.expand_slots(whole)) == 25
    (psalm,) = refs.parse_refs("詩117篇", strict=True).refs
    assert refs.expand_slots(psalm) == ("psa.117.1", "psa.117.2")


def test_verse_ref_is_immutable_and_reports_level():
    ref = R("jhn", 3, 16)
    with pytest.raises(AttributeError):
        ref.ch = 4
    assert not ref.is_whole_chapter
    assert R("dan", 7, ch_end=8).is_whole_chapter
