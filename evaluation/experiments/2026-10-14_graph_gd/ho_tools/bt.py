"""Bible text lookup for the §7 HO drafting and audit agents (copy of E7/newq/tools/bt.py).

The agents run it as `bt ...` (run_gen.py puts a wrapper on their PATH); they see only
USAGE and the command output, so everything printed is neutral wording with no file
paths, tracebacks or project terms. Differences from the archived tool (prereg §7 工具):

* paths are not hard-coded to /tmp: layers come from the pinned store reader
  (_ho_text), GT v2 from the repo (pinned sha), OLD31 / NEW82 through gd_common, and the
  HO drafts from the state file named by the HOBT_STATE environment variable;
* `pid` and gold use gd's verse_index (passage_id, then split_passage_ids), the §4 rule;
* `old REGEX` searches only GT v2 and OLD31 and prints their id and question text;
* `old --gold [--except ID] KEY ...` reports, for each key's passages, whether NEW82,
  OLD31 or another live HO draft already uses that passage as gold: passage id and source
  class only, never a question's text;
* an argument is printed back only when it looks like a verse key or sub-command (letters,
  digits, '.', '-'): anything else (a path a shell glob or ~ produced) shows as its position,
  so the tool can never list file names (bt_guard also refuses unquoted globs).

Exit codes: 0 ok, 2 usage or data error (one neutral line on stdout).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, TextIO

from _ho_common import GT_V2_PATH, GT_V2_SHA256, gd  # first: sets sys.path

import _ho_text as T  # noqa: E402
from _ho_state import LIVE  # noqa: E402

STATE_ENV = "HOBT_STATE"
MAX_LINES = 120
SRC_GT, SRC_OLD31 = "既有題庫", "舊多跳題"
SRC_NEW82, SRC_HO = "前一批多跳題", "本批其他草稿"
GOLD_FLAG, EXCEPT_FLAG = "--gold", "--except"
USAGE = """用法：
  bt v KEY [KEY ...]            讀經節原文；KEY 例：gen.1.1、合併節 gen.24.29-30、範圍 gen.1.1-gen.1.5
  bt grep 正規式 [書卷,書卷]     搜尋經文，輸出「經節 段落 經文」，最多 120 行
  bt pid KEY [KEY ...]          每節所屬的段落（段落 id、起訖、段落標題）
  bt books                      書卷 id、中文名、章數
  bt old 正規式                  搜尋既有題目（既有題庫與舊多跳題）：題號與題目
  bt old --gold [--except 題號] KEY [KEY ...]
                                這些經節所在的段落是否已被其他題目使用（只列段落與來源）"""


_SHOWN = re.compile(r"[0-9A-Za-z.-]{1,40}")       # what an argument may look like to be echoed


class BtUsage(Exception):
    """A bad command line (printed as one line with USAGE)."""


def shown(arg: str, n: int) -> str:
    """`arg` when it looks like a key or a word, else 「第 n 個參數」 (never a path)."""
    return arg if _SHOWN.fullmatch(arg) else f"第{n}個參數"


def _missing(key: str, n: int, problem: str) -> str:
    return f"{shown(key, n)} <<{'半節鍵不支援，請用整節' if problem == 'half verse' else '查無此節'}>>"


# ------------------------------------------------------------------ text commands

def _passages_label(unit: str) -> str:
    return "+".join(T.unit_passages(unit))


def cmd_v(keys: Sequence[str]) -> list[str]:
    out = []
    for n, key in enumerate(keys, 1):
        st = T.resolve(key)
        if st.problem:
            out.append(_missing(key, n, st.problem))
        else:
            out.extend(f"{u} {T.verses()[u].text}" for u in st.units)
    return out


def cmd_pid(keys: Sequence[str]) -> list[str]:
    out = []
    for n, key in enumerate(keys, 1):
        st = T.resolve(key)
        if st.problem:
            out.append(_missing(key, n, st.problem))
            continue
        for u in st.units:
            for pid in T.unit_passages(u):
                title, start, end = T.passage_meta()[pid]
                out.append(f"{u} {pid} {start}..{end} {title}")
    return out


def cmd_grep(pattern: str, books: str | None) -> list[str]:
    pat = _regex(pattern)
    wanted = set(books.split(",")) if books else None
    hits = [v for v in T.verses().values()
            if (wanted is None or v.book_id in wanted) and pat.search(v.text)]
    out = [f"{v.key} {_passages_label(v.key)} {v.text}" for v in hits[:MAX_LINES]]
    if len(hits) > MAX_LINES:
        out.append(f"... 共 {len(hits)} 筆，只顯示前 {MAX_LINES} 筆；請縮小正規式或書卷")
    else:
        out.append(f"[{len(hits)} 筆]")
    return out


def cmd_books() -> list[str]:
    return [f"{b.book_id} {b.name} {b.chapters}" for b in T.books()]


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as err:
        raise BtUsage(f"正規式無法解析：{err}") from None


# ------------------------------------------------------------------ old: texts (GT v2, OLD31)

def question_banks() -> list[tuple[str, str, str, str]]:
    """(source, id, question, searchable text) of GT v2 and OLD31, in file order."""
    gt = json.loads(gd.read_pinned(GT_V2_PATH, GT_V2_SHA256))["questions"]
    rows = [(SRC_GT, q["question_id"], q["question"], q["question"] + "\n" + q.get("reference_answer", ""))
            for q in gt]
    old31 = set(gd.load_old31().ids)
    usable = json.loads(gd.read_pinned(gd.OLD31_FILE, gd.FILE_SHA256[gd.OLD31_FILE]))
    rows += [(SRC_OLD31, q["id"], q["question"], q["question"] + "\n" + q["answer"])
             for q in usable if q["id"] in old31]
    return rows


def old_text(pattern: str, banks: Iterable[tuple[str, str, str, str]]) -> list[str]:
    pat = _regex(pattern)
    hits = [f"{src} {qid} {question}" for src, qid, question, text in banks if pat.search(text)]
    return hits[:MAX_LINES] + [f"[{len(hits)} 筆]"]


# ------------------------------------------------------------------ old --gold: conflicts only

def _item_gold(item: Mapping) -> set[str]:
    """Gold passages of a draft item's hop_slots, skipping keys that do not resolve."""
    out: set[str] = set()
    for hop in item.get("hop_slots") or ():
        for key in hop if isinstance(hop, list) else ():
            try:
                out |= gd.hop_gold([key])
            except gd.GdError:
                continue
    return out


def draft_items(state_path: str | None, exclude: str | None) -> list[dict]:
    """Live HO drafts of the state file (none when unset or absent), minus `exclude`."""
    if not state_path or not Path(state_path).is_file():
        return []
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    return [r["item"] for r in state.get("records", [])
            if r.get("status") in LIVE and r.get("item") and r.get("id") != exclude]


def owner_map(state_path: str | None, exclude: str | None) -> dict[str, set[str]]:
    """passage id -> source classes using it as §4 gold: NEW82, OLD31, live HO drafts."""
    owners: dict[str, set[str]] = {}
    for label, qset in ((SRC_NEW82, gd.load_new82()), (SRC_OLD31, gd.load_old31())):
        for q in qset.questions:
            for gold in gd.question_gold(q):
                for pid in gold:
                    owners.setdefault(pid, set()).add(label)
    for item in draft_items(state_path, exclude):
        for pid in _item_gold(item):
            owners.setdefault(pid, set()).add(SRC_HO)
    return owners


def gold_conflicts(keys: Sequence[str], owners: Mapping[str, Iterable[str]]) -> list[str]:
    """Per key: its passages and which source classes already use them (no question text)."""
    out, seen, hit = [], set(), set()
    order = (SRC_NEW82, SRC_OLD31, SRC_HO)
    for n, key in enumerate(keys, 1):
        st = T.resolve(key)
        if st.problem:
            out.append(_missing(key, n, st.problem))
            continue
        for unit in st.units:
            for pid in T.unit_passages(unit):
                seen.add(pid)
                srcs = [s for s in order if s in set(owners.get(pid, ()))]
                if srcs:
                    hit.add(pid)
                out.append(f"{unit} → {pid} " + ("衝突：" + "、".join(srcs) if srcs else "無衝突"))
    out.append(f"[{len(seen)} 個段落中 {len(hit)} 個已被使用]")
    return out


def cmd_old(args: Sequence[str], env: Mapping[str, str]) -> list[str]:
    if not args:
        raise BtUsage("old 需要正規式，或 --gold 加經節")
    if args[0] != GOLD_FLAG:
        if len(args) != 1:
            raise BtUsage("old 只接受一個正規式（含空白請加引號）")
        return old_text(args[0], question_banks())
    rest, exclude = list(args[1:]), None
    if rest[:1] == [EXCEPT_FLAG]:
        if len(rest) < 2:
            raise BtUsage("--except 後要接題號")
        exclude, rest = rest[1], rest[2:]
    if not rest:
        raise BtUsage("--gold 後要接至少一個經節")
    return gold_conflicts(rest, owner_map(env.get(STATE_ENV), exclude))


# ------------------------------------------------------------------ CLI

def run(argv: Sequence[str], env: Mapping[str, str]) -> list[str]:
    if not argv:
        raise BtUsage("缺少子命令")
    cmd, args = argv[0], list(argv[1:])
    simple: dict[str, Callable[[], list[str]]] = {
        "v": lambda: cmd_v(args), "pid": lambda: cmd_pid(args), "books": cmd_books,
        "grep": lambda: cmd_grep(args[0], args[1] if len(args) > 1 else None),
        "old": lambda: cmd_old(args, env)}
    if cmd not in simple:
        raise BtUsage(f"不認得的子命令 {shown(cmd, 1)}")
    if cmd in ("v", "pid") and not args or cmd == "grep" and not 1 <= len(args) <= 2:
        raise BtUsage(f"{cmd} 的參數不對")
    return simple[cmd]()


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout,
         env: Mapping[str, str] | None = None) -> int:
    try:
        lines = run(sys.argv[1:] if argv is None else argv, os.environ if env is None else env)
    except BtUsage as err:
        print(f"錯誤：{err}\n{USAGE}", file=out)
        return 2
    except gd.IntegrityError:
        print("錯誤：資料檔核對失敗，請停止並回報", file=out)
        return 2
    except Exception as err:  # noqa: BLE001 - the agent must never see a traceback or a path
        print(f"錯誤：工具內部錯誤（{type(err).__name__}），請停止並回報", file=out)
        return 2
    print("\n".join(lines), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
