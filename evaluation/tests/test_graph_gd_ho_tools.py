"""GD experiment §7 HO tools: bt.py, banned terms, the bt guard hook, prompts, Kay sampling, page.

Unit tests use synthetic data (monkeypatched question sets and passages); the store tests
(skipped when the store is not mounted) only read questions, gold and the text layer.
Nothing here runs retrieval, scoring or encoding on any set, and nothing launches an agent.
"""

import importlib
import io
import json
import random
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
for _p in (str(_DIR / "ho_tools"), str(_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = importlib.import_module("_ho_common")
gd = H.gd
banned = importlib.import_module("banned")
bt = importlib.import_module("bt")
guard = importlib.import_module("bt_guard")
P = importlib.import_module("_ho_prompts")
kay = importlib.import_module("sample_kay")
page = importlib.import_module("build_page")
annotate = importlib.import_module("annotate")

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# ---------------------------------------------------------------- banned terms

def test_banned_terms_match_words_not_substrings_of_other_words():
    hits = banned.find_terms("a paragraph about storage and kg-free text", banned.BANNED_TERMS)
    assert [h.term for h in hits] == ["KG"]
    assert {h.term for h in banned.find_terms("Graph RAG 用向量檢索", banned.BANNED_TERMS)} == {
        "graph", "RAG", "向量", "檢索"}
    assert banned.find_terms("Kay 的 prereg 在 Bible_RAG", banned.MEMORY_MARKERS)
    assert not banned.find_terms("可拉是以斯哈的兒子", banned.PROMPT_TERMS)


def test_prompt_check_covers_purpose_words_and_cli_exit_codes(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("這是對照實驗的出題 prompt。")
    good = tmp_path / "good.md"
    good.write_text("出一題聖經問答題。")
    assert {h.term for h in banned.check_prompt_file(bad)} == {"對照", "實驗"}
    assert banned.main([str(good)]) == 0
    assert banned.main([str(bad)]) == 1
    assert banned.main([]) == 2
    assert banned.main([str(tmp_path / "missing.md")]) == 2


def test_the_frozen_prompts_are_free_of_banned_words():
    for path in (H.GEN_PROMPT, H.AUDIT_PROMPT):
        assert banned.check_prompt_file(path) == [], path
    assert banned.check_prompt_text(bt.USAGE) == []


@needs_store
def test_no_banned_or_memory_word_occurs_in_what_bt_can_print():
    """A transcript hit can then only come from the agent or the prompt (§7)."""
    texts = [v.text for v in importlib.import_module("_ho_text").verses().values()]
    texts += [p.title for p in gd.load_passages()]
    texts += [t for _, _, _, t in bt.question_banks()]
    blob = "\n".join(texts)
    assert banned.find_terms(blob, banned.BANNED_TERMS + banned.MEMORY_MARKERS) == []

# ---------------------------------------------------------------- bt guard hook

@pytest.mark.parametrize("cmd", ["bt v gen.1.1", "bt grep '可拉|以斯哈' num,exo", "bt books",
                                 "bt old --gold --except H_KIN_001 gen.1.1 gen.1.2",
                                 "bt old '亞倫.*妻'", "bt grep '以斯哈$'"])
def test_guard_lets_one_plain_bt_call_through(cmd):
    assert guard.check_command(cmd) is None


@pytest.mark.parametrize("cmd", ["ls", "pwd", "env", "cat /etc/hostname", "bt v x; ls",
                                 "bt v x && cat y", "bt v x | head", "bt v $(whoami)",
                                 "bt v `id`", 'bt v "$HOME"', "bt v x > f", "bt v x\nls",
                                 "btx v", "bt 'unterminated", 'bt grep "以斯哈$"', "", "  "])
def test_guard_refuses_everything_else(cmd):
    assert guard.check_command(cmd) is not None


@pytest.mark.parametrize("cmd", ["bt v ../home/*/.claude/projects/*/memory/* gen.1.1", "bt v ~/.claude/projects/*",
                                 "bt v /mnt/*/bible_rag_store/reports/*", "bt v gen.1.?", "bt v gen.1.[12]",
                                 "bt v {gen,exo}.1.1", "bt v ~", "bt grep 以斯哈.* num"])
def test_guard_refuses_unquoted_globs_and_tilde_so_bt_cannot_list_files(cmd):
    assert "single quotes" in guard.check_command(cmd)


@pytest.mark.parametrize("cmd", ["bt grep '以斯哈.*' num", "bt old '亞倫[的]妻'", 'bt grep "可拉.?"',
                                 "bt grep '~'", "bt v gen.1.1 \\*"])
def test_quoted_or_escaped_glob_characters_reach_bt_as_text(cmd):
    assert guard.check_command(cmd) is None


def test_bt_never_prints_back_an_argument_that_is_not_key_like(monkeypatch):
    T = bt.T
    monkeypatch.setattr(T, "resolve", lambda key: T.KeyStatus(key, (), "not found"))
    out = bt.cmd_v(["../home/kenzx0521/.claude/projects/x/memory/project_graph.md", "gen.99.1", "~kay"])
    assert out == ["第1個參數 <<查無此節>>", "gen.99.1 <<查無此節>>", "第3個參數 <<查無此節>>"]
    assert bt.cmd_pid(["/etc/passwd"]) == ["第1個參數 <<查無此節>>"]
    assert bt.gold_conflicts(["a/b"], {}) == ["第1個參數 <<查無此節>>", "[0 個段落中 0 個已被使用]"]
    buf = io.StringIO()
    assert bt.main(["/home/x"], out=buf, env={}) == 2 and "/home" not in buf.getvalue()


def test_guard_hook_io(monkeypatch, capsys):
    def run(event):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        return guard.main()
    assert run({"tool_name": "Bash", "tool_input": {"command": "bt v gen.1.1"}}) == 0
    assert run({"tool_name": "StructuredOutput", "tool_input": {}}) == 0
    assert run({"tool_name": "Bash", "tool_input": {"command": "ls"}}) == guard.DENY_EXIT
    assert run({"tool_name": "Read", "tool_input": {"file_path": "/etc/x"}}) == guard.DENY_EXIT
    err = capsys.readouterr().err
    assert "denied" in err and "/home" not in err and "Bible" not in err

# ---------------------------------------------------------------- bt old: conflicts only

def _fake_sets(monkeypatch, marker):
    """NEW82 / OLD31 stand-ins whose question text carries `marker`; one passage per verse."""
    def qset(name, qid, key):
        q = gd.Question(qid, f"{marker} {name} 題目全文", gd.KIN, ((key,), ("gen.50.1",)), None)
        return gd.QuestionSet(name, (q,), {})
    monkeypatch.setattr(gd, "load_new82", lambda: qset("new82", "N_KIN_77", "gen.2.1"))
    monkeypatch.setattr(gd, "load_old31", lambda: qset("old31", "KIN_77", "gen.3.1"))
    monkeypatch.setattr(gd, "question_gold",
                        lambda q, *a: tuple(frozenset(f"ps:{k}" for k in h) for h in q.hops))
    monkeypatch.setattr(gd, "hop_gold", lambda keys, *a: frozenset(f"ps:{k}" for k in keys))
    T = bt.T
    monkeypatch.setattr(T, "resolve", lambda key: T.KeyStatus(key, (key,)) if key.startswith("gen.")
                        else T.KeyStatus(key, (), "not found"))
    monkeypatch.setattr(T, "unit_passages", lambda unit: (f"ps:{unit}",))


def _draft_state(tmp_path, marker):
    item = {"id": "H_DIS_009", "question": f"{marker} 草稿題目", "hop_slots": [["gen.4.1"], ["gen.5.1"]]}
    state = {"records": [{"id": "H_DIS_009", "status": "pending_audit", "item": item},
                         {"id": "H_DIS_010", "status": "dropped",
                          "item": {**item, "id": "H_DIS_010", "hop_slots": [["gen.6.1"], ["gen.7.1"]]}}]}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state, ensure_ascii=False))
    return path


def test_old_gold_reports_passage_and_source_but_never_question_text(monkeypatch, tmp_path):
    marker = "獨特標記ZQX"
    _fake_sets(monkeypatch, marker)
    state = _draft_state(tmp_path, marker)
    buf = io.StringIO()
    keys = ["gen.2.1", "gen.3.1", "gen.4.1", "gen.6.1", "gen.8.1", "xx.1.1"]
    assert bt.main(["old", "--gold", *keys], out=buf, env={bt.STATE_ENV: str(state)}) == 0
    out = buf.getvalue()
    assert "gen.2.1 → ps:gen.2.1 衝突：前一批多跳題" in out
    assert "gen.3.1 → ps:gen.3.1 衝突：舊多跳題" in out
    assert "gen.4.1 → ps:gen.4.1 衝突：本批其他草稿" in out
    assert "gen.6.1 → ps:gen.6.1 無衝突" in out          # a dropped draft holds nothing
    assert "gen.8.1 → ps:gen.8.1 無衝突" in out and "xx.1.1 <<查無此節>>" in out
    for leak in (marker, "題目全文", "草稿題目", "N_KIN_77", "KIN_77", "H_DIS_009"):
        assert leak not in out


def test_old_gold_except_drops_the_own_draft(monkeypatch, tmp_path):
    _fake_sets(monkeypatch, "M")
    state = _draft_state(tmp_path, "M")
    buf = io.StringIO()
    bt.main(["old", "--gold", "--except", "H_DIS_009", "gen.4.1"], out=buf, env={bt.STATE_ENV: str(state)})
    assert "gen.4.1 → ps:gen.4.1 無衝突" in buf.getvalue()


def test_old_text_searches_only_the_text_banks():
    banks = [(bt.SRC_GT, "G1", "葉忒羅是誰？", "葉忒羅是誰？\n摩西的岳父"),
             (bt.SRC_OLD31, "O1", "亞倫的妻子？", "亞倫的妻子？\n以利沙巴")]
    assert bt.old_text("岳父", banks) == ["既有題庫 G1 葉忒羅是誰？", "[1 筆]"]
    assert bt.old_text("沒有", banks) == ["[0 筆]"]


@pytest.mark.parametrize("argv", [[], ["nope"], ["v"], ["grep"], ["old"], ["old", "a", "b"],
                                  ["old", "--gold"], ["old", "--gold", "--except"], ["grep", "("]])
def test_bt_usage_errors_are_one_neutral_message(argv):
    buf = io.StringIO()
    assert bt.main(argv, out=buf, env={}) == 2
    assert buf.getvalue().startswith("錯誤：") and "/" not in buf.getvalue().split("\n")[0]


@needs_store
def test_store_old_gold_on_new82_gold_leaks_no_new82_text(tmp_path):
    q = gd.load_new82().questions[0]
    key = q.hops[0][0]
    buf = io.StringIO()
    assert bt.main(["old", "--gold", key], out=buf, env={bt.STATE_ENV: str(tmp_path / "none.json")}) == 0
    out = buf.getvalue()
    assert "衝突：前一批多跳題" in out
    assert q.question[:12] not in out and q.qid not in out


@needs_store
def test_store_old_text_never_returns_new82_questions():
    q = gd.load_new82().questions[5]
    buf = io.StringIO()
    bt.main(["old", q.question[:10]], out=buf, env={})
    lines = buf.getvalue().splitlines()
    assert all(l.startswith((bt.SRC_GT, bt.SRC_OLD31, "[")) for l in lines)
    assert all(not l.split(" ")[1].startswith("N_") for l in lines[:-1])


@needs_store
def test_store_bt_text_commands():
    assert bt.cmd_v(["gen.24.30"])[0].startswith("gen.24.29-30 ")
    assert bt.cmd_v(["gen.1.1a"]) == ["gen.1.1a <<半節鍵不支援，請用整節>>"]
    assert bt.cmd_pid(["num.16.1"]) == ["num.16.1 ps:num.16.1 num.16.1..num.16.35 可拉、大坍、亞比蘭的叛變"]
    hits = [v for v in bt.T.verses().values() if v.book_id == "num" and "以斯哈" in v.text]
    assert bt.cmd_grep("以斯哈", "num")[-1] == f"[{len(hits)} 筆]" and hits
    assert len(bt.cmd_books()) == gd.N_BOOKS

# ---------------------------------------------------------------- prompts

def test_prompt_sections_and_rendering_need_exact_placeholders():
    gen, audit = P.default_prompts()
    assert set(gen.sections) == {"system", "task_new", "task_fix"}
    assert set(audit.sections) == {"system", "task_audit"}
    values = {"qid": "H_MH_001", "category_line": P.category_line("MH", "BRL"), "category_code": "BRL",
              "used_cores": "約西亞（2 題，已滿）"}
    text = P.render(gen, "task_new", values)
    assert "H_MH_001" in text and "BRL（地點、物件、事件橋接）" in text and "{{" not in text
    assert "已用過的核心" in text and "約西亞（2 題，已滿）" in text
    audit_text = P.render(audit, "task_audit", {"qid": "H_MH_001", "category_line": "多跳",
                                                "used_cores": "約西亞（1 題）", "item_json": "{}"})
    assert "約西亞（1 題）" in audit_text
    with pytest.raises(H.HoToolError):
        P.render(gen, "task_new", {k: v for k, v in values.items() if k != "qid"})
    with pytest.raises(H.HoToolError):
        P.render(gen, "task_new", {**values, "extra": "x"})


def test_prompt_loader_refuses_banned_words_and_stray_text(tmp_path):
    bad = tmp_path / "p.md"
    bad.write_text("<!-- section:system -->\n用向量出題\n")
    with pytest.raises(H.HoToolError):
        P.load_prompt(bad)
    bad.write_text("前言\n<!-- section:system -->\n出題\n")
    with pytest.raises(H.HoToolError):
        P.load_prompt(bad)


def test_prompts_carry_the_section_7_rules():
    text = H.GEN_PROMPT.read_text(encoding="utf-8")
    for rule in ("2 到 5 跳", "不出前提錯誤的題", "同一個核心最多 2 題", "平行經文必須全列",
                 "[SHORTCUT]", "shortcut_search", "bt old --gold", "不可用範圍鍵", "core", "別名、異寫"):
        assert rule in text, rule
    for code in ("KIN", "DIS", "TO", "SUC", "BRP", "BRL", "OQ"):
        assert f"{code}" in text
    audit = H.AUDIT_PROMPT.read_text(encoding="utf-8")
    for word in ("critical", "major", "minor", "ok", "checked", "suggested_fix", "別名、異寫"):
        assert word in audit

# ---------------------------------------------------------------- Kay sample

def test_kay_sample_is_the_section_7_draw_and_deterministic():
    ids = [f"H_{c}_{i:03d}" for c in ("KIN", "DIS", "TO", "MH") for i in range(1, 31)]
    shuffled = random.Random(5).sample(ids, len(ids))
    got = kay.sample_ids(shuffled)
    assert got == random.Random(20261014).sample(sorted(ids), 15)
    assert got == kay.sample_ids(list(reversed(ids))) and len(set(got)) == 15
    assert kay.sample_ids(ids) != kay.sample_ids(ids, seed=1)

# ---------------------------------------------------------------- review page

def test_page_embeds_annotated_questions_and_refuses_raw_ones(tmp_path):
    q = {"id": "H_KIN_001", "category": "KIN", "question": "問</script>題", "answer": "a",
         "key_points": ["k"], **{k: [] for k in annotate.ANNOTATED_KEYS}, "n_hops": 2, "cross_book": False}
    html = page.page_html([q])
    assert "/*__DATA__*/null" not in html and "問<\\/script>題" in html
    with pytest.raises(H.HoToolError):
        page.page_html([{"id": "H_KIN_002"}])
    out = page.write_page([q], tmp_path / "p.html")
    assert out.read_text(encoding="utf-8") == html
