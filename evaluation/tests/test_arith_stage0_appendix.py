"""Ordered-chain arithmetic stage-0 appendix (appendix_x.py; prereg §1 輸出, §11-3).

The leak check runs on made-up texts (王甲, 假經文 …). The store-backed tests build the store files into a
temporary output root (x_common.OUT_ROOT), write the appendix to a temporary path (never into the
repository) and check it against the store's text layer: no 8-character window of any verse, no question
text, no card line. The repository's appendix.md, once written, is checked the same way against the real
store build. They skip when the store is not mounted. Nothing here calls Ollama.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import appendix_x as AP  # noqa: E402
import run_x as R  # noqa: E402
import x_common as X  # noqa: E402

STORE_OK = X.REF_V2.is_file() and X.R4_LAYER.is_file() and (X.TEXT / "verse_units.jsonl").is_file() and \
    (X.STORE / "reports/kg_cards_20261018/A_confirm/scores.json").is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({X.STORE})")
TESTS_STUB = {"files": ["evaluation/tests/x.py"], "files_sha256": {"evaluation/tests/x.py": "ab" * 32},
              "returncode": 0, "summary": "stub", "pass": True}


def test_leak_problems_on_made_up_texts():
    verse = "起初王甲造了假城與假塔的事"
    q = {"Q1": "王甲到王丙一共幾年？"}
    clean = "| Q1 | DYN | S5 | 76 |"
    assert AP.leak_problems(clean, q, ["王甲：在位二十年；生王乙"], [verse]) == []
    assert AP.leak_problems(f"x {verse[2:10]} y", q, [], [verse]) == ["1 verses share an 8-character window with the appendix"]
    assert AP.leak_problems(f"x {verse[2:9]} y", q, [], [verse]) == []                 # 7 characters is not a window
    assert AP.leak_problems("備註：王甲到王丙一共幾", q, [], []) == ["question text of Q1"]
    assert AP.leak_problems("見 王甲：在位二十年；生王乙", {}, ["王甲：在位二十年；生王乙"], []) == ["card line 王甲：在…"]
    assert AP.windows("甲乙丙", 2) == {"甲乙", "乙丙"}


def test_cells_on_made_up_items():
    sync = {"id": "SYNC2_01", "family": "SYNC", "gold": {"Y": "王乙", "Z": "王丁"}, "seeds": ["A01"],
            "seeds_ref": ["I01"], "seed_names": [["I", "王甲"]],
            "keys": [{"type": "name", "role": "Y", "gold_ref": "I03"}, {"type": "name", "role": "Z", "gold_ref": "J02"}]}
    assert AP.gold_cell(sync) == "Y＝I03 王乙；Z＝J02 王丁"
    assert AP.seeds_cell(sync) == "A01 王甲（參照層 I01）"
    gen = {"gold": 130, "seeds": ["G05.00", "G05.02"], "seeds_ref": None, "seed_names": [[None, "甲"], [None, "丙"]]}
    assert AP.gold_cell(gen) == "130" and AP.seeds_cell(gen) == "G05.00 甲 / G05.02 丙"
    assert AP.flag_text("homonym shown as 乙的父親甲") == "同名人物，題目以不在路徑上的親屬名辨識（§3.4）"
    assert AP.flag_text("other flag") == "other flag"


def test_write_refuses_the_repository_but_appendix_md(tmp_path):
    with pytest.raises(SystemExit, match="inside the repository"):
        AP.write(X.HERE / "other.md")


@pytest.fixture
def built(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(X, "OUT_ROOT", out)
    R.build(run_tests=lambda: TESTS_STUB, log=lambda *_a: None)
    return out


@needs_store
def test_store_appendix_is_public_and_complete(built, tmp_path):
    p = AP.write(tmp_path / "appendix.md")
    text = p.read_text(encoding="utf-8")
    inp = R.load_inputs()
    items = inp["items.json"]["items"]
    assert AP.check(p) == []
    assert AP.leak_problems(text, {it["id"]: it["question"] for it in items}, AP.card_lines(inp["cards.json"]["cards"]),
                            AP.verse_texts()) == []
    assert all(f"| {it['id']} |" in text for it in items) and len(items) == 52
    assert inp["k0.json"]["prompts_sha256"] in text and X.sha256_file(built / "items.json") in text
    assert "appendix.md" not in {ln.split("|")[1].strip().removeprefix("harness ") for ln in text.splitlines()
                                 if ln.startswith("| harness ")}
    assert "SYNC2_01" in text and "答案王" in text and "anchor_first_segment" in text
    assert f"| K0-4 合成測試 x.py（k0.json） | `{'ab' * 32}` |" in text                  # the K0-4 tests as k0.json pins them
    harness = {ln.split("|")[1].strip().removeprefix("harness ") for ln in text.splitlines() if ln.startswith("| harness ")}
    assert {f"tests/{Path(f).name}" for f in R.K0_TESTS} <= harness and "tests/test_arith_stage0_appendix.py" in harness
    p.write_text(text + "\n", encoding="utf-8")
    assert AP.check(p) == ["appendix.md is not what appendix_x renders for the store build"]


@pytest.mark.skipif(not (STORE_OK and AP.APPENDIX.is_file() and X.ITEMS.is_file()),
                    reason="the repository's appendix.md or the store build is not there yet")
def test_repo_appendix_leaks_nothing():
    text = AP.APPENDIX.read_text(encoding="utf-8")
    inp = R.load_inputs()
    assert AP.problems_of(text, inp) == []
