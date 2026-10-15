"""The arms of the book_anchor ablation: in-process name swaps (prereg §3, §0.1 M1, §6 I4/I7).

arm(name, router=, routes=, snapshot=) swaps, around one retrieve_and_rerank call:

  router._gather                     ctrl: the original; a deepcopy of what it returns is kept
                                     as the snapshot (the pre-rank pool), the original object
                                     as ``gathered``. nopin: returns a deepcopy of the same
                                     question's ctrl snapshot. off: the original.
  router.pin_book_anchor_candidates  every arm: a recorder of book_gate and the pinned ids;
                                     nopin: book_gate False returns ``ranked`` itself, True
                                     calls the original with the arguments as given.
  routes._book_anchor                ctrl / nopin: the original, calls counted (M1);
                                     off: an async function returning [].

router.py binds pins' names by from-import, so they are swapped in router's namespace;
routes.py calls _book_anchor by its module global. A process lock that is not reentrant
guards arm(): nesting or a concurrent entry raises ArmReentryError; finally restores every
name. Modules are parameters (tests pass fakes); nothing here imports the backend.

intent_retry(intent_classifier) retries _llm_intent on an exception or an unparsable reply
(§6 I4); llm_capture(generator) proxies generator.get_llm_client to hash the messages sent
(§6 I7).
"""
from __future__ import annotations

import copy
import inspect
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import _ba_io

__all__ = ["ARMS", "ArmReentryError", "SnapshotError", "Snapshot", "ArmRecord", "arm",
           "nopin_pin", "off_book_anchor", "IntentLog", "intent_retry", "LlmCapture",
           "llm_capture"]

ARMS = ("ctrl", "nopin", "off")
_LOCK = threading.Lock()


class ArmReentryError(RuntimeError):
    """arm() entered while another arm() is active (nested or concurrent)."""


class SnapshotError(RuntimeError):
    """nopin without the same question's ctrl gather snapshot."""


@dataclass(frozen=True)
class Snapshot:
    query: str
    gathered: Any          # deepcopy of router._gather's return value, before any ranking


@dataclass
class ArmRecord:
    name: str
    gathered: Any = None                   # the Gathered object this arm ranked (a reference)
    snapshot: Snapshot | None = None       # ctrl only
    pins: list[dict] = field(default_factory=list)
    ba_calls: int = 0                      # routes._book_anchor calls
    ba_new: int = 0                        # candidates they returned

    @property
    def ba_invoked(self) -> bool:
        return self.ba_calls > 0

    @property
    def pinned(self) -> list[str]:
        return [pid for call in self.pins for pid in call["pinned"]]


def _bound(fn: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    bound = inspect.signature(fn).bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def nopin_pin(orig: Callable, signature_of: Callable | None = None) -> Callable:
    """nopin's book-anchor pin: book_gate False → ranked unchanged; True → orig as called.
    book_gate is read by binding the call to ``signature_of`` (default: orig)."""
    def pin(ranked, candidates, *args, **kwargs):
        if not _bound(signature_of or orig, (ranked, candidates, *args), kwargs)["book_gate"]:
            return ranked
        return orig(ranked, candidates, *args, **kwargs)
    pin.__wrapped_original__ = orig
    return pin


async def off_book_anchor(*args: Any, **kwargs: Any) -> list[dict]:
    """off: no book_anchor candidates at all."""
    return []


def _pin_recorder(rec: ArmRecord, orig: Callable, nopin: bool) -> Callable:
    def pin(ranked, candidates, *args, **kwargs):
        book_gate = bool(_bound(orig, (ranked, candidates, *args), kwargs)["book_gate"])
        before = {c["id"] for c in ranked}
        called = []

        def spy(*a, **k):
            called.append(True)
            return orig(*a, **k)

        target = nopin_pin(spy, signature_of=orig) if nopin else spy
        out = target(ranked, candidates, *args, **kwargs)
        rec.pins.append({"book_gate": book_gate,
                         "pinned": [c["id"] for c in out if c["id"] not in before],
                         "called": bool(called)})
        return out
    return pin


def _counting(rec: ArmRecord, inner: Callable) -> Callable:
    async def book_anchor(*args, **kwargs):
        rec.ba_calls += 1
        out = await inner(*args, **kwargs)
        rec.ba_new += len(out)
        return out
    return book_anchor


def _gather_swap(rec: ArmRecord, orig: Callable, snapshot: Snapshot | None) -> Callable:
    async def gather(*args, **kwargs):
        query = _bound(orig, args, kwargs)["query"]
        if rec.name == "nopin":
            if snapshot is None or snapshot.query != query:
                raise SnapshotError(f"nopin has no ctrl gather snapshot of query {query[:40]!r}")
            rec.gathered = copy.deepcopy(snapshot.gathered)
            return rec.gathered
        rec.gathered = await orig(*args, **kwargs)
        if rec.name == "ctrl":
            rec.snapshot = Snapshot(query, copy.deepcopy(rec.gathered))
        return rec.gathered
    return gather


@contextmanager
def arm(name: str, *, router: Any, routes: Any,
        snapshot: Snapshot | None = None) -> Iterator[ArmRecord]:
    """Swap router / routes names for one arm; the snapshot is used by nopin only."""
    if name not in ARMS:
        raise ValueError(f"unknown arm {name!r}; expected one of {ARMS}")
    if name == "nopin" and snapshot is None:
        raise SnapshotError("nopin needs the same question's ctrl gather snapshot")
    if not _LOCK.acquire(blocking=False):
        raise ArmReentryError(f"arm({name!r}) entered while another arm is active")
    rec = ArmRecord(name)
    saved = (router._gather, router.pin_book_anchor_candidates, routes._book_anchor)
    try:
        gather, pin, book_anchor = saved
        router._gather = _gather_swap(rec, gather, snapshot)
        router.pin_book_anchor_candidates = _pin_recorder(rec, pin, name == "nopin")
        routes._book_anchor = _counting(rec, off_book_anchor if name == "off" else book_anchor)
        yield rec
    finally:
        router._gather, router.pin_book_anchor_candidates, routes._book_anchor = saved
        _LOCK.release()


# ---------------------------------------------------------------- intent (§6 I4)

@dataclass
class IntentLog:
    attempts: int = 0
    ok: bool | None = None
    errors: list[str] = field(default_factory=list)


@contextmanager
def intent_retry(ic: Any, retries: int = 2) -> Iterator[IntentLog]:
    """Retry ic._llm_intent (at most ``retries`` times) when it raises or when its reply
    does not parse (ic._extract_json returns nothing, which prod turns into "topic").
    After the last failure it behaves as prod: the exception propagates to classify_intent
    (→ topic) or the topic fallback is returned. log.ok is False then."""
    log = IntentLog()
    orig_llm, orig_extract = ic._llm_intent, ic._extract_json
    state = {"parsed": True}

    def extract(text):
        out = orig_extract(text)
        state["parsed"] = bool(out)
        return out

    async def llm_intent(question):
        for attempt in range(1, retries + 2):
            log.attempts, state["parsed"] = attempt, True
            try:
                result = await orig_llm(question)
            except Exception as exc:  # noqa: BLE001 — retried, then prod's fallback
                log.errors.append(f"exception: {exc!r}"[:200])
                if attempt > retries:
                    log.ok = False
                    raise
                continue
            if state["parsed"]:
                log.ok = True
                return result
            log.errors.append("unparsable reply")
            if attempt > retries:
                log.ok = False
                return result
        raise AssertionError("unreachable")

    ic._llm_intent, ic._extract_json = llm_intent, extract
    try:
        yield log
    finally:
        ic._llm_intent, ic._extract_json = orig_llm, orig_extract


# ---------------------------------------------------------------- generator LLM proxy (§6 I7)

@dataclass
class LlmCapture:
    messages_sha: str | None = None
    options: dict = field(default_factory=dict)
    n_calls: int = 0


class _Proxy:
    def __init__(self, client: Any, cap: LlmCapture):
        self._client, self._cap = client, cap

    async def chat(self, messages, **kwargs):
        self._cap.messages_sha = _ba_io.messages_sha(messages)
        self._cap.options = dict(kwargs)
        self._cap.n_calls += 1
        return await self._client.chat(messages=messages, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


@contextmanager
def llm_capture(generator: Any) -> Iterator[LlmCapture]:
    """generator.get_llm_client returns a proxy that hashes the messages it forwards."""
    cap = LlmCapture()
    orig = generator.get_llm_client
    generator.get_llm_client = lambda: _Proxy(orig(), cap)
    try:
        yield cap
    finally:
        generator.get_llm_client = orig
