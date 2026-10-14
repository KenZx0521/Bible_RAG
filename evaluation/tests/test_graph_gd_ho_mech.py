"""GD experiment §7 機械稽核 (ho_tools/mech_check.py, _ho_transcript.py): one test per rule.

Question rules run on a synthetic layer (VerseUnits / VerseIndex built here, NEW82 / OLD31
owners injected); transcript rules on synthetic stream-json events: absolute and relative
paths, banned words (errors only in the system prompt, warnings in agent text), memory
words, the blinding errors a commit drops a question for, and the 衝突 passages that
`bt old --gold` reported. One store test runs the CLI on a question file built from verses
outside the NEW82 ∪ OLD31 gold.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-14_graph_gd"
for _p in (str(_DIR / "ho_tools"), str(_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

H = importlib.import_module("_ho_common")
gd = H.gd
M = importlib.import_module("mech_check")
TR = importlib.import_module("_ho_transcript")
C = importlib.import_module("_ho_claude")

needs_store = pytest.mark.skipif(
    not (gd.LAYERS_ROOT / "text" / gd.LAYER_VERSIONS["text"] / "layer_manifest.json").is_file(),
    reason=f"store not mounted ({gd.STORE})")

# synthetic layer: gen.1..9 with verses 1-3, one passage per chapter; gen.10.1-2 merged;
# gen.9.3 is a unit with no verse_index row (its gold cannot be computed)
_KEYS = [f"gen.{c}.{v}" for c in range(1, 10) for v in range(1, 4)] + ["gen.10.1-2"]
UNITS = gd.VerseUnits(tuple(_KEYS), {k: ((1, 2) if k.endswith("1-2") else (int(k.rsplit(".", 1)[1]),) * 2)
                                     for k in _KEYS})
VI = gd.VerseIndex({k: f"ps:{k.rsplit('.', 1)[0]}.1" for k in _KEYS if k != "gen.9.3"},
                   {k: () for k in _KEYS if k != "gen.9.3"})
CTX = M.Context({"ps:gen.8.1": "new82:N_KIN_01", "ps:gen.7.1": "old31:KIN_03"}, UNITS, VI)


def item(qid="H_KIN_001", hops=(("gen.1.1",), ("gen.2.1",)), core="可拉", category="KIN", **kw):
    base = {f: "" for f in gd.HO_FIELDS}
    base.update(id=qid, category=category, question="問題？", core=core, key_points=["a", "b"],
                hop_slots=[list(h) for h in hops], hop_roles=["r"] * len(hops), change_log="",
                hops=[], n_hops=len(hops), needs_identity_resolution=False)
    base.update(kw)
    return base


def rules(it, earlier=(), level="error"):
    return sorted({v.rule for v in M.check_item(it, CTX, earlier) if v.level == level})

# ---------------------------------------------------------------- question rules

def test_a_clean_question_has_no_violation_and_merged_keys_are_fine():
    assert M.check_item(item(), CTX) == []
    assert M.check_item(item(hops=(("gen.10.1-2", "gen.3.1"), ("gen.2.1",))), CTX) == []
    assert rules(item(hops=(("gen.10.2",), ("gen.2.1",)))) == []       # resolves to the merged unit


@pytest.mark.parametrize("name,value", [("core", None), ("hops", None), ("question", "  "),
                                        ("core", ""), ("change_log", ["[SHORTCUT]"]), ("key_points", "a")])
def test_rule_fields(name, value):
    it = {k: v for k, v in item().items() if k != name} if value is None else item(**{name: value})
    assert rules(it) == ["fields"]


@pytest.mark.parametrize("qid,cat", [("H_XX_001", "KIN"), ("H_KIN_001", "NULL"), ("H_MH_001", "KIN"),
                                     ("H_TO_001", "DIS")])
def test_rule_id_prefix(qid, cat):
    assert rules(item(qid=qid, category=cat)) == ["id_prefix"]


def test_multi_hop_sub_types_pass_the_prefix_rule():
    for sub in ("SUC", "BRP", "BRL", "OQ"):
        assert rules(item(qid="H_MH_001", category=sub)) == []


def test_rule_duplicate_id():
    assert "duplicate_id" in rules(item(hops=(("gen.3.1",), ("gen.4.1",))), [item()])


@pytest.mark.parametrize("hops", [(("gen.1.1",),), tuple((f"gen.{c}.1",) for c in range(1, 7))])
def test_rule_hops_count(hops):
    assert rules(item(hops=hops)) == ["hops_count"]


def test_rule_half_key():
    assert "half_key" in rules(item(hops=(("gen.1.1a", "gen.1.2"), ("gen.2.1",))))


@pytest.mark.parametrize("key", ["gen.1.1-gen.1.3", "Gen 1:1", "gen.1"])
def test_rule_key_form(key):
    assert "key_form" in rules(item(hops=((key, "gen.1.2"), ("gen.2.1",))))


def test_rule_verse_missing_and_hop_no_pid():
    assert rules(item(hops=(("gen.11.1", "gen.1.1"), ("gen.2.1",)))) == ["verse_missing"]
    assert rules(item(hops=(("gen.11.1",), ("gen.2.1",)))) == ["hop_no_pid", "verse_missing"]


def test_rule_gold():
    assert rules(item(hops=(("gen.9.3",), ("gen.2.1",)))) == ["gold"]


def test_rule_hop_overlap():
    assert rules(item(hops=(("gen.1.1",), ("gen.1.2",)))) == ["hop_overlap"]


def test_rules_overlap_new82_and_old31():
    assert rules(item(hops=(("gen.8.2",), ("gen.2.1",)))) == ["overlap_new82"]
    assert rules(item(hops=(("gen.1.1",), ("gen.7.3",)))) == ["overlap_old31"]


def test_rule_overlap_ho_flags_the_later_question_only():
    first = item("H_KIN_001", (("gen.3.1",), ("gen.4.1",)), core="甲")
    later = item("H_DIS_001", (("gen.3.2",), ("gen.5.1",)), core="乙", category="DIS")
    found = M.check_set([first, later], CTX)
    assert found["H_KIN_001"] == []
    assert {v.rule for v in found["H_DIS_001"]} == {"overlap_ho"}


def test_rule_core_limit_counts_stripped_cores():
    a = item("H_KIN_001", (("gen.1.1",), ("gen.2.1",)), core="可拉")
    b = item("H_KIN_002", (("gen.3.1",), ("gen.4.1",)), core=" 可拉 ")
    c = item("H_KIN_003", (("gen.5.1",), ("gen.6.1",)), core="可拉")
    found = M.check_set([a, b, c], CTX)
    assert [sorted({v.rule for v in found[q]}) for q in ("H_KIN_001", "H_KIN_002", "H_KIN_003")] == [
        [], [], ["core_limit"]]


def test_rule_core_similar_warns_on_a_core_inside_another():
    a = item("H_KIN_001", (("gen.1.1",), ("gen.2.1",)), core="約西亞")
    b = item("H_KIN_002", (("gen.3.1",), ("gen.4.1",)), core="約西亞王")
    c = item("H_KIN_003", (("gen.5.1",), ("gen.6.1",)), core="約西亞")
    found = M.check_set([a, b, c], CTX)
    assert found["H_KIN_001"] == [] and [v.rule for v in found["H_KIN_002"]] == ["core_similar"]
    assert {(v.rule, v.level) for v in found["H_KIN_003"]} == {("core_similar", "warn")}   # 2 exact: no limit
    other = item("H_KIN_004", (("gen.5.2",), ("gen.6.2",)), core="亞")                     # 1 char: ignored
    assert M.check_item(other, CTX, [a]) == []


def test_rule_hop_roles_is_only_a_warning():
    it = item(hop_roles=["only one"])
    assert rules(it) == [] and rules(it, level="warn") == ["hop_roles"]


def test_every_documented_question_rule_is_exercised():
    assert set(M.QUESTION_RULES) == {
        "fields", "id_prefix", "duplicate_id", "hops_count", "half_key", "key_form", "verse_missing",
        "hop_no_pid", "gold", "hop_overlap", "overlap_new82", "overlap_old31", "overlap_ho",
        "core_limit", "core_similar", "hop_roles"}

# ---------------------------------------------------------------- transcript rules

def events(cmds=("bt v gen.1.1",), text="好", ok=True, cwd="/srv", tools=("Bash", "StructuredOutput"),
           denied=(), result_text="起初", model=C.MODEL, mcp=()):
    ev = [{"type": "system", "subtype": "init", "cwd": cwd, "tools": list(tools), "mcp_servers": list(mcp),
           "model": model, "permissionMode": "dontAsk"}]
    for i, cmd in enumerate(cmds):
        name, inp = ("Read", {"file_path": cmd[5:]}) if cmd.startswith("READ ") else ("Bash", {"command": cmd})
        ev.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}})
        res = "PreToolUse:Bash hook error: [bt-guard]: denied: only `bt` may run" if cmd in denied else result_text
        ev.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": res, "is_error": cmd in denied}]}})
    ev.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text},
                                                            {"type": "thinking", "thinking": ""}]}})
    if ok:
        ev.append({"type": "result", "subtype": "success", "is_error": False, "result": "",
                   "structured_output": {"status": "drafted"}})
    return ev


def trules(ev, prompts=None, level="error"):
    return sorted({v.rule for v in TR.check_events(ev, prompts, cwd=Path("/srv")) if v.level == level})


def test_a_clean_transcript_passes():
    assert TR.check_events(events(), {"system": "出題", "user": "任務"}, cwd=Path("/srv")) == []


@pytest.mark.parametrize("kw", [{"cwd": str(H.REPO_ROOT)}, {"cwd": "/mnt/x"}, {"model": "claude-sonnet"},
                                {"tools": ("Bash", "Read")}, {"mcp": ({"name": "x"},)}])
def test_rule_t_init(kw):
    assert trules(events(**kw)) == ["t_init"]


def test_rule_t_init_needs_an_init_event():
    assert "t_init" in trules(events()[1:])


@pytest.mark.parametrize("cmd", ["ls", "bt v x; cat y", "READ /etc/passwd"])
def test_rule_t_tool_on_any_executed_non_bt_call(cmd):
    assert "t_tool" in trules(events(cmds=("bt v gen.1.1", cmd)))


def test_a_refused_attempt_is_only_a_warning():
    ev = events(cmds=("ls",), denied=("ls",))
    assert trules(ev) == [] and trules(ev, level="warn") == ["t_tool_denied"]


def test_rule_t_path_allows_only_the_store_layers():
    assert trules(events(result_text="see /home/someone/notes.md")) == ["t_path"]
    assert trules(events(result_text="~/.claude/x")) == ["t_path"]
    seen_layers = trules(events(result_text=f"{gd.LAYERS_ROOT}/text/x.jsonl"))
    assert "t_path" not in seen_layers           # allowed path; its 'bible_rag' is still a leak
    assert seen_layers == ["t_memory"]
    assert trules(events(cmds=("bt v /etc/passwd",))) == ["t_path"]


@pytest.mark.parametrize("kw", [{"cmds": ("bt v ../etc/*",)}, {"result_text": "../etc/passwd <<查無此節>>"},
                                {"result_text": "proj/memory/x.md <<查無此節>>"}, {"cmds": ("bt v ./x",)},
                                {"text": "讀了 ~/.claude/x"}])
def test_rule_t_path_also_catches_relative_paths_in_commands_and_results(kw):
    assert "t_path" in trules(events(**kw))          # a globbing command is also t_tool


def test_slashes_and_tildes_in_the_agents_own_words_are_not_paths():
    ev = events(text="祖孫/叔侄，約 ~30 年，1/2 的人")
    ev[1]["message"]["content"][0]["input"]["description"] = "Read verses a/b of the 2/3 range"
    assert trules(ev) == []


def test_banned_words_are_errors_in_the_system_prompt_and_warnings_in_agent_text():
    assert trules(events(), {"system": "檢索題", "user": ""}) == ["t_banned"]
    for ev, prompts in ((events(text="用向量找"), None), (events(result_text="dense 結果"), None),
                        (events(), {"system": "出題", "user": "題目：用 grep 檢索平行經文"})):
        assert trules(ev, prompts) == [] and trules(ev, prompts, "warn") == ["t_banned_agent"]
    assert "t_banned_agent" not in TR.BLINDING_RULES and "t_memory" in TR.BLINDING_RULES


def test_rule_t_memory():
    assert trules(events(text="Kay 說過")) == ["t_memory"]
    assert trules(events(result_text="依 prereg")) == ["t_memory"]


def test_rule_t_result():
    assert trules(events(ok=False)) == ["t_result"]


def test_conflict_passages_come_only_from_old_gold_results():
    gold = "gen.2.1 → ps:gen.2.1 衝突：舊多跳題\ngen.4.1 → ps:gen.4.1 無衝突\ngen.5.1 → ps:gen.5.1 衝突：本批其他草稿"
    ev = events(cmds=("bt old --gold gen.2.1 gen.4.1 gen.5.1", "bt v gen.1.1"), result_text=gold)
    assert TR.conflict_passages(ev) == {"ps:gen.2.1", "ps:gen.5.1"}        # the bt v result is ignored
    assert TR.conflict_passages(events(cmds=("bt v gen.1.1",), result_text=gold)) == set()


def test_blinding_errors_skip_t_result_and_warnings(tmp_path):
    for d in ("transcripts", "prompts"):
        (tmp_path / d).mkdir()
    for run, ev in (("clean", events(ok=False, text="檢索")), ("leak", events(text="Kay 說"))):
        (tmp_path / "transcripts" / f"{run}.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in ev))
        (tmp_path / "prompts" / f"{run}.json").write_text(json.dumps({"system": "s", "user": "u"}))
    assert TR.blinding_errors(tmp_path, ["clean"]) == []
    got = TR.blinding_errors(tmp_path, ["clean", "leak"])
    assert [v.rule for v in got] == ["t_memory"] and got[0].detail.startswith("leak: ")


def test_check_run_reads_the_files_and_needs_the_prompts(tmp_path):
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "transcripts" / "gen_H_KIN_001_1.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events()) + "\n{torn")
    assert {v.rule for v in TR.check_run(tmp_path, "gen_H_KIN_001_1", Path("/srv"))} == {"t_init"}
    (tmp_path / "prompts" / "gen_H_KIN_001_1.json").write_text(json.dumps({"system": "s", "user": "u"}))
    assert TR.check_run(tmp_path, "gen_H_KIN_001_1", Path("/srv")) == []
    assert [v.rule for v in TR.check_run(tmp_path, "gen_H_KIN_001_9", Path("/srv"))] == ["t_result"]

# ---------------------------------------------------------------- CLI (store)

def free_verses(n):
    """n whole-verse keys, each in its own passage outside the NEW82 ∪ OLD31 gold."""
    used = set(M.store_context().owners)
    vi, out = gd.load_verse_index(), {}
    for key in gd.load_verse_units().order:
        pid = vi.passage_of[key]
        if "-" not in key and not vi.split_of[key] and pid not in used and pid not in out:
            out[pid] = key
            if len(out) == n:
                return list(out.values())
    raise AssertionError("not enough free passages")


@needs_store
def test_store_cli_file_mode(tmp_path):
    v = free_verses(4)
    new82_key = gd.load_new82().questions[0].hops[0][0]
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"questions": [item("H_KIN_001", ((v[0],), (v[1],))),
                                              item("H_TO_001", ((v[2],), (v[3],)), category="TO")]}))
    assert M.main(["file", "--in", str(good), "--out", str(tmp_path / "g.json")]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"questions": [item("H_KIN_001", ((new82_key,), (v[1],)))]}))
    assert M.main(["file", "--in", str(bad), "--out", str(tmp_path / "b.json")]) == 1
    report = json.loads((tmp_path / "b.json").read_text())
    assert report["with_errors"] == ["H_KIN_001"]
    assert {v["rule"] for v in report["violations"]["H_KIN_001"]} == {"overlap_new82"}
    assert "ho_tools/mech_check.py" in report["meta"]["sha256"]


def test_innocent_agent_wording_is_not_a_transcript_hit_but_is_refused_in_prompts():
    ev = events()
    ev[1]["message"]["content"][0]["input"]["description"] = "Retrieve the verse text with bt"
    assert trules(ev) == []
    assert {h.term for h in importlib.import_module("banned").check_prompt_text("retrieve 經文")} == {"retrieve"}
