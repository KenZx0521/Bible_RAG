"""GEN confirmation set: the Genesis age card ``gencard`` (prereg §5.1–§5.3, §4.1 arm G), all on the CPU.

Synthetic tests run on a made-up two-chapter layer and names file (every name and number made up; this
file shares no 8-character window with the store's text layer or any real question, checked below): a
paraphrase bank x name forms x marker forms (spaced as mech_g accepts them) x namesake and blocker traps,
markers and kinship words that mark no seed, every abstention reason, the scope's boundaries, the engine's
verbatim copy, the card, the standard-library-only rule and a ReDoS timing pin. The store tests (skipped
when the store is not mounted) read the real layer and gen_names.json and name the persons only through
it: the card equals stage-0's engine_x.card on all 64 same-chapter pairs at d >= 2; code-built variants of
all 58 pool slots give the exact seeds, the 6 marker slots in every spacing mech_g accepts; stage-0's 14
F1/F5 development templates give the gold pair and its 4 F3 templates abstain; the rule fires on none of
GT v1/v2, A's 32 confirm questions and stage-0's DYN/S6/SYNC items; the prod dynasty trigger fires on none
of the pins. They assert counts, ids and booleans only and print no question or card text. No LLM.
"""
from __future__ import annotations

import ast
import importlib
import itertools
import json
import re
import signal
import sys
import time
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import g_common as GC  # noqa: E402
import gencard  # noqa: E402

# the package exports the functions trigger and card, which shadow the submodules of those names
E, NM, SD, TR = (importlib.import_module(f"gencard.{m}") for m in ("engine", "names", "seeds", "trigger"))

PKG = H / "gencard"
WINDOW = 8
STORE_OK = GC.GEN_LAYER.is_file() and GC.GEN_NAMES.is_file() and GC.POOL.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({GC.GEN_NAMES})")

# ---------------------------------------------------------------- a synthetic layer (made up)
# (id, name, begetting age, remaining years, stated lifespan); G05.06 is the taken one (engine.TAKEN_ID);
# 戴維 dies the year 費恩 is born (his age then equals his lifespan: the scope's boundary)
CH5 = (("G05.00", "安東", 100, 800, 900), ("G05.01", "布朗", 90, 700, 790), ("G05.02", "卡爾", 80, 600, 680),
       ("G05.03", "戴維", 70, 50, 120), ("G05.04", "艾倫", 50, 510, 560), ("G05.05", "費恩", 50, 700, 750),
       ("G05.06", "葛林", 65, 235, 300), ("G05.07", "霍華德", 120, 600, 720), ("G05.08", "伊森", 110, 500, 610),
       ("G05.09", "傑森", 400, None, 800))
CH11 = (("G11.00", "凱", 90, 400, None), ("G11.01", "李奧", 30, 300, None), ("G11.02", "麥斯", 25, 200, None),
        ("G11.03", "尼克", 35, 100, None), ("G11.04", "奧托", 20, 300, None), ("G11.05", "保羅", 30, 50, None),
        ("G11.06", "昆汀", 30, 200, None), ("G11.07", "羅伊", 25, 100, None), ("G11.08", "史坦", 70, None, 205))
ROWS = {r[0]: r for r in CH5 + CH11}
# the common words of the guarded chain names 凱 and 史坦, and of the Cain-line name 柔伊 (a rule-4 blocker)
COMMON = {"凱": ("凱旋", "凱歌", "凱子", "凱過"), "史坦": (*(f"史坦{c}" for c in "著住開了"), "歷史"),
          "柔伊": ("溫柔伊",)}
CAIN = ("凱恩", "艾迪", "米契爾", "霍華", "柔伊", "諾德", "柯霍")     # 葛林 and 伊森 have namesakes there
ABRAM = ("艾瑞克", "艾瑞克森", "哈利", "蘿拉", "蜜雪")               # 羅伊 has one there (史坦's son)
BOOKS = ("某乙福音", "某乙", "某丙志上", "代上", "某丙志")             # 代上: a book only as an abbreviation
LEX = ("卡爾頓", "布朗尼", "尼克森", "奧托曼", "麥斯來", "保羅斯", "葛林城", "奧托死城", "尼克高齡鎮")


def gen_doc() -> dict:
    nodes, edges, derived = [], [], {}
    for ch, rows in ((5, CH5), (11, CH11)):
        for order, (gid, name, b, r, t) in enumerate(rows):
            f = {"beget": [b, f"syn.{ch}.{3 * order}"]}
            if r is not None:
                f["remain"] = [r, f"syn.{ch}.{3 * order + 1}"]
            if t is not None:
                f["total"] = [t, f"syn.{ch}.{3 * order + 2}"]
            else:
                derived[gid] = b + r
            nxt = rows[order + 1][1] if order + 1 < len(rows) else None
            nodes.append({"id": gid, "name": name, "chapter": ch, "order": order, "sons": [nxt] if nxt else [],
                          "fields": f, "flood_offset": [2, "syn.11.0"] if gid == "G11.00" else None})
        edges += [[a[0], b[0], "son", f"syn.{ch}.{3 * i}"] for i, (a, b) in enumerate(zip(rows, rows[1:]))]
    nodes[9]["sons"] = ["凱", "路克", "馬可"]                 # the flood patriarch's sons, the first on chapter 11
    nodes[-1]["sons"] = ["艾瑞克", "羅伊", "哈利"]            # a son bearing a chain name: 羅伊's namesake
    return {"schema": "arith.gen_layer.v1", "text_digest": "syn", "nodes": nodes, "edges": edges,
            "conflict_edges": [["G05.09", "G11.00", "son", "syn.5.30"]], "flood": {"noah_age": [450, "syn.7.6"]},
            "derived": {"total": derived}, "checks": {}}


def names_doc(gen: dict) -> dict:
    chain = [{"id": n["id"], "name": n["name"], "chapter": n["chapter"]}
             for n in sorted(gen["nodes"], key=lambda n: (n["chapter"], n["order"]))]
    return {"schema": "gen_confirm.gen_names.v1", "text_digest": "syn", "gen_layer_sha256": "syn", "chain": chain,
            "cain_line": sorted(CAIN), "abram_family": sorted(ABRAM), "extra_persons": sorted(CAIN + ABRAM),
            "other_books": sorted(BOOKS), "lexicon_blockers": sorted(LEX), "sources": {}}


@pytest.fixture(scope="module")
def L():
    gen = gen_doc()
    return gencard.parse(gen, names_doc(gen), common_words=COMMON)


def nm(x: str) -> str:
    return ROWS[x][1]


def life(x: str) -> int:
    _i, _n, b, r, t = ROWS[x]
    return t if t is not None else b + r


def chain_ids(ch: int) -> list[str]:
    return [r[0] for r in (CH5 if ch == 5 else CH11)]


def oracle(x: str, y: str, form: str) -> bool:
    """Independent of gencard: does a pair (x above y, same chapter) fit the pool's shape for a form."""
    ids = chain_ids(int(x[1:3]))
    i, j = ids.index(x), ids.index(y)
    age = sum(ROWS[z][2] for z in ids[i:j])
    if form == "F1":
        return 2 <= j - i <= 4 and age < life(x)
    return j - i >= 2 and x != E.TAKEN_ID and 0 < life(x) - age < life(y)


def pairs(ch: int, d_min: int = 1):
    ids = chain_ids(ch)
    return [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + d_min, len(ids))]


ALL_PAIRS = pairs(5) + pairs(11)

# ---------------------------------------------------------------- the paraphrase bank (made up)
F1_BANK = ("依創世記所載，{x}幾歲時，{y}出生？", "根據創世記，{y}出生的時候，{x}多大年紀？",
           "創世記中，{x}在{y}誕生那年是多少歲？", "按照創世記的記載，{x}多少歲的時候{y}才出世？",
           "{y}降生時，{x}的年齡是多少？（依創世記）", "照創世記的記載，{x}比{y}大幾歲？",
           "依創世記，{x}和{y}兩人出生相隔多少年？", "創世記的家譜裡，{y}來到世上時{x}幾歲？",
           "依創世記，{x}幾歲的時候，家族裡生下了{y}？", "依創世記，{x}比{y}大多少歲？",
           "創世記記載的{y}出世時，{x}的歲數是多少？")
F5_BANK = ("依創世記所載，{x}去世那年，{y}幾歲？", "根據創世記，{x}過世的時候，{y}多大了？",
           "創世記中，{x}離世時{y}的年紀是多少？", "照創世記，{x}逝世那一年，{y}年齡多少？",
           "{x}壽終時，{y}已經活了多久？（依創世記）", "依創世記，{y}出生之後，{x}又活了多少年？",
           "按創世記的記載，{x}死的時候{y}幾歲？", "依創世記，{x}離開人世那年，{y}是多少歲？",
           "依創世記，{x}辭世時，{y}的歲數是多少？", "依創世記，{y}出生以後，{x}還活了幾年？")
BANK = {"F1": F1_BANK, "F5": F5_BANK}


def name_forms(father, son, x: str, y: str) -> dict[str, tuple[str, str]]:
    """(X as written, Y as written) per form; a marker form only where the chain has the marker person."""
    X, Y, out = nm(x), nm(y), {"plain": (nm(x), nm(y))}
    f, c = father(x), son(y)
    if f:
        F = nm(f)
        out |= {"x_son": (f"{F}的兒子{X}", Y), "x_zhi": (f"{F}之子{X}", Y), "x_br": (f"{X}（{F}的兒子）", Y),
                "x_br_half": (f"{X}({F}之子)", Y)}
    if c:
        C = nm(c)
        out |= {"y_father": (X, f"{C}的父親{Y}"), "y_zhi": (X, f"{C}之父{Y}"), "y_br": (X, f"{Y}（{C}的父親）"),
                "y_br_half": (X, f"{Y}({C}之父)")}
    if f and c:
        out["both"] = (out["x_son"][0], out["y_father"][1])
    return out


# ---------------------------------------------------------------- parse
def test_parse_reads_the_layer_and_the_names(L):
    assert L.order == tuple(r[0] for r in CH5 + CH11) and L.chains[11][0] == "G11.00"
    assert L.father("G05.00") is None and L.father("G05.04") == "G05.03" and L.son("G11.08") is None
    assert L.distance("G05.01", "G05.04") == 3 and L.distance("G05.04", "G05.01") is None
    assert L.distance("G05.01", "G11.04") is None and L.age_at_birth("G05.01", "G05.04") == 90 + 80 + 70
    assert L.lifespan["G11.02"] == 225 and L.lifespan["G11.08"] == 205 and L.taken == {"G05.06"}
    assert L.son_namesakes == {"羅伊"} and set(L.guarded) == {"凱", "史坦"}
    assert ("G05.09", "G11.00") in L.parents and set(COMMON["凱"]) <= set(L.blockers) and set(LEX) <= set(L.blockers)
    assert [len(b) for b in L.blockers] == sorted((len(b) for b in L.blockers), reverse=True)


def test_parse_refuses_a_names_file_of_another_chain_or_schema():
    gen = gen_doc()
    bad = names_doc(gen)
    bad["chain"] = bad["chain"][:-1]
    with pytest.raises(ValueError):
        gencard.parse(gen, bad, common_words=COMMON)
    with pytest.raises(ValueError):
        gencard.parse(gen, dict(names_doc(gen), schema="other"), common_words=COMMON)


def test_parse_refuses_a_names_file_of_another_text_layer():
    gen = gen_doc()
    with pytest.raises(ValueError, match="text layer"):
        gencard.parse(gen, dict(names_doc(gen), text_digest="other"), common_words=COMMON)


@pytest.mark.parametrize("key", ["lexicon_blockers", "cain_line", "gen_layer_sha256", "other_books"])
def test_parse_refuses_a_names_file_missing_a_contract_key(key):
    gen = gen_doc()
    with pytest.raises(ValueError, match=key):
        gencard.parse(gen, {k: v for k, v in names_doc(gen).items() if k != key}, common_words=COMMON)


def test_parse_refuses_a_names_file_with_a_key_the_contract_lacks():
    gen = gen_doc()
    with pytest.raises(ValueError, match="junk"):
        gencard.parse(gen, dict(names_doc(gen), junk=1), common_words=COMMON)


def test_parse_derives_the_run_together_blockers_of_a_guarded_name():
    """A guarded name run into a chain name that begins with its last character (史坦 + 坦…) is a blocker:
    the reading 史 + 坦… is as likely, so neither name counts."""
    gen = gen_doc()
    node = next(n for n in gen["nodes"] if n["id"] == "G11.06")
    node["name"] = "坦尼"
    L2 = gencard.parse(gen, names_doc(gen), common_words=COMMON)
    assert "史坦尼" in L2.blockers and not any(b.startswith("凱") and len(b) > 2 for b in L2.blockers)
    assert gencard.rule_seeds("依創世記，奧托幾歲時，史坦尼出生？", L2) == (None, SD.NO_PAIR)
    assert gencard.rule_seeds("依創世記，奧托幾歲時，史坦出生？", L2)[0] == ("G11.04", "G11.08")


def test_parse_copies_the_layer():
    gen = gen_doc()
    L = gencard.parse(gen, names_doc(gen), common_words=COMMON)
    gen["nodes"][0]["name"] = "改了"
    assert L.gen["nodes"][0]["name"] == "安東"


# ---------------------------------------------------------------- the bank on every pair
@pytest.mark.parametrize("form", ["F1", "F5"])
def test_every_phrasing_and_name_form_gives_the_pair_exactly_where_the_pool_shape_holds(L, form):
    wrong, fired, n = [], 0, 0
    for x, y in ALL_PAIRS:
        want = (x, y) if L.distance(x, y) >= 2 and oracle(x, y, form) else None
        for key, (xs, ys) in name_forms(L.father, L.son, x, y).items():
            for k, t in enumerate(BANK[form]):
                got, _why = gencard.rule_seeds(t.format(x=xs, y=ys), L)
                n, fired = n + 1, fired + (got is not None)
                if got != want:
                    wrong.append((x, y, key, k, got))
    assert not wrong, wrong[:5]
    assert n > 1000 and fired > 300


def test_trigger_and_card_agree_with_the_rule_seeds(L):
    for x, y in ALL_PAIRS:
        for form, bank in BANK.items():
            q = bank[0].format(x=nm(x), y=nm(y))
            t, (s, why), c = gencard.trigger(q, L), gencard.rule_seeds(q, L), gencard.card(q, L)
            assert (t.fired, t.seeds, t.reason) == (s is not None, s, why)
            assert (c is None) == (s is None) and (c is None or (c.seeds, c.reason) == (s, SD.OK))
            assert t.shape == (form if t.fired else None) and (t.step == 0) == t.fired


def test_the_pair_rule_never_finds_two_pairs(L):
    """Step 5's 'more than one pair' cannot happen: every subset of up to four chain ids has at most one."""
    for k in (2, 3, 4):
        for ids in itertools.combinations(L.order, k):
            assert len(SD.structural_pairs(L, ids)) <= 1


# ---------------------------------------------------------------- every abstention reason
# (question, step, reason); mostly 布朗 G05.01 > 戴維 G05.03 (in F1 shape) and 布朗 > 艾倫 G05.04 (in F5 shape)
REASON_CASES = (
    ("依某乙福音的家譜，布朗幾歲時，戴維出生？", 2, SD.OTHER_BOOK),
    ("依某丙志上，布朗去世那年，戴維幾歲？", 2, SD.OTHER_BOOK),
    ("依代上的家譜，布朗幾歲時，戴維出生？", 2, SD.OTHER_BOOK),
    ("依創世記，凱恩的後代葛林幾歲時，伊森出生？", 4, SD.CAIN_LINE),
    ("依創世記，霍華幾歲時，伊森出生？", 4, SD.CAIN_LINE),
    ("依創世記，溫柔伊森幾歲時，傑森出生？", 4, SD.CAIN_LINE),            # a rule-4 blocker never hides a chain name
    ("依創世記，保羅幾歲時，艾瑞克的兄弟羅伊出生？", 4, SD.ABRAM_FAMILY),
    ("依創世記，保羅幾歲時，史坦的兒子羅伊（艾瑞克的兄弟）出生？", 4, SD.ABRAM_FAMILY),
    ("依創世記，布朗活了多少歲？", 5, SD.NO_PAIR),
    ("依創世記，布朗幾歲時，卡爾出生？", 5, SD.NO_PAIR),                                  # d = 1
    ("依創世記，傑森幾歲時，李奧出生？", 5, SD.NO_PAIR),                                  # two chapters
    ("依創世記，布朗幾歲時，卡爾的兒子戴維出生？", 5, SD.NO_PAIR),                        # a person on the path
    ("依創世記，傑森的兒子凱幾歲時，麥斯出生？", 5, SD.NO_PAIR),                          # a marker across chapters
    ("依創世記，傑森幾歲時凱出生？", 5, SD.NO_PAIR),                                      # 凱 alone in chapter 11
    # a marker phrase whose marked name is no seed: the pair it leaves is not the one asked (布朗, 艾倫)
    ("依創世記，卡爾的父親布朗幾歲時，艾倫出生？", 5, SD.MARKED_OFF),
    ("依創世記，布朗（卡爾的父親）幾歲時，艾倫出生？", 5, SD.MARKED_OFF),
    ("依創世記，艾倫出生之後，卡爾的父親布朗又活了多少年？", 5, SD.MARKED_OFF),
    ("依創世記，安東去世那年，卡爾的兒子戴維幾歲？", 5, SD.MARKED_OFF),                    # asked (安東, 戴維)
    ("依創世記，安東去世那年，戴維（卡爾的兒子）幾歲？", 5, SD.MARKED_OFF),
    ("依創世記，布朗去世那年，艾倫的孫子費恩幾歲？", 5, SD.MARKED_OFF),                    # a kin word naming no seed
    ("依創世記，保羅幾歲時，史坦的兒子羅伊出生？", 6, SD.MARKER),
    ("依創世記，布朗幾歲時，艾倫的兒子戴維出生？", 6, SD.MARKER),                          # 艾倫 is 戴維's son
    ("依創世記，戴維（卡爾的父親）去世那年，費恩幾歲？", 6, SD.MARKER),                     # 卡爾 is 戴維's father
    ("依創世記，保羅去世那年，羅伊 （史坦的兒子）幾歲？", 6, SD.MARKER),                    # spaced as mech_g allows
    ("依創世記，保羅去世那年，羅伊( 史坦的兒子 )幾歲？", 6, SD.MARKER),
    ("依創世記，保羅去世那年，史坦的兒子 羅伊幾歲？", 6, SD.MARKER),
    ("依創世記，保羅去世那年，羅伊（史坦 的兒子）幾歲？", 6, SD.MARKER),
    ("依創世記，布朗和戴維是什麼關係？", 7, SD.NO_AGE_CUE),
    ("依創世記，布朗和戴維相差幾歲？", 7, SD.NO_EVENT_CUE),
    ("依創世記，布朗去世時，戴維出生多少年了？", 7, SD.MANY_FAMILIES),
    ("依創世記，戴維在洪水以後過了幾年才出生？布朗呢？", 7, SD.MANY_FAMILIES),
    ("依創世記，洪水那年，布朗和戴維各幾歲？", 7, SD.FLOOD),
    ("依創世記，布朗死後，艾倫又活了多少年？", 7, SD.DEATH_LIVED_ON),                      # 艾倫's years after
    ("依創世記，布朗去世以後，艾倫還活了幾年？", 7, SD.DEATH_LIVED_ON),
    ("依創世記，艾倫和布朗去世相隔多少年？", 7, SD.DEATH_SPAN),                            # the gap of two deaths
    ("依創世記，布朗過世時與艾倫相差幾歲？", 7, SD.DEATH_SPAN),
    ("依創世記，戴維幾歲時，布朗出生？", 8, SD.BORN_NOT_B),
    ("依創世記，戴維是在布朗幾歲時出生的？", 8, SD.BORN_NOT_B),                            # rule 7 as written (P1)
    ("依創世記，從布朗出生到戴維出生，隔了幾年？", 8, SD.BORN_NOT_B),
    ("依創世記，戴維去世時，布朗幾歲？", 8, SD.DYING_NOT_A),
    ("依創世記，戴維比布朗大幾歲？", 8, SD.OLDER_NOT_AB),
    ("依創世記，保羅幾歲時，史坦生了羅伊？", 8, SD.BEGETTER),                              # 史坦 is 羅伊's son
    ("依創世記，布朗幾歲時生了戴維？", 8, SD.BEGETTER),                                    # 布朗 is no father of 戴維
    ("依創世記，布朗去世那年，艾倫的兒子幾歲？", 8, SD.UNNAMED_KIN),                        # asks an unnamed son
    ("依創世記，布朗的兒子幾歲時，戴維出生？", 8, SD.UNNAMED_KIN),
    ("依創世記，布朗去世那年，艾倫的父親幾歲？", 8, SD.UNNAMED_KIN),
    ("依創世記，布朗之子幾歲時，戴維出生？", 8, SD.UNNAMED_KIN),
    ("依創世記，安東幾歲時，費恩出生？", 9, SD.F1_FAR),
    ("依創世記，戴維幾歲時，葛林出生？", 9, SD.F1_GONE),
    ("依創世記，戴維幾歲時，費恩出生？", 9, SD.F1_GONE),                                   # born the year 戴維 died
    ("依創世記，戴維去世那年，費恩幾歲？", 9, SD.F5_GONE),                                 # 費恩 born that year
    ("依創世記，葛林去世那年，伊森幾歲？", 9, SD.F5_TAKEN),
    ("依創世記，戴維去世那年，葛林幾歲？", 9, SD.F5_GONE),                                 # born after 戴維 died
    ("依創世記，李奧去世那年，尼克幾歲？", 9, SD.F5_GONE),                                 # 尼克 died first
    ("依創世記，布朗幾歲時，戴維出生？是不是？", 10, SD.YES_NO),
    ("依創世記，布朗去世那年，艾倫幾歲嗎", 10, SD.YES_NO),
    ("依創世記，誰比較老，布朗幾歲時戴維出生", 10, SD.YES_NO),
)


@pytest.mark.parametrize("q,step,reason", REASON_CASES)
def test_each_abstention_returns_its_step_and_reason(L, q, step, reason):
    t = gencard.trigger(q, L)
    assert (t.fired, t.step, t.reason, t.seeds) == (False, step, reason, None)
    assert gencard.rule_seeds(q, L) == (None, reason) and gencard.card(q, L) is None


def test_every_reason_but_the_unreachable_one_has_a_case():
    covered = {r for _q, _s, r in REASON_CASES}
    every = {r for rs in SD.REASONS.values() for r in rs}
    assert every - covered == {SD.MANY_PAIRS}
    assert all(r in SD.REASONS[s] for _q, s, r in REASON_CASES)


# ---------------------------------------------------------------- namesakes, markers, blockers
FIRES = (
    ("依創世記，保羅幾歲時，史坦的父親羅伊（不是艾瑞克的兄弟）出生？", ("G11.05", "G11.07")),   # rule 4's exception
    ("依創世記，保羅幾歲時，羅伊（史坦之父，不是艾瑞克的兄弟）出生？", None),                   # not a marker phrase
    ("依創世記，霍華德幾歲時，傑森出生？", ("G05.07", "G05.09")),                              # not the Cain line's 霍華
    ("依創世記，凱幾歲時，麥斯出生？", ("G11.00", "G11.02")),                                  # 凱 with a chapter mate
    ("依創世記，凱過世那年，奧托幾歲？", ("G11.00", "G11.04")),                                # 凱過 swallows no cue
    ("依創世記，昆汀幾歲時，史坦出生？", ("G11.06", "G11.08")),
    ("依創世記，奧托幾歲時，史坦出生？", ("G11.04", "G11.08")),                                # 史坦出 is no word
    ("依創世記，史坦著急地問：昆汀幾歲時羅伊出生？", None),                                    # 史坦著 is a word: d = 1
    ("依創世記，凱幾歲時，麥斯來到世上？", ("G11.00", "G11.02")),                              # 麥斯來 swallows no cue
    ("依創世記，凱旋那年，李奧幾歲時麥斯出生？", None),                                        # 凱旋 is a word: d = 1
    ("依創世記，凱旋那年，凱幾歲時麥斯出生？", ("G11.00", "G11.02")),
    ("依創世記，布朗尼幾歲時，戴維出生？", None),                                              # 布朗尼 is another name
    ("依創世記，葛林城建成時，費恩幾歲時伊森出生？", ("G05.05", "G05.08")),                    # 葛林城: no 葛林 on the path
    ("依創世記，布朗族幾歲時，戴維出生？", None),                                              # the tribe
    ("依創世記，卡爾比戴維大幾歲？", None),                                                     # d = 1
    ("依創世記，布朗比戴維大幾歲？", ("G05.01", "G05.03")),
    ("依創世記，布朗（安東的兒子）比戴維（艾倫的父親）大幾歲？", ("G05.01", "G05.03")),
    ("依創世記，安東之子布朗比艾倫之父戴維大多少歲？", ("G05.01", "G05.03")),
    ("依創世記，保羅幾歲時，羅伊 （史坦的父親）出生？", ("G11.05", "G11.07")),            # spaced bracket markers
    ("依創世記，保羅幾歲時，羅伊( 史坦的父親 )出生？", ("G11.05", "G11.07")),
    ("依創世記，保羅幾歲時，羅伊\u3000（\u3000史坦的父親\u3000）出生？", ("G11.05", "G11.07")),
    ("依創世記，保羅幾歲時，史坦的父親 羅伊出生？", ("G11.05", "G11.07")),
    ("依創世記，柯霍華德幾歲時，傑森出生？", ("G05.07", "G05.09")),                         # longest first: not 柯霍
    ("依創世記，奧托死城建成那年，昆汀幾歲時史坦出生？", ("G11.06", "G11.08")),              # 死 inside a blocker
    ("依創世記，溫柔伊始的那年，布朗幾歲時戴維出生？", ("G05.01", "G05.03")),                # 溫柔伊 hides 柔伊
    ("依創世記，布朗幾歲時，他的後代上一輩戴維出生？", ("G05.01", "G05.03")),                # 後代上 is no book
    ("依創世記，布朗幾歲時，第三代上的戴維出生？", ("G05.01", "G05.03")),
    ("依創世記，布朗的後代戴維出生時，布朗幾歲？", ("G05.01", "G05.03")),                    # a kin word naming a seed
)


@pytest.mark.parametrize("q,want", FIRES)
def test_namesake_marker_and_blocker_cases(L, q, want):
    assert gencard.rule_seeds(q, L)[0] == want


def test_a_blocker_overlapping_a_cue_word_is_skipped_but_one_holding_it_is_kept(L):
    q = TR.nfkc("凱過世，凱過一關")
    toks = TR.scan(q, L)
    assert [(t.text, t.kind) for t in toks] == [("凱", "chain"), ("凱過", "blocker")]


def test_a_guarded_name_counts_only_with_a_chapter_mate(L):
    assert TR.read("傑森幾歲時凱出生", L).ids == ("G05.09",)
    assert TR.read("凱幾歲時史坦出生", L).ids == ("G11.00", "G11.08")


def test_a_marker_phrase_is_one_mention_of_the_marked_name(L):
    r = TR.read("保羅幾歲時，羅伊（史坦的父親）出生", L)
    assert [m.id for m in r.mentions] == ["G11.05", "G11.07"] and r.claims == (TR.Claim("G11.07", "G11.08", "G11.07"),)
    assert TR.nearest_before(r.mentions, r.events[0].start).id == "G11.07"


def test_the_scan_takes_the_longest_name_first_and_a_tie_to_the_leftmost(L):
    assert [(t.text, t.kind) for t in TR.scan("柯霍華德", L)] == [("霍華德", "chain")]
    assert [(t.text, t.kind) for t in TR.scan("柔伊森", L)] == [("柔伊", "cain")]


def test_a_cue_word_inside_a_name_taken_is_no_cue(L):
    assert TR.read("奧托死城", L).events == () and not TR.read("尼克高齡鎮", L).age_cue
    assert TR.read("奧托死了", L).events and TR.read("尼克高齡", L).age_cue


def test_a_rule4_common_word_hides_its_name_but_never_a_chain_name(L):
    assert L.rule4_words == {"溫柔伊"} and "溫柔伊" in L.blockers and set(L.guarded) == {"凱", "史坦"}
    assert [(t.text, t.kind) for t in TR.scan("溫柔伊始", L)] == [("溫柔伊", "blocker")]
    assert [(t.text, t.kind) for t in TR.scan("溫柔伊森", L)] == [("柔伊", "cain")]


def test_a_common_word_overlapping_a_guarded_name_on_the_left_wins_the_tie(L):
    assert TR.read("奧托和昆汀，歷史坦然", L).ids == ("G11.04", "G11.06")


def test_dai_shang_is_a_book_only_as_an_abbreviation(L):
    assert [TR.read(q, L).other_book for q in ("後代上", "第三代上", "年代上", "世代上", "幾代上")] == [False] * 5
    assert [TR.read(q, L).other_book for q in ("依代上，", "代上1章", "(代上)", "對照代上的家譜")] == [True] * 4


def test_a_kin_word_after_a_name_names_the_next_one_or_leaves_the_person_unnamed(L):
    r = TR.read("布朗的後代戴維", L)
    assert r.kin_named == ("G05.03",) and not r.kin_unnamed
    assert TR.read("布朗的兒子幾歲", L).kin_unnamed and TR.read("布朗之孫", L).kin_unnamed
    assert TR.read("布朗的孫子 戴維", L).kin_named == ("G05.03",)
    assert not TR.read("安東的兒子布朗", L).kin_unnamed and TR.read("安東的兒子布朗", L).kin_named == ()
    assert not TR.read("戴維出生之後，布朗又活了", L).kin_unnamed                # 之後 is no kin word


def test_a_marker_on_the_path_never_gives_a_pair(L):
    """X written through his chain son A (「A的父親X」, 「X（A的父親）」) or Y's son C asked through Y (「Y的兒子C」,
    「C（Y的兒子）」): the name on the path leaves a structural pair that is not the one asked, so nothing fires."""
    fired, n = [], 0
    for x, y in ALL_PAIRS:
        a, c = L.son(x), L.son(y)
        forms = [(f"{nm(a)}的父親{nm(x)}", nm(y)), (f"{nm(x)}（{nm(a)}的父親）", nm(y))] if a else []
        forms += [(nm(x), f"{nm(y)}的兒子{nm(c)}"), (nm(x), f"{nm(c)}（{nm(y)}的兒子）")] if c else []
        for (xs, ys), t in itertools.product(forms, F1_BANK + F5_BANK):
            q, n = t.format(x=xs, y=ys), n + 1
            if gencard.rule_seeds(q, L)[0] is not None:
                fired.append((x, y, q))
    assert n > 5000 and fired == [], fired[:3]


def test_every_marker_spelling_mech_g_accepts_is_read_as_the_marker(L):
    """The contract with mech_g: each spaced bracket marker its _marker_forms accepts gives the pair (or the
    pool shape's abstention) exactly as the unspaced one does."""
    import mech_g as M
    import prompts_g as P
    n = 0
    for (x, y), form in itertools.product(SIX, ("F1", "F5")):
        want = (x, y) if oracle(x, y, form) else None
        for end, person, (xs, ys) in spaced_markers(L, x, y):
            marker = f"{person}的{'父親' if end == 'Y' else '兒子'}{nm(y) if end == 'Y' else nm(x)}"
            spec = P.SlotSpec(sid="S", qid="q", slot_id="q", qtype=form, chapter=int(x[1:3]), x_id=x, y_id=y,
                              x=nm(x), y=nm(y), path=(), marker=marker, marker_person=person, marker_end=end)
            pattern = M._marker_forms(spec)
            for t in BANK[form]:
                q, n = t.format(x=xs, y=ys), n + 1
                assert pattern.search(M.norm(q)) and gencard.rule_seeds(q, L)[0] == want, (x, y, form, q)
    assert n > 5000


# the synthetic twins of prereg §2.2's six marker slots: Y = 羅伊 (史坦's son bears that name) from 尼克, 奧托
# and 保羅; through the Cain line's namesakes, (安東, 葛林), (安東, 伊森), (葛林, 伊森)
SIX = (("G11.03", "G11.07"), ("G11.04", "G11.07"), ("G11.05", "G11.07"), ("G05.00", "G05.06"), ("G05.00", "G05.08"),
       ("G05.06", "G05.08"))
SPACES = ("", " ", "\u3000", "\t")                     # mech_g's \s* around and inside a bracket marker


def spaced_markers(L, x: str, y: str) -> list[tuple[str, str, tuple[str, str]]]:
    """(marker end, marker person, (X as written, Y as written)): every bracket marker spelled with spaces."""
    out, c, f = [], L.son(y), L.father(x)
    for s1, s2, s3 in itertools.product(SPACES, repeat=3):
        if c:
            out.append(("Y", nm(c), (nm(x), f"{nm(y)}{s1}（{s2}{nm(c)}的父親{s3}）")))
        if f:
            out.append(("X", nm(f), (f"{nm(x)}{s1}({s2}{nm(f)}的兒子{s3})", nm(y))))
    return out


def test_the_six_marker_shapes_give_the_pair_with_either_marker(L):
    fired = 0
    for (x, y), form in itertools.product(SIX, ("F1", "F5")):
        forms = {k: v for k, v in name_forms(L.father, L.son, x, y).items() if k != "plain"}
        assert forms, (x, y)
        for (xs, ys), t in itertools.product(forms.values(), BANK[form]):
            got = gencard.rule_seeds(t.format(x=xs, y=ys), L)[0]
            assert got == ((x, y) if oracle(x, y, form) else None), (x, y, form)
            fired += got is not None
    assert fired > 200


def test_namesake_traps_on_every_pair_abstain(L):
    """A Cain-line or Abram-family name, another book, no cue or a yes/no word: no pair ever fires."""
    traps = ("依創世記，凱恩的後代{x}幾歲時，{y}出生？", "依創世記，{x}幾歲時，艾瑞克家的{y}出生？",
             "依某乙福音的家譜，{x}幾歲時，{y}出生？", "依創世記，{x}和{y}是什麼關係？",
             "依創世記，{x}去世那年，{y}幾歲嗎？", "依創世記，{y}去世那年，{x}幾歲？",
             "依創世記，{y}幾歲時，{x}出生？", "依創世記，{x}在洪水以後過了幾年才出生？{y}呢？")
    fired = [(x, y, k) for x, y in ALL_PAIRS for k, t in enumerate(traps)
             if gencard.rule_seeds(t.format(x=nm(x), y=nm(y)), L)[0] is not None]
    assert fired == []


# ---------------------------------------------------------------- cue literals
def test_cue_literals_hold_every_word_of_rules_7_and_10():
    want = ("幾歲", "多少歲", "多大", "年紀", "年齡", "歲數", "高齡", "多老", "年歲", "相隔", "相差", "間隔", "相距", "隔了",
            "差了", "多少年", "幾年", "多久", "出生", "誕生", "出世", "降生", "來到世上", "生了", "生下", "生出", "得了", "去世",
            "過世", "離世", "逝世", "辭世", "死", "壽終", "離開人世", "大幾歲", "大多少歲", "又活", "還活", "是否", "是不是",
            "有沒有", "嗎", "誰比較", "哪一位")
    assert set(want) <= set(gencard.CUE_LITERALS) and len(set(gencard.CUE_LITERALS)) == len(gencard.CUE_LITERALS)
    assert isinstance(gencard.CUE_LITERALS, tuple) and all(isinstance(w, str) and w for w in gencard.CUE_LITERALS)
    assert not {"的父親", "的兒子", "之父", "之子", "比"} & set(gencard.CUE_LITERALS)       # marker strings stay writable


# ---------------------------------------------------------------- the card
def test_card_for_seeds_is_engine_xs_genesis_branch(L):
    for x, y in pairs(5, 2) + pairs(11, 2):
        window, core, texts, lines = E.gen_parts(L.gen, [x, y])
        rows, kept, _dr, _dl = E.fit(texts, window, core, lines, 900)
        c = gencard.card_for_seeds((x, y), L)
        assert c.g_block == E.render([texts[r] for r in rows], [(ln["head"], ln["payload"]) for ln in kept])
        assert c.t_block == E.render([texts[r] for r in rows], []) and c.rows == tuple(rows)
        assert c.g_block.startswith(c.t_block + "\n" + E.DERIVED_HEADER) and c.chars_g == len(c.g_block)
        born = next(ln["value"] for ln in kept if ln["kind"] == "born_age") if oracle(x, y, "F1") else None
        assert born is None or c.covers(born)


def test_covers_reads_the_kept_lines(L):
    c = gencard.card_for_seeds(("G05.01", "G05.03"), L)
    assert c.covers(170) and c.covers(790) and c.covers(500)          # born_age 90+80; lifespan; 戴維 died first
    assert not c.covers(171) and not c.covers(620) and not c.covers(170, ("Y",))


def test_card_for_seeds_refuses_two_chapters(L):
    with pytest.raises(ValueError):
        gencard.card_for_seeds(("G05.01", "G11.03"), L)


# ---------------------------------------------------------------- the package
def test_engine_is_a_verbatim_copy_of_engine_xs_genesis_functions():
    src_x = (GC.STAGE0_DIR / "engine_x.py").read_text(encoding="utf-8")
    src_g = (PKG / "engine.py").read_text(encoding="utf-8")

    def segments(src: str) -> dict:
        lines = src.splitlines(keepends=True)
        out = {}
        for node in ast.parse(src).body:
            key = node.name if isinstance(node, ast.FunctionDef) else (
                node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None)
            if key:
                out[key] = "".join(lines[node.lineno - 1:node.end_lineno])
        return out
    sx, sg = segments(src_x), segments(src_g)
    copied = [k for k in sg if k not in ("DERIVED_HEADER", "CAP_CHARS")]
    assert len(copied) == 21 and all(sg[k] == sx[k] for k in copied), [k for k in copied if sg[k] != sx.get(k)]
    a_engine = (GC.REPO / "evaluation/experiments/2026-10-18_kg_cards/A/engine.py").read_text(encoding="utf-8")
    want = next(n.value.value for n in ast.parse(a_engine).body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DERIVED_HEADER")
    assert E.DERIVED_HEADER == want and E.CAP_CHARS == GC.stage0().x_common.CAP_CHARS == 900


STDLIB_USED = {"__future__", "bisect", "collections", "copy", "dataclasses", "re", "types", "typing", "unicodedata"}


def test_gencard_uses_only_the_standard_library_and_relative_imports():
    for p in sorted(PKG.glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert {a.name.split(".")[0] for a in node.names} <= STDLIB_USED, p.name
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module.split(".")[0] in STDLIB_USED, (p.name, node.module)
    assert STDLIB_USED <= set(sys.stdlib_module_names)
    assert sorted(p.name for p in PKG.glob("*.py")) == ["__init__.py", "card.py", "engine.py", "names.py", "seeds.py",
                                                         "trigger.py"]


def test_the_public_api():
    assert set(gencard.__all__) >= {"parse", "trigger", "rule_seeds", "card", "card_for_seeds", "CUE_LITERALS"}


# ---------------------------------------------------------------- ReDoS
LIMIT_S = 0.03            # the slowest case (trigger and card) takes about 2 ms
MAX_CHARS = 500
CJK_RUN = re.compile("[\u4e00-\u9fff]+")
FILLS = ("，", "、", ",", " ", "的", "了", "(", "（", "）", "比", "的父親", "的兒子")


def _alarm(_sig, _frame):
    raise TimeoutError


def _took(L, q: str) -> float:
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(2)
    try:
        t = time.perf_counter()
        gencard.trigger(q, L)
        gencard.card(q, L)
        return time.perf_counter() - t
    except TimeoutError:
        return float("inf")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _cases():
    code = "".join((PKG / f).read_text(encoding="utf-8") for f in ("trigger.py", "seeds.py", "names.py"))
    runs = set(CJK_RUN.findall(code))
    lits = sorted(set(gencard.CUE_LITERALS) | set("".join(gencard.CUE_LITERALS)) | runs | set("".join(runs)))
    names = [r[1] for r in CH5 + CH11]
    for lit in lits:
        for fill in (*FILLS, lit):
            yield ("安東" + lit + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"
    for unit in [n + "的兒子" for n in names] + names + [f"({n}的父親)" for n in names] + ["比安東大幾歲", "凱過世"]:
        yield (unit * MAX_CHARS)[:MAX_CHARS]
    for t in F1_BANK + F5_BANK:
        ex = t.format(x="布朗", y="戴維")
        for k in range(1, len(ex) + 1, 3):
            for fill in FILLS:
                yield (ex[:k] + fill * MAX_CHARS)[:MAX_CHARS - 1] + "x"


def test_no_question_of_500_characters_takes_long(L):
    slow = [(q[:10], t) for q in _cases() if (t := _took(L, q)) > LIMIT_S]
    assert not slow, slow[:5]


# ---------------------------------------------------------------- store: the real layer and names
@pytest.fixture(scope="module")
def R():
    return gencard.parse(GC.read_json(GC.GEN_LAYER), GC.read_json(GC.GEN_NAMES))


@pytest.fixture(scope="module")
def pool():
    return GC.read_json(GC.POOL)["pool"]


@needs_store
def test_real_layer_parses_with_one_son_namesake_and_two_guarded_names(R):
    assert len(R.order) == 19 and [len(R.chains[5]), len(R.chains[11])] == [10, 9]
    assert {R.id_of[n] for n in R.son_namesakes} == {"G11.07"} and {R.id_of[n] for n in R.guarded} == {"G11.00", "G11.08"}
    assert R.taken == {"G05.06"} and GC.sha256_file(GC.GEN_LAYER) == R.gen_layer_sha256


@needs_store
def test_real_pair_rule_never_finds_two_pairs(R):
    assert all(len(SD.structural_pairs(R, ids)) <= 1 for k in (2, 3, 4) for ids in itertools.combinations(R.order, k))


@needs_store
def test_real_cards_equal_stage0s_engine_x_on_all_64_same_chapter_pairs(R):
    S = GC.stage0()
    gen, n = S.gen_layer.load(), 0
    for ch in (5, 11):
        ids = S.gen_layer.chain(gen, ch)
        for i, j in ((i, j) for i in range(len(ids)) for j in range(i + 2, len(ids))):
            x, y = ids[i], ids[j]
            for gold in {ln["value"] for ln in S.engine_x.gen_pair_lines(gen, x, y)} | {None}:
                item = {"family": "GEN", "seeds": [x, y], "gold": gold,
                        "keys": [{"type": "arith", "classes": ["A", "Y"]}]}
                want, got = S.engine_x.card(item, gen=gen), gencard.card_for_seeds((x, y), R)
                assert (got.g_block, got.t_block, list(got.rows)) == (want["g_block"], want["t_block"], want["rows"])
                assert [list(p) for p in got.lines] == want["lines"] and got.chars_g == want["chars_g"]
                tags = [dict(zip(("kind", "seeds", "k", "value", "unit"), (t[0], list(t[1]), *t[2:]))) for t in got.tags]
                assert tags == want["tags"]
                assert gold is None or got.covers(gold) == want["covered"]
            n += 1
    assert n == 64


REAL_F1 = ("依創世記所載，{x}幾歲時，{y}出生？", "根據創世記，{y}出生的時候，{x}多大年紀？",
           "照創世記的記載，{x}比{y}大幾歲？", "依創世記，{x}和{y}兩人出生相隔多少年？",
           "創世記中，{y}誕生那一年，{x}是多少歲？")
REAL_F5 = ("依創世記所載，{x}去世那年，{y}幾歲？", "根據創世記，{x}過世的時候，{y}多大了？",
           "依創世記，{y}出生之後，{x}又活了多少年？", "按創世記的記載，{x}死的時候{y}的年紀是多少？",
           "創世記中，{x}壽終時，{y}已經活了多久？")
REAL = {"F1": REAL_F1, "F5": REAL_F5}


def real_forms(R, x: str, y: str, marker: bool) -> dict[str, tuple[str, str]]:
    X, Y = R.name[x], R.name[y]
    if not marker:
        return {"plain": (X, Y)}
    f, c = R.father(x), R.son(y)
    out = {}
    if f:
        out |= {"x_son": (f"{R.name[f]}的兒子{X}", Y), "x_br": (f"{X}（{R.name[f]}的兒子）", Y)}
    if c:
        out |= {"y_father": (X, f"{R.name[c]}的父親{Y}"), "y_br": (X, f"{Y}（{R.name[c]}的父親）"),
                "y_zhi": (X, f"{R.name[c]}之父{Y}")}
    return out


def real_pins(R, pool) -> list[tuple[str, str, tuple[str, str]]]:
    """(sid, question, gold pair) of every code-built variant of every pool slot (6 slots with markers)."""
    out = []
    for s in pool:
        for key, (xs, ys) in real_forms(R, s["x"], s["y"], s["marker_required"]).items():
            out += [(s["sid"], t.format(x=xs, y=ys), (s["x"], s["y"])) for t in REAL[s["qtype"]]]
    return out


@needs_store
def test_real_variants_of_all_58_slots_give_the_exact_seeds(R, pool):
    pins = real_pins(R, pool)
    wrong = [sid for sid, q, gold in pins if gencard.rule_seeds(q, R)[0] != gold]
    assert len(pool) == 58 and sum(s["marker_required"] for s in pool) == 6
    assert not wrong, sorted(set(wrong))
    assert len(pins) >= 58 * 5 and len({sid for sid, _q, _g in pins}) == 58


@needs_store
def test_real_marker_slots_without_their_marker_still_give_the_chain_pair(R, pool):
    """The rule reads chain names as the chain persons: the marker is a writing rule for the reader (prereg
    §2.2), not a condition of the rule."""
    marked = [s for s in pool if s["marker_required"]]
    got = [gencard.rule_seeds(REAL[s["qtype"]][0].format(x=R.name[s["x"]], y=R.name[s["y"]]), R)[0] for s in marked]
    assert got == [(s["x"], s["y"]) for s in marked]


@needs_store
def test_real_scope_on_every_same_chapter_pair_is_the_pool_shape(R):
    """F1 and F5 phrasings fire exactly on the pairs stage-0's candidate rules admit (gen_layer arithmetic),
    the famous-number and 1000 exclusions aside."""
    S = GC.stage0()
    gen, G = S.gen_layer.load(), S.gen_layer
    taken = {S.engine_x.TAKEN_ID}
    for ch in (5, 11):
        ids = G.chain(gen, ch)
        for i, j in ((i, j) for i in range(len(ids)) for j in range(i + 1, len(ids))):
            x, y = ids[i], ids[j]
            age = G.age_at_birth(gen, x, y)
            want = {"F1": j - i >= 2 and j - i <= 4 and age < G.total(gen, x),
                    "F5": j - i >= 2 and x not in taken and 0 < G.total(gen, x) - age < G.total(gen, y)}
            for form, bank in REAL.items():
                for t in bank:
                    assert (gencard.rule_seeds(t.format(x=R.name[x], y=R.name[y]), R)[0] == (x, y)) == want[form]


@needs_store
def test_real_pool_slots_are_inside_the_scope_and_every_candidate_is_too(R):
    S = GC.stage0()
    gen = S.gen_layer.load()
    cands = S.items_x.f1_candidates(gen, {}) + S.items_x.f5_candidates(gen, {})
    for c in cands:
        x, y = c["path"][0], c["path"][-1]
        assert gencard.rule_seeds(REAL[c["qtype"]][0].format(x=R.name[x], y=R.name[y]), R)[0] == (x, y)
    assert len(cands) == 72


# the chain persons by position (chapter 5, then 11): the store tests name them only through the real layer
CH5_ROLES = ("adam", "seth", "enosh", "kenan", "mahalalel", "jared", "enoch", "methuselah", "lamech", "noah")
CH11_ROLES = ("shem", "arpachshad", "shelah", "eber", "peleg", "reu", "serug", "nahor", "terah")


def real_ids(R) -> dict[str, str]:
    return dict(zip(CH5_ROLES, R.chains[5])) | dict(zip(CH11_ROLES, R.chains[11]))


def real_names(R) -> dict[str, str]:
    return {k: R.name[v] for k, v in real_ids(R).items()}


def misread(R, cases) -> list[int]:
    """The indexes of the (question, want) cases whose rule_seeds differ (no question text in the output)."""
    return [i for i, (q, want) in enumerate(cases) if gencard.rule_seeds(q, R) != want]


def blocker_pins(R) -> list[tuple[str, tuple[str, str]]]:
    """(question, gold pair): the chapter-11 head (a guarded name) with every death word and the chapter's last
    (a guarded name) with every birth word, as the pool's F5 (shem, eber) and F1 (reu, terah); eber before
    來到世上 (eber's lexicon superstring overlaps the cue); every common word of names.py next to (reu, terah)."""
    I, N = real_ids(R), real_names(R)
    out = [(f"依創世記，{N['shem']}{w}那年，{N['eber']}幾歲？", (I["shem"], I["eber"])) for w in TR.DEATH_WORDS]
    out += [(f"依創世記，{N['reu']}幾歲時，{N['terah']}{w}？", (I["reu"], I["terah"])) for w in TR.BIRTH_WORDS]
    out += [(f"依創世記，{N['arpachshad']}幾歲時，{N['eber']}來到世上？", (I["arpachshad"], I["eber"]))]
    words = [w for ws in NM.COMMON_WORDS.values() for w in ws]
    return out + [(f"依創世記，{w}之後，{N['reu']}幾歲時{N['terah']}出生？", (I["reu"], I["terah"])) for w in words]


@needs_store
def test_real_blocker_never_swallows_a_cue(R):
    pins = blocker_pins(R)
    assert len(pins) > 40 and misread(R, [(q, (g, SD.OK)) for q, g in pins]) == []


@needs_store
def test_real_namesake_cases(R):
    I, N = real_ids(R), real_names(R)
    peleg, nahor, terah = N["peleg"], N["nahor"], N["terah"]
    cases = [(f"依創世記，{peleg}幾歲時，{terah}的父親{nahor}（不是{a}的兄弟）出生？", ((I["peleg"], I["nahor"]), SD.OK))
             for a in R.abram_family]                                                  # rule 4's exception
    cases += [(f"依創世記，{peleg}幾歲時，{terah}的兒子{nahor}出生？", (None, SD.MARKER)),
              (f"依創世記，{peleg}幾歲時，{terah}生了{nahor}？", (None, SD.BEGETTER))]      # the begetter's son
    cases += [(f"依創世記，{peleg}幾歲時，{a}的兄弟{nahor}出生？", (None, SD.ABRAM_FAMILY)) for a in R.abram_family]
    cases += [(f"依創世記，{c}的後代{N['enoch']}幾歲時，{N['lamech']}出生？", (None, SD.CAIN_LINE)) for c in R.cain_line]
    cases += [(f"依創世記，{N['jared']}的兒子{N['enoch']}幾歲時，{N['noah']}的父親{N['lamech']}出生？",
               ((I["enoch"], I["lamech"]), SD.OK)),
              (f"依創世記，{N['methuselah']}比{N['noah']}大幾歲？", ((I["methuselah"], I["noah"]), SD.OK))]  # chain first
    assert len(cases) > 25 and misread(R, cases) == []


@needs_store
def test_real_a_marker_on_the_path_never_gives_a_pair(R):
    """The real twin of test_a_marker_on_the_path_never_gives_a_pair, on every same-chapter pair."""
    fired, n = [], 0
    for ch in (5, 11):
        ids = R.chains[ch]
        for x, y in ((ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))):
            a, c, X, Y = R.son(x), R.son(y), R.name[x], R.name[y]
            forms = [(f"{R.name[a]}的父親{X}", Y), (f"{X}（{R.name[a]}的父親）", Y)] if a else []
            forms += [(X, f"{Y}的兒子{R.name[c]}"), (X, f"{R.name[c]}（{Y}的兒子）")] if c else []
            for (xs, ys), t in itertools.product(forms, REAL_F1 + REAL_F5):
                n += 1
                if gencard.rule_seeds(t.format(x=xs, y=ys), R)[0] is not None:
                    fired.append((x, y))
    assert n > 1000 and fired == []


@needs_store
def test_real_marker_slots_read_every_spelling_mech_g_accepts(R, pool):
    import mech_g as M
    import prompts_g as P
    names, bad, n = P.load_names(), [], 0
    for s in (s for s in pool if s["marker_required"]):
        spec = P.slot_spec(s, names, "Q01")
        rel, end = ("父親", spec.y) if spec.marker_end == "Y" else ("兒子", spec.x)
        pattern = M._marker_forms(spec)
        for s1, s2, s3 in itertools.product(SPACES, repeat=3):
            br = f"{end}{s1}（{s2}{spec.marker_person}的{rel}{s3}）"
            xs, ys = (spec.x, br) if spec.marker_end == "Y" else (br, spec.y)
            for t in REAL[s["qtype"]]:
                q, n = t.format(x=xs, y=ys), n + 1
                if not pattern.search(M.norm(q)) or gencard.rule_seeds(q, R)[0] != (s["x"], s["y"]):
                    bad.append(s["sid"])
    assert n == 6 * len(SPACES) ** 3 * 5 and sorted(set(bad)) == []


@needs_store
def test_real_other_quantities_unnamed_kin_and_off_seed_markers_abstain(R):
    N = real_names(R)
    a, e, s, m = N["adam"], N["enosh"], N["seth"], N["mahalalel"]
    cases = [(f"依創世記，{a}死後，{e}又活了多少年？", SD.DEATH_LIVED_ON),
             (f"依創世記，{a}去世以後，{e}還活了幾年？", SD.DEATH_LIVED_ON),
             (f"依創世記，{e}和{a}去世相隔多少年？", SD.DEATH_SPAN),
             (f"依創世記，{a}去世那年，{e}的孫子幾歲？", SD.UNNAMED_KIN),
             (f"依創世記，{a}去世那年，{e}的父親幾歲？", SD.UNNAMED_KIN),
             (f"依創世記，{a}的兒子幾歲時，{e}出生？", SD.UNNAMED_KIN),
             (f"依創世記，{e}的父親{s}幾歲時，{m}出生？", SD.MARKED_OFF),
             (f"依創世記，{a}去世那年，{e}的兒子{N['kenan']}幾歲？", SD.MARKED_OFF),
             (f"依創世記，{m}出生之後，{e}的父親{s}又活了多少年？", SD.MARKED_OFF),
             (f"依創世記，{s}（{e}的父親）幾歲時，{m}出生？", SD.MARKED_OFF),
             (f"依創世記，{a}去世那年，{N['kenan']}（{e}的兒子）幾歲？", SD.MARKED_OFF),
             (f"依創世記，{N['peleg']}去世那年，{N['nahor']}的兒子{N['terah']}幾歲？", SD.MARKED_OFF),
             (f"依創世記，{m}是在{s}幾歲時出生的？", SD.BORN_NOT_B)]          # rule 7 as written: raised for P1
    assert misread(R, [(q, (None, why)) for q, why in cases]) == []


@needs_store
def test_real_book_abbreviation_rule4_common_words_and_run_together_names(R):
    I, N = real_ids(R), real_names(R)
    a, e, terah, reu = N["adam"], N["enosh"], N["terah"], N["reu"]
    rule4 = [w for name, ws in NM.COMMON_WORDS.items() if name in R.cain_line for w in ws]
    left = [w for w in NM.COMMON_WORDS[terah] if w.endswith(terah[0]) and not w.startswith(terah)]
    assert rule4 and left and reu[0] == terah[-1] == N["lamech"][0]
    assert {terah[:-1] + reu, terah[:-1] + N["lamech"]} <= set(R.blockers)
    fires = [(f"依創世記，{a}幾歲時，他的後代上一輩{e}出生？", (I["adam"], I["enosh"]))]
    fires += [(f"依創世記，{w}{a}和{e}來算：{a}幾歲時{e}出生？", (I["adam"], I["enosh"])) for w in rule4]
    fires += [(f"依創世記，{N['peleg']}去世那年，{w}{terah[1:]}丁譯本裡{N['serug']}幾歲？", (I["peleg"], I["serug"]))
              for w in left]
    cases = [(q, (g, SD.OK)) for q, g in fires]
    cases += [(f"依創世記，{N['peleg']}去世時，{terah[:-1]}{reu}幾歲？", (None, SD.NO_PAIR)),
              (f"依創世記，{N['serug']}去世那年，{left[0]}{reu}的後代幾歲？", (None, SD.NO_PAIR))]
    assert misread(R, cases) == []


@needs_store
def test_real_stage0_templates_give_the_gold_pair_and_f3_abstains(R):
    items = [it for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"] if it["family"] == "GEN"]
    got = {it["id"]: gencard.rule_seeds(it["question"], R)[0] for it in items}
    f15 = [it for it in items if it["qtype"] in ("F1", "F5")]
    f3 = [it for it in items if it["qtype"] == "F3"]
    assert (len(f15), len(f3)) == (14, 4)
    assert sum(got[it["id"]] == tuple(it["seeds"]) for it in f15) == 14
    assert sum(got[it["id"]] is None for it in f3) == 4


def _real_questions() -> dict[str, list[str]]:
    out = {}
    for f in ("ground_truth.json", "ground_truth.v2.json"):
        out[f] = [q["question"] for q in GC.read_json(GC.REPO / f)["questions"]]
    out["A_confirm"] = [q["question"] for q in
                        GC.read_json(GC.STORE / "reports/kg_cards_20261018/A_confirm/questions_frozen.json")["questions"]]
    out["stage0_other"] = [it["question"] for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"]
                           if it["family"] in ("DYN", "S6", "SYNC")]
    return out


@needs_store
def test_real_rule_fires_on_none_of_the_gt_a_and_stage0_dynasty_questions(R):
    qs = _real_questions()
    sizes = [len(qs[k]) for k in ("ground_truth.json", "ground_truth.v2.json", "A_confirm", "stage0_other")]
    assert sizes == [500, 500, 32, 34]
    assert {k: sum(gencard.card(q, R) is not None for q in v) for k, v in qs.items()} == {k: 0 for k in qs}
    assert {k: sum(gencard.trigger(q, R).fired for q in v) for k, v in qs.items()} == {k: 0 for k in qs}


@needs_store
def test_real_prod_dynasty_trigger_fires_on_none_of_the_pins(R, pool):
    for p in (GC.REPO / "backend", GC.REPO / "packages"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from ragcommon import routing
    from utils.regnal import layer as LY
    from utils.regnal import trigger as PT
    lay = LY.with_lexicon(LY.parse_layer(GC.R4_LAYER.read_bytes()),
                          routing.load_lexicon(GC.R4_LAYER.with_name("routing_lexicon.json")))
    assert GC.sha256_file(GC.R4_LAYER) == GC.R4_LAYER_SHA256
    items = [it["question"] for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"] if it["family"] == "GEN"]
    pins = [q for _sid, q, _g in real_pins(R, pool)] + [q for q, _g in blocker_pins(R)] + items
    assert len(pins) > 300 and sum(PT.trigger(q, lay.names, lay.blockers).fired for q in pins) == 0


def windows(s: str) -> set[str]:
    return {s[i:i + WINDOW] for i in range(len(s) - WINDOW + 1)}


def real_texts() -> dict[str, list[str]]:
    """Every real text no repo file may share a window with: the verses, GT v1/v2, A's frozen confirm questions
    and all of stage-0's item questions (the store's development set, in no committed file)."""
    text = GC.STORE / "layers/text/text@247eafe44b02/verse_units.jsonl"
    out = {"verses": [json.loads(line)["text"] for line in text.read_text(encoding="utf-8").splitlines()]}
    out |= {k: v for k, v in _real_questions().items() if k != "stage0_other"}
    out["stage0_items"] = [it["question"] for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"]]
    return out


@needs_store
def test_these_files_share_no_window_with_a_verse_or_a_real_question():
    """repo 不放任何經節字串與真實題目: no 8-character window of gencard/*.py or this file (as written or NFKC) is
    in a verse or a real question (counts only)."""
    mine = set()
    for p in [Path(__file__)] + sorted(PKG.glob("*.py")):
        src = p.read_text(encoding="utf-8")
        mine |= windows(src) | windows(TR.nfkc(src))
    texts = real_texts()
    hits = {k: sum(bool((windows(t) | windows(TR.nfkc(t))) & mine) for t in v) for k, v in texts.items()}
    assert [len(texts[k]) > 0 for k in texts] == [True] * 5 and hits == {k: 0 for k in texts}
