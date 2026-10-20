"""Bible text lookup of the HO writers and auditors (prereg §3.1, §3.5): `bt v`, `bt grep`, `bt books`.

Copy of experiment A's ho_a/bt_a.py (itself HO's ho_tools/bt.py without `pid` and `old`), the original untouched,
with one change: bt_a reads the text layer through ``c_common`` (A's constants; prereg §3.9 forbids that import),
this copy reads the two files of the text layer directly from the store (TEXT = text@247eafe44b02), sha256-pinned
exactly as bt_a pins them (= the layer manifest); a mismatch refuses. The agents run it as `bt ...` through the
<root>/bin/bt wrapper (claude_g, stderr dropped), so everything printed is neutral wording with no file path,
traceback or project term. An argument is printed back only when it looks like a verse key or sub-command
(letters, digits, '.', '-'); anything else (a path a glob or ~ produced) shows as its position. Exit 0 ok, 2 usage
or data error (one neutral line). Stdlib only; reads nothing else and writes nothing.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable, Sequence, TextIO

TEXT = Path("/mnt/ollama-data/bible_rag_store/layers/text/text@247eafe44b02")
TEXT_SHA256 = {"verse_units.jsonl": "c2e9630d6cf1e6a0c3792ef9eaf97421325e3a5e080c7b65b628a1c2416a5293",
               "books.jsonl": "e01d5cc0956cbf5684897179d251d14417aa9a4c2ed1f908a556e6ed77731137"}
MAX_LINES = 120
COMMANDS = ("v", "grep", "books")
USAGE = """用法：
  bt v KEY [KEY ...]            讀經節原文；KEY 例：1ki.15.8、合併節 gen.24.29-30、範圍 1ki.15.1-1ki.15.8
  bt grep 正規式 [書卷,書卷]     搜尋經文，輸出「經節 經文」，最多 120 行
  bt books                      書卷 id、中文名、章數"""
_SHOWN = re.compile(r"[0-9A-Za-z.-]{1,40}")
_KEY = re.compile(r"^([0-9a-z]+)\.(\d+)\.(\d+)$")
_HALF = re.compile(r"^[0-9a-z]+\.\d+\.\d+[ab]$")


class BtUsage(Exception):
    """A bad command line (printed as one line with USAGE)."""


class BtData(Exception):
    """The text layer failed its sha256 check."""


def shown(arg: str, n: int) -> str:
    """`arg` when it looks like a key or a word, else 「第n個參數」 (never a path)."""
    return arg if _SHOWN.fullmatch(arg) else f"第{n}個參數"


def _rows(name: str) -> list[dict]:
    data = (TEXT / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != TEXT_SHA256[name]:
        raise BtData(name)
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


@functools.cache
def units() -> dict:
    """unit_key -> verse_units.jsonl row."""
    return {r["unit_key"]: r for r in _rows("verse_units.jsonl")}


@functools.cache
def book_rows() -> dict:
    """book_id -> books.jsonl row."""
    return {r["book_id"]: r for r in _rows("books.jsonl")}


@functools.cache
def _order() -> tuple[list[str], dict[str, int], dict[str, str]]:
    """Unit keys in canonical order, their position, and whole verse -> merged unit key."""
    keys = sorted(units(), key=lambda k: units()[k]["ord"])
    member = {}
    for k in keys:
        r = units()[k]
        for v in range(int(r["v_start"]), int(r["v_end"]) + 1):
            member[f"{r['book_id']}.{r['chapter']}.{v}"] = k
    return keys, {k: i for i, k in enumerate(keys)}, member


def clear_caches() -> None:
    """Forget the loaded layer (tests point TEXT / TEXT_SHA256 at a synthetic one)."""
    for f in (units, book_rows, _order):
        f.cache_clear()


def unit_of(key: str) -> str | None:
    """The unit holding a whole or merged verse key (gen.24.30 -> gen.24.29-30)."""
    if key in units():
        return key
    return _order()[2].get(key)


def resolve(key: str) -> tuple[list[str], str | None]:
    """(unit keys, problem): one key, a merged key, or a range KEY-KEY; problem 'half' | 'missing' | 'long'."""
    if _HALF.match(key):
        return [], "half"
    one = unit_of(key)
    if one:
        return [one], None
    a, sep, b = key.partition("-")
    if sep and _KEY.match(a) and _KEY.match(b):
        ua, ub = unit_of(a), unit_of(b)
        if ua and ub:
            keys, pos, _ = _order()
            lo, hi = sorted((pos[ua], pos[ub]))
            if hi - lo + 1 > MAX_LINES:
                return [], "long"
            return keys[lo:hi + 1], None
    return [], "missing"


_PROBLEM = {"half": "半節鍵不支援，請用整節", "missing": "查無此節", "long": f"範圍超過 {MAX_LINES} 節，請分段讀"}


def cmd_v(keys: Sequence[str]) -> list[str]:
    out = []
    for n, key in enumerate(keys, 1):
        found, problem = resolve(key)
        if problem:
            out.append(f"{shown(key, n)} <<{_PROBLEM[problem]}>>")
        else:
            out.extend(f"{u} {units()[u]['text']}" for u in found)
    return out


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as err:
        raise BtUsage(f"正規式無法解析：{err}") from None


def cmd_grep(pattern: str, books: str | None) -> list[str]:
    pat = _regex(pattern)
    wanted = set(books.split(",")) if books else None
    if wanted and not wanted <= set(book_rows()):
        bad = sorted(wanted - set(book_rows()))
        raise BtUsage(f"不認得的書卷 {', '.join(shown(b, i) for i, b in enumerate(bad, 1))}")
    keys = _order()[0]
    hits = [k for k in keys if (wanted is None or units()[k]["book_id"] in wanted) and pat.search(units()[k]["text"])]
    out = [f"{k} {units()[k]['text']}" for k in hits[:MAX_LINES]]
    if len(hits) > MAX_LINES:
        out.append(f"... 共 {len(hits)} 筆，只顯示前 {MAX_LINES} 筆；請縮小正規式或書卷")
    else:
        out.append(f"[{len(hits)} 筆]")
    return out


def cmd_books() -> list[str]:
    rows = sorted(book_rows().values(), key=lambda r: r["ord"])
    return [f"{r['book_id']} {r['name']} {r['chapter_count']}" for r in rows]


def run(argv: Sequence[str]) -> list[str]:
    if not argv:
        raise BtUsage("缺少子命令")
    cmd, args = argv[0], list(argv[1:])
    table: dict[str, Callable[[], list[str]]] = {
        "v": lambda: cmd_v(args), "books": cmd_books,
        "grep": lambda: cmd_grep(args[0], args[1] if len(args) > 1 else None)}
    if cmd not in table:
        raise BtUsage(f"不認得的子命令 {shown(cmd, 1)}")
    if (cmd == "v" and not args) or (cmd == "grep" and not 1 <= len(args) <= 2) or (cmd == "books" and args):
        raise BtUsage(f"{cmd} 的參數不對")
    return table[cmd]()


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    try:
        lines = run(sys.argv[1:] if argv is None else argv)
    except BtUsage as err:
        print(f"錯誤：{err}\n{USAGE}", file=out)
        return 2
    except BtData:
        print("錯誤：資料檔核對失敗，請停止並回報", file=out)
        return 2
    except Exception as err:  # noqa: BLE001 - the agent must never see a traceback or a path
        print(f"錯誤：工具內部錯誤（{type(err).__name__}），請停止並回報", file=out)
        return 2
    print("\n".join(lines), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
