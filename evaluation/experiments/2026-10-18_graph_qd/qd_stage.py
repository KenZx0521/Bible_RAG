"""Container stages and Ollama checks of the QD experiment (host side, no gold).

A Stage is new82_ans build_it.Stage with four changes: its directory is a parameter (the
QD stages never write into new82_ans/stages), a decompose meta must also name the frozen
model and max_tokens, a decomposition that fell back because Ollama raised is not a
result (plan.md §4 K): it stays missing and is redone, and a chunk that fails at the
container level (no meta line, a hung exec) is left for the next round instead of stopping
the stage. A half-written last line left by a killed run is cut off before the file is read.
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

import qd_common as Q

CONTAINER_SCRIPT = Q.HERE / "qd_container.py"
CHUNK = {"decompose": 8, "encode": 200, "rerank": 8}
MAX_ROUNDS = 3
EXEC_TIMEOUT = 1800         # seconds per docker exec; a hung exec counts as a failed chunk
FAILED_CHUNK_PAUSE = 60     # seconds before the next chunk after a container-level failure


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def container_body() -> str:
    body = CONTAINER_SCRIPT.read_text(encoding="utf-8")
    if body.count(Q.H.PLACEHOLDER) != 1:
        raise Q.QdError("qd_container.py must hold the helper placeholder exactly once")
    return body.replace(Q.H.PLACEHOLDER, Q.H.iterq_helpers())


def run_container(payload: dict, err_path: Path) -> list[dict]:
    """One docker exec with the payload; returns the parsed stdout lines (stderr -> err_path)."""
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode()
    script = f'PAYLOAD_B64 = "{b64}"\n' + container_body()
    with err_path.open("ab") as err:
        try:
            proc = subprocess.run(Q.H.CMD, input=script.encode("utf-8"), stdout=subprocess.PIPE,
                                  stderr=err, timeout=EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return [{"type": "exit", "returncode": None, "error": f"timeout after {EXEC_TIMEOUT}s"}]
    lines = []
    for raw in proc.stdout.decode("utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            lines.append({"type": "garbled", "text": raw[:300]})
    if proc.returncode != 0:
        lines.append({"type": "exit", "returncode": proc.returncode})
    return lines


def check_decompose_meta(meta: dict) -> None:
    Q.gd.expect("decompose meta type", meta.get("type"), "meta")
    Q.gd.expect("decompose build_id", meta.get("build_id"), Q.gd.BUILD_ID)
    Q.gd.expect("decompose temperature", meta.get("decomposer_temperature"), 0.0)
    Q.gd.expect("decompose prompt sha", meta.get("prompt_file_sha256"), Q.PROMPT_SHA256)
    Q.gd.expect("decompose llm", meta.get("llm"), Q.LLM_LABEL)
    Q.gd.expect("decompose max_tokens", meta.get("llm_max_tokens"), Q.LLM_MAX_TOKENS)


class Stage:
    """One container stage: a JSON-lines file of meta / result / error lines (append only)."""

    RESULT = {"decompose": ("dec", "key"), "encode": ("q", "sid"), "rerank": ("r", "key")}

    def __init__(self, root: Path, name: str, mode: str,
                 runner: Callable[[dict, Path], list[dict]] = run_container) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.name, self.mode, self.runner = name, mode, runner
        self.path = root / f"{name}.jsonl"
        self.err = root / f"{name}.err.log"
        self.repair_tail()

    def repair_tail(self) -> None:
        """Cut a half-written last line (a run killed while appending)."""
        if not self.path.exists():
            return
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):
            keep = data[:data.rfind(b"\n") + 1]
            self.path.write_bytes(keep)
            log(f"{self.name}: cut {len(data) - len(keep)} bytes of a half-written last line")

    def lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(s) for s in self.path.read_text(encoding="utf-8").splitlines() if s.strip()]

    def results(self) -> dict[str, dict]:
        kind, field = self.RESULT[self.mode]
        out: dict[str, dict] = {}
        for rec in self.lines():
            if rec.get("type") != kind:
                continue
            if self.mode == "decompose" and not Q.dec_is_result(rec):
                continue
            out.setdefault(rec[field], rec)
        return out

    def metas(self) -> list[dict]:
        return [r for r in self.lines() if r.get("type") == "meta"]

    def check_meta(self, meta: dict) -> None:
        if self.mode == "encode":
            Q.gd.verify_container_meta(meta, "embedder", strict=True)
        elif self.mode == "rerank":
            Q.gd.verify_container_meta(meta, "reranker", strict=True)
        else:
            check_decompose_meta(meta)

    def ensure(self, items: list[dict], prompt: dict | None = None,
               before_chunk: Callable[[], None] | None = None) -> dict[str, dict]:
        _, field = self.RESULT[self.mode]
        keys = [it[field] for it in items]
        if len(set(keys)) != len(keys):
            raise Q.QdError(f"{self.name}: duplicate keys in the items")
        for rnd in range(MAX_ROUNDS):
            done = self.results()
            todo = [it for it in items if it[field] not in done]
            if not todo:
                break
            log(f"{self.name}: round {rnd}, {len(done)} done, {len(todo)} to do")
            step = CHUNK[self.mode]
            for i in range(0, len(todo), step):
                part = todo[i:i + step]
                if before_chunk is not None:
                    before_chunk()
                t0 = time.time()
                payload = {"mode": self.mode, "items": part}
                if prompt is not None:
                    payload["prompt"] = prompt
                lines = self.runner(payload, self.err)
                if not lines or lines[0].get("type") != "meta":
                    # a container-level failure (exec, Postgres, timeout): these items stay
                    # missing for the next round; nothing is written
                    log(f"  {self.name}: chunk failed without a meta line: "
                        f"{json.dumps(lines[:2], ensure_ascii=False)[:300]}; pause {FAILED_CHUNK_PAUSE}s")
                    time.sleep(FAILED_CHUNK_PAUSE)
                    continue
                self.check_meta(lines[0])
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write("".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in lines))
                bad = [r for r in lines if r.get("type") in ("error", "garbled", "exit")]
                infra = [r["key"] for r in lines
                         if r.get("type") == "dec" and not Q.dec_is_result(r)]
                log(f"  {self.name}: {i + len(part)}/{len(todo)} ({time.time() - t0:.0f}s)"
                    + (f" problems: {json.dumps(bad, ensure_ascii=False)[:300]}" if bad else "")
                    + (f" ollama-failure fallbacks (redone): {infra}" if infra else ""))
        done = self.results()
        missing = [k for k in keys if k not in done]
        if missing:
            raise Q.QdError(f"{self.name}: {len(missing)} items still missing after "
                            f"{MAX_ROUNDS} rounds: {missing[:5]}")
        return {k: done[k] for k in keys}


# ------------------------------------------------------------------ Ollama (host, read-mostly)

def ollama_digest(model: str = Q.OLLAMA_MODEL) -> str:
    tags = httpx.get(f"{Q.OLLAMA_URL}/api/tags", timeout=30).json()
    for m in tags.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return m["digest"]
    raise Q.QdError(f"Ollama has no model {model}")


def check_ollama() -> str:
    got = ollama_digest()
    Q.gd.expect(f"Ollama {Q.OLLAMA_MODEL} digest", got, Q.OLLAMA_DIGEST)
    return got


def ollama_ps() -> list[dict]:
    return httpx.get(f"{Q.OLLAMA_URL}/api/ps", timeout=30).json().get("models", [])


def warm_up(keep_alive: str = "60m") -> float:
    """Load the frozen decomposer before a decompose stage (an empty prompt only loads it), so a
    cold 11 GB load cannot time out the first calls. Returns the seconds it took."""
    t0 = time.time()
    r = httpx.post(f"{Q.OLLAMA_URL}/api/generate",
                   json={"model": Q.OLLAMA_MODEL, "prompt": "", "stream": False,
                         "keep_alive": keep_alive}, timeout=600)
    r.raise_for_status()
    loaded = [m for m in ollama_ps() if m.get("name") == Q.OLLAMA_MODEL]
    if not loaded or loaded[0].get("digest") != Q.OLLAMA_DIGEST:
        raise Q.QdError(f"warm-up did not load {Q.OLLAMA_MODEL}: {ollama_ps()}")
    return time.time() - t0


def log_ps(path: Path, label: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "label": label,
                             "ps": ollama_ps()}, ensure_ascii=False) + "\n")
