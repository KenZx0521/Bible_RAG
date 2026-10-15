"""book_anchor ablation arms (experiments/2026-10-15_book_anchor/ba_arms.py).

prereg §3 and §10 test_ba_arms, against fake router / routes / intent / generator modules
whose functions call each other through module globals, as backend router.py (from-import
of pins' names) and routes.py (_book_anchor by global name) do: every name is restored,
also after an exception; nested or concurrent entry raises; nopin gets a deep copy of the
ctrl snapshot; no snapshot stops nopin; the nopin pin passes book_gate=True through and
returns ranked itself on False; off's _book_anchor returns []; the recorder's ids and
book_gate; module names that cannot shadow the backend's; intent retry (§6 I4) and the
generator's LLM proxy (§6 I7).
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXP = _REPO / "evaluation" / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_io as bio  # noqa: E402
import ba_arms  # noqa: E402

ROUTES_SRC = '''
async def _book_anchor(inp, route, pool, strategies, errors, weight=0.9, top_k=10):
    return [dict(c) for c in ANCHORS]

async def route_r5(query):
    pool = [dict(c) for c in DENSE]
    return pool + await _book_anchor(query, "R5", pool, [], {})
'''

ROUTER_SRC = '''
class Gathered:
    def __init__(self, route, candidates, multi_book):
        self.route, self.candidates, self.multi_book = route, candidates, multi_book

async def _gather(query, verse_refs, intent_type, entity_names, keywords, active):
    return Gathered("R5", await routes.route_r5(query), MULTI)

def pin_book_anchor_candidates(ranked, candidates, top_k, max_pins=2, score_key="rerank_score",
                               book_gate=False):
    existing = {c["id"] for c in ranked}
    to_pin = [c for c in candidates
              if c.get("source_strategy") == "book_anchor" and c["id"] not in existing][:max_pins]
    return (to_pin + ranked)[:top_k]

async def retrieve_and_rerank(query, verse_refs, intent_type, entity_names, top_k=None,
                              keywords=None, use_graph=None):
    g = await _gather(query, verse_refs, intent_type, entity_names, keywords, None)
    for c in g.candidates:
        c["rerank_score"] = RR.get(c["id"], 0.0)
    ranked = sorted(g.candidates, key=lambda c: -c["rerank_score"])[:top_k]
    ranked = pin_book_anchor_candidates(ranked, g.candidates, top_k=top_k, max_pins=2,
                                        score_key="rerank_score", book_gate=g.multi_book)
    return ranked, {"route_used": g.route, "strategy_errors": {}}
'''

DENSE = [{"id": f"ps:d.{i}", "source_strategy": "hybrid_hybrid", "weight": 0.65} for i in range(4)]
ANCHORS = [{"id": f"ps:a.{i}", "source_strategy": "book_anchor", "weight": 0.9} for i in range(3)]
RR = {"ps:d.0": 0.9, "ps:d.1": 0.8, "ps:d.2": 0.7, "ps:d.3": 0.6, "ps:a.0": 0.1}


def fake_modules(multi=False, anchors=ANCHORS):
    routes = types.ModuleType("fake_routes")
    routes.__dict__.update(DENSE=DENSE, ANCHORS=anchors)
    exec(ROUTES_SRC, routes.__dict__)
    router = types.ModuleType("fake_router")
    router.__dict__.update(routes=routes, MULTI=multi, RR=RR)
    exec(ROUTER_SRC, router.__dict__)
    return router, routes


def names(router, routes):
    return (router._gather, router.pin_book_anchor_candidates, routes._book_anchor)


def run(coro):
    return asyncio.run(coro)


async def retrieve(router, query="q"):
    results, _ = await router.retrieve_and_rerank(query, [], "cross_reference", [], top_k=5)
    return [r["id"] for r in results]


async def ctrl_then(router, routes, name, query="q", query_ctrl="q"):
    with ba_arms.arm("ctrl", router=router, routes=routes) as ctrl:
        ctrl_ids = await retrieve(router, query_ctrl)
    with ba_arms.arm(name, router=router, routes=routes, snapshot=ctrl.snapshot) as rec:
        ids = await retrieve(router, query)
    return ctrl, ctrl_ids, rec, ids


# ---------------------------------------------------------------- swaps and restore

@pytest.mark.parametrize("name", ba_arms.ARMS)
def test_every_name_is_restored_after_the_arm(name):
    router, routes = fake_modules()
    before = names(router, routes)
    run(ctrl_then(router, routes, name))
    assert names(router, routes) == before


@pytest.mark.parametrize("name", ba_arms.ARMS)
def test_every_name_is_restored_after_an_exception(name):
    router, routes = fake_modules()
    before = names(router, routes)
    snapshot = ba_arms.Snapshot("q", router.Gathered("R5", [], False))
    with pytest.raises(RuntimeError, match="boom"):
        with ba_arms.arm(name, router=router, routes=routes, snapshot=snapshot):
            assert names(router, routes) != before
            raise RuntimeError("boom")
    assert names(router, routes) == before
    with ba_arms.arm("ctrl", router=router, routes=routes):    # the lock was released
        pass


def test_nested_entry_raises_and_restores():
    router, routes = fake_modules()
    before = names(router, routes)
    with ba_arms.arm("ctrl", router=router, routes=routes):
        with pytest.raises(ba_arms.ArmReentryError):
            with ba_arms.arm("off", router=router, routes=routes):
                pass
    assert names(router, routes) == before


def test_concurrent_entry_raises():
    router, routes = fake_modules()

    async def hold():
        with ba_arms.arm("ctrl", router=router, routes=routes):
            await asyncio.sleep(0.05)

    async def enter():
        await asyncio.sleep(0.01)
        with ba_arms.arm("off", router=router, routes=routes):
            pass

    async def both():
        return await asyncio.gather(hold(), enter(), return_exceptions=True)

    outcomes = run(both())
    assert outcomes[0] is None and isinstance(outcomes[1], ba_arms.ArmReentryError)


def test_an_unknown_arm_raises():
    router, routes = fake_modules()
    with pytest.raises(ValueError):
        with ba_arms.arm("tail", router=router, routes=routes):
            pass


# ---------------------------------------------------------------- ctrl recorder

def test_ctrl_records_the_pinned_ids_and_book_gate_and_keeps_its_pool():
    router, routes = fake_modules()
    ctrl, ids, rec, _ = run(ctrl_then(router, routes, "off"))
    assert ids == ["ps:a.1", "ps:a.2", "ps:d.0", "ps:d.1", "ps:d.2"]
    assert ctrl.pins == [{"book_gate": False, "pinned": ["ps:a.1", "ps:a.2"], "called": True}]
    assert ctrl.pinned == ["ps:a.1", "ps:a.2"] and ctrl.ba_calls == 1 and ctrl.ba_new == 3
    assert ctrl.gathered is not ctrl.snapshot.gathered
    assert all("rerank_score" in c for c in ctrl.gathered.candidates)     # the ranked original
    assert not any("rerank_score" in c for c in ctrl.snapshot.gathered.candidates)


def test_multi_book_book_gate_is_recorded_true():
    router, routes = fake_modules(multi=True)
    ctrl, *_ = run(ctrl_then(router, routes, "nopin"))
    assert ctrl.pins[0]["book_gate"] is True


# ---------------------------------------------------------------- nopin

def test_nopin_ranks_a_deep_copy_of_the_ctrl_snapshot():
    router, routes = fake_modules()
    ctrl, _, nopin, ids = run(ctrl_then(router, routes, "nopin"))
    assert ids == ["ps:d.0", "ps:d.1", "ps:d.2", "ps:d.3", "ps:a.0"]
    assert nopin.ba_calls == 0                              # no second gather
    snap = ctrl.snapshot.gathered.candidates
    got = nopin.gathered.candidates
    assert [c["id"] for c in got] == [c["id"] for c in snap]
    assert all(a is not b for a, b in zip(got, snap))
    assert all(a is not b for a, b in zip(got, ctrl.gathered.candidates))
    got[0]["weight"] = -1.0                                 # nopin's in-place rewrite
    assert snap[0]["weight"] == 0.65


def test_ctrl_rewrites_after_the_snapshot_do_not_reach_nopin():
    router, routes = fake_modules()
    with ba_arms.arm("ctrl", router=router, routes=routes) as ctrl:
        run(retrieve(router))
    ctrl.gathered.candidates[0]["weight"] = 99.0            # ctrl's objects, changed afterwards
    ctrl.gathered.candidates.append({"id": "ps:x", "source_strategy": "book_anchor"})
    with ba_arms.arm("nopin", router=router, routes=routes, snapshot=ctrl.snapshot) as nopin:
        run(retrieve(router))
    assert nopin.gathered.candidates[0]["weight"] == 0.65
    assert "ps:x" not in [c["id"] for c in nopin.gathered.candidates]


def test_nopin_without_a_snapshot_or_with_another_questions_raises():
    router, routes = fake_modules()
    with pytest.raises(ba_arms.SnapshotError):
        with ba_arms.arm("nopin", router=router, routes=routes):
            pass
    with pytest.raises(ba_arms.SnapshotError):
        run(ctrl_then(router, routes, "nopin", query="q2", query_ctrl="q1"))


def test_nopin_pin_returns_ranked_itself_without_book_gate():
    seen = []

    def orig(ranked, candidates, top_k, max_pins=2, score_key="rerank_score", book_gate=False):
        seen.append(book_gate)
        return ["pinned", *ranked]

    pin = ba_arms.nopin_pin(orig)
    ranked = [{"id": "x"}]
    assert pin(ranked, [{"id": "a"}], top_k=5, max_pins=2, book_gate=False) is ranked
    assert pin(ranked, [{"id": "a"}], 5) is ranked                    # default book_gate
    assert seen == []


def test_nopin_pin_passes_every_argument_through_with_book_gate():
    calls = []

    def orig(ranked, candidates, top_k, max_pins=2, score_key="rerank_score", book_gate=False):
        calls.append((ranked, candidates, top_k, max_pins, score_key, book_gate))
        return "orig"

    pin = ba_arms.nopin_pin(orig)
    ranked, cands = [{"id": "x"}], [{"id": "a"}]
    assert pin(ranked, cands, top_k=5, max_pins=2, score_key="fused_score", book_gate=True) == "orig"
    assert calls == [(ranked, cands, 5, 2, "fused_score", True)]
    assert calls[0][0] is ranked and calls[0][1] is cands


def test_nopin_keeps_multi_book_pins():
    router, routes = fake_modules(multi=True)
    ctrl, ctrl_ids, nopin, ids = run(ctrl_then(router, routes, "nopin"))
    assert ids == ctrl_ids
    assert nopin.pins == [{"book_gate": True, "pinned": ["ps:a.1", "ps:a.2"], "called": True}]


def test_nopin_single_book_records_the_call_without_pins():
    router, routes = fake_modules()
    _, _, nopin, _ = run(ctrl_then(router, routes, "nopin"))
    assert nopin.pins == [{"book_gate": False, "pinned": [], "called": False}]


# ---------------------------------------------------------------- off

def test_off_book_anchor_returns_an_empty_list():
    router, routes = fake_modules()
    _, _, off, ids = run(ctrl_then(router, routes, "off"))
    assert ids == ["ps:d.0", "ps:d.1", "ps:d.2", "ps:d.3"]
    assert off.ba_calls == 1 and off.ba_new == 0 and off.pinned == []
    assert all(c["source_strategy"] != "book_anchor" for c in off.gathered.candidates)


def test_off_replacement_is_an_async_function_returning_empty():
    out = asyncio.run(ba_arms.off_book_anchor(object(), "R5", [], [], {}))
    assert out == []


def test_ctrl_without_book_anchor_call_is_seen_as_not_invoked():
    router, routes = fake_modules(anchors=[])
    router.routes = types.SimpleNamespace(route_r5=_no_anchor_route, _book_anchor=routes._book_anchor)
    with ba_arms.arm("ctrl", router=router, routes=router.routes) as ctrl:
        run(retrieve(router))
    assert ctrl.ba_calls == 0 and not ctrl.ba_invoked


async def _no_anchor_route(query):
    return [dict(c) for c in DENSE]


# ---------------------------------------------------------------- module names

def test_experiment_module_names_cannot_shadow_the_backends():
    backend = {p.stem for p in (_REPO / "backend").iterdir()
               if p.suffix == ".py" or (p.is_dir() and not p.name.startswith("."))}
    assert {"config", "utils", "serving", "database", "models", "routers", "main"} <= backend
    ours = {p.stem for p in _EXP.glob("*.py")}
    assert ours and not ours & backend, ours & backend


# ---------------------------------------------------------------- intent retry (§6 I4)

INTENT_SRC = '''
import json
REPLIES = []

async def _llm_intent(question):
    reply = REPLIES.pop(0)
    if isinstance(reply, Exception):
        raise reply
    parsed = _extract_json(reply)
    if not parsed:
        return "topic", [], []
    return parsed["intent"], parsed.get("entities", []), []

def _extract_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None

async def classify_intent(question):
    try:
        intent, entities, keywords = await _llm_intent(question)
    except Exception:
        intent, entities, keywords = "topic", [], []
    return {"type": intent, "entities": entities, "keywords": keywords}
'''


def fake_intent(*replies):
    ic = types.ModuleType("fake_intent")
    exec(INTENT_SRC, ic.__dict__)
    ic.REPLIES.extend(replies)
    return ic


GOOD = '{"intent": "cross_reference", "entities": ["以賽亞書"]}'


def classify(ic, retries=2):
    with ba_arms.intent_retry(ic, retries) as log:
        out = run(ic.classify_intent("q"))
    return out, log


def test_intent_first_try():
    ic = fake_intent(GOOD)
    out, log = classify(ic)
    assert out["type"] == "cross_reference" and log.ok is True and log.attempts == 1


def test_intent_retries_an_exception_and_an_unparsable_reply():
    ic = fake_intent(RuntimeError("timeout"), "thinking only", GOOD)
    out, log = classify(ic)
    assert out["type"] == "cross_reference" and log.ok is True and log.attempts == 3
    assert len(log.errors) == 2 and not ic.REPLIES


def test_intent_gives_up_after_two_retries_like_prod():
    ic = fake_intent("x", "y", "z", GOOD)
    out, log = classify(ic)
    assert out["type"] == "topic" and log.ok is False and log.attempts == 3
    assert ic.REPLIES == [GOOD]
    ic = fake_intent(RuntimeError("a"), RuntimeError("b"), RuntimeError("c"))
    out, log = classify(ic)
    assert out["type"] == "topic" and log.ok is False and log.attempts == 3


def test_intent_names_are_restored():
    ic = fake_intent(GOOD)
    before = (ic._llm_intent, ic._extract_json)
    classify(ic)
    assert (ic._llm_intent, ic._extract_json) == before


# ---------------------------------------------------------------- LLM proxy (§6 I7)

class FakeClient:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, temperature=0.1, max_tokens=512):
        self.calls.append(messages)
        return "答案"


def test_llm_capture_hashes_the_messages_and_options_and_restores():
    client = FakeClient()
    gen = types.ModuleType("fake_generator")
    gen.get_llm_client = lambda: client
    original = gen.get_llm_client
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    with ba_arms.llm_capture(gen) as cap:
        answer = run(gen.get_llm_client().chat(messages=messages, temperature=0.1, max_tokens=10000))
    assert answer == "答案" and client.calls == [messages]
    assert cap.messages_sha == bio.messages_sha(messages)
    assert cap.options == {"temperature": 0.1, "max_tokens": 10000} and cap.n_calls == 1
    assert gen.get_llm_client is original
