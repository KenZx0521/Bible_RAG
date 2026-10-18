"""Shared stage-0 harness for the generation-side KG card experiments (prereg.md §1).

Host side, stdlib only. Calls Ollama /api/chat directly with prod's generation model and options
(gemma4:e4b-it-q8_0, temperature 0.1, num_predict 10000; backend env LLM_TEMPERATURE / LLM_MAX_TOKENS),
one shared system prompt and one shared user template for every arm. Every call records the
token counts Ollama reports so the common K0 truncation check can be made afterwards.

Jobs (one JSON object each, run in list order):
  {"job_id", "exp", "item", "arm", "rep", "kind": "gen"|"stage1"|"seed",
   "system": str, "user": str}                                   # fixed prompt
  {"job_id", ..., "system": str, "user_template": str,            # stage-2 prompt: "{slot}" is filled
   "slot_from": <stage1 job_id>, "slot_max_lines": int, "slot_cap_chars": int}
Outputs: one "answer" line per job appended to <out>.jsonl; reruns skip done job_ids.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

STORE = Path("/mnt/ollama-data/bible_rag_store")
OUT_ROOT = STORE / "reports/kg_cards_20261018"
KS = STORE / "reports/kg_niche_20261018/kgniche"          # archived probes (FP's "K")
MH = STORE / "reports/multihop_kg_20261012/session_e73fd5d9"
TEXT_LAYER = STORE / "layers/text/text@247eafe44b02"

OLLAMA = "http://localhost:11434"
MODEL = "gemma4:e4b-it-q8_0"
OPTIONS = {"temperature": 0.1, "num_predict": 10000}
TIMEOUT_S = 900
MAX_ROUNDS = 3

# prod utils/generator.py SYSTEM_PROMPT, rule 1 widened to the auxiliary block (same for every arm)
SYSTEM_PROMPT = """你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」與「輔助資料」中的資訊來回答，禁止使用其他任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）
3. 將相關經文內容整理成連貫的回答
4. 不要加入提供內容中沒有提到的推論、解讀或額外資訊
5. 回答使用繁體中文"""

AUX_LABEL = "以下是輔助資料（依經文整理）："
ANSWER_INSTRUCTION = "請先逐步列出推理，最後一行只寫「答案：」加上答案。"

USER_TEMPLATE = """以下是提供的經文段落（你只能使用這些內容來回答）：

{context}
{aux}
---

嚴格根據以上經文段落{aux_ref}的內容，回答以下問題。不要添加提供內容中沒有的資訊。{instruction}
{question}"""


def context_block(i: int, src: dict) -> str:
    """prod utils/generator.build_context_blocks, one block (keep in sync)."""
    header = f"[{i}] {src.get('book_name', '')} 第{src.get('chapter_num', '')}章"
    if src.get("title"):
        header += f" - {src['title']}"
    if src.get("verse_range"):
        header += f" ({src['verse_range']}節)"
    return f"{header}\n{src.get('content', '')}"


def build_context(sources: list[dict]) -> str:
    return "\n\n".join(context_block(i, s) for i, s in enumerate(sources, 1))


def build_user(context: str, question: str, aux_block: str | None,
               instruction: str = ANSWER_INSTRUCTION) -> str:
    """aux_block None or "" = no auxiliary section (B0)."""
    if aux_block:
        aux, aux_ref = f"\n{AUX_LABEL}\n{aux_block}\n", "與輔助資料"
    else:
        aux, aux_ref = "", ""
    return USER_TEMPLATE.format(context=context, aux=aux, aux_ref=aux_ref,
                                instruction=instruction, question=question)


# ---------------------------------------------------------------- Ollama
def _post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def api_ps() -> dict:
    with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=30) as resp:
        return json.loads(resp.read())


def chat(system: str, user: str, options: dict | None = None) -> dict:
    body = {"model": MODEL, "stream": False, "options": dict(options or OPTIONS),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    t0 = time.time()
    data = _post("/api/chat", body, TIMEOUT_S)
    msg = data.get("message", {})
    return {"content": msg.get("content", ""), "thinking_chars": len(msg.get("thinking") or ""),
            "prompt_eval_count": data.get("prompt_eval_count"), "eval_count": data.get("eval_count"),
            "done_reason": data.get("done_reason"), "elapsed_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- slot filling (two-stage arms)
def fill_slot(stage1_text: str, max_lines: int, cap_chars: int) -> str:
    """First max_lines non-empty lines of the stage-1 output, then cut to cap_chars."""
    lines = [ln.strip() for ln in stage1_text.strip().splitlines() if ln.strip()]
    return "\n".join(lines[:max_lines])[:cap_chars]


# ---------------------------------------------------------------- runner
def done_jobs(out_path: Path) -> dict:
    done = {}
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            d = json.loads(line)
            if d.get("type") == "answer":
                done[d["job_id"]] = d
    return done


def resolve_user(job: dict, done: dict) -> str | None:
    if "user" in job:
        return job["user"]
    src = done.get(job["slot_from"])
    if src is None:
        return None
    slot = fill_slot(src["content"], job["slot_max_lines"], job["slot_cap_chars"])
    return job["user_template"].replace("{slot}", slot)


def run_jobs(jobs: list[dict], out_path: Path, log=print, options: dict | None = None) -> dict:
    """Run jobs in order; Ollama exceptions are retried in later rounds (not results)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for rnd in range(MAX_ROUNDS):
        done = done_jobs(out_path)
        todo = [j for j in jobs if j["job_id"] not in done]
        log(f"round {rnd}: {len(done)} done, {len(todo)} to do")
        if not todo:
            break
        for job in todo:
            user = resolve_user(job, done)
            if user is None:
                continue  # stage-1 dependency failed this round
            try:
                res = chat(job["system"], user, options)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"type": "error", "job_id": job["job_id"], "round": rnd,
                                        "error": repr(e)}, ensure_ascii=False) + "\n")
                continue
            rec = {"type": "answer", "job_id": job["job_id"], "exp": job.get("exp"),
                   "item": job.get("item"), "arm": job.get("arm"), "rep": job.get("rep"),
                   "kind": job.get("kind", "gen"), "user_chars": len(user), "round": rnd, **res}
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done[job["job_id"]] = rec
    done = done_jobs(out_path)
    log(f"FINISHED {len(done)} of {len(jobs)}")
    return done


# ---------------------------------------------------------------- answer parsing / normalisation
_ANS = re.compile(r"答案\s*[：:]")
_PARENS = re.compile(r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")
_MD = re.compile(r"[*_#`>]")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", _MD.sub("", unicodedata.normalize("NFKC", text or "")))


def answer_line(content: str) -> str | None:
    """Text after the last 「答案：」 up to the end of its line (or the next non-empty line if the
    marker ends its line). None = no answer line (format failure)."""
    text = unicodedata.normalize("NFKC", content or "")
    ms = list(_ANS.finditer(text))
    if not ms:
        return None
    rest = text[ms[-1].end():]
    for ln in rest.splitlines():
        if norm(ln):
            return norm(ln)
    return None


def strip_parens(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, _PARENS.sub("", s)
    return s


_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_RUN = re.compile(r"[零〇一二兩三四五六七八九十百]+")


def cn2int(s: str) -> int | None:
    """一 … 九百九十九 (十二, 四十一, 二十五, 一百零五); None if not a numeral."""
    if not s or any(c not in _CN and c not in "十百" for c in s):
        return None
    if all(c in _CN for c in s):  # bare digits: 三 → 3, 一九 → 19
        return int("".join(str(_CN[c]) for c in s))
    total, cur = 0, 0
    for c in s:
        if c == "百":
            total += (cur or 1) * 100
            cur = 0
        elif c == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = _CN[c]
    return total + cur


def numbers_in(s: str) -> set[int]:
    out = {int(x) for x in re.findall(r"\d+", s)}
    for run in _CN_RUN.findall(s):
        v = cn2int(run)
        if v is not None:
            out.add(v)
    return out


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
