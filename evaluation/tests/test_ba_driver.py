"""book_anchor ablation container driver, host-testable logic (experiments/.../ba_driver.py).

The container path (main.py lifespan, PG, Qdrant, models) runs only in the batch container
and is verified by smoke and I0–I4/I7 (prereg §10). Here the per-question and per-item logic
runs against fakes: intent_classifier.py and generator.py compiled from the repo's backend
source with their backend imports replaced by stubs, and a fake router / routes pair that
calls its names through module globals as router.py and routes.py do. Covered: one intent
per question shared by every arm and re-run (§2, §6 I4); ctrl → nopin → off; M1's skip and
--force-ids; strategy_errors re-run at most twice; I7 (exit 3 before any LLM call); failed
answers retried twice then written; the messages hash; resume and the JSON-lines stream.
The container entry itself (_run_retrieve / _run_generate) runs against fake backend
modules in sys.modules: its meta lines pass §6 I0 against an eval3c-shaped run_meta
(load_models' "bge_m3" renamed to /health's "embedder"); a failed LLM health check or
handshake writes nothing, so the same command resumes cleanly; nothing to do loads nothing.
"""

import ast
import asyncio
import io
import json
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXP = _REPO / "evaluation" / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_checks as ck  # noqa: E402
import _ba_io as bio  # noqa: E402
import ba_driver as drv  # noqa: E402


def backend_module(rel, name, **inject):
    """A backend module from its repo source; imports of config / utils.* are dropped and
    the names they bound come from ``inject``."""
    tree = ast.parse((_REPO / "backend" / rel).read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in ("config", "utils"))]
    mod = types.ModuleType(name)
    mod.__dict__.update(inject)
    exec(compile(tree, rel, "exec"), mod.__dict__)
    return mod


class FakeClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, messages, temperature=0.1, max_tokens=512):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def generator_module(client):
    settings = types.SimpleNamespace(llm_temperature=0.1, llm_max_tokens=10000)
    return backend_module("utils/generator.py", "fake_generator", settings=settings,
                          get_llm_client=lambda: client)


def intent_module(client):
    found = types.SimpleNamespace(refs=[], rejected=[])
    return backend_module("utils/intent_classifier.py", "fake_intent",
                          get_llm_client=lambda: client,
                          find_verse_references=lambda q: found)


ROUTES_SRC = '''
async def _book_anchor(inp, route, pool, strategies, errors, weight=0.9, top_k=10):
    return [dict(c) for c in ANCHORS.get(inp, [])]

async def route(query):
    pool = [dict(c) for c in DENSE]
    if query in ANCHORS:
        pool += await _book_anchor(query, "R5", pool, [], {})
    return pool
'''

ROUTER_SRC = '''
class Gathered:
    def __init__(self, route, candidates, multi_book):
        self.route, self.candidates, self.multi_book = route, candidates, multi_book
        self.signals = None

async def _gather(query, verse_refs, intent_type, entity_names, keywords, active):
    CALLS.append(intent_type)
    return Gathered("R5" if intent_type == "cross_reference" else "fallback",
                    await routes.route(query), False)

def pin_book_anchor_candidates(ranked, candidates, top_k, max_pins=2, score_key="rerank_score",
                               book_gate=False):
    existing = {c["id"] for c in ranked}
    pins = [c for c in candidates
            if c.get("source_strategy") == "book_anchor" and c["id"] not in existing]
    return (pins[:max_pins] + ranked)[:top_k]

async def retrieve_and_rerank(query, verse_refs, intent_type, entity_names, top_k=None,
                              keywords=None, use_graph=None):
    g = await _gather(query, verse_refs, intent_type, entity_names, keywords, None)
    for c in g.candidates:
        c["rerank_score"] = RR.get(c["id"], 0.0)
    ranked = sorted(g.candidates, key=lambda c: -c["rerank_score"])[:top_k]
    ranked = pin_book_anchor_candidates(ranked, g.candidates, top_k=top_k, book_gate=False)
    errors = ERRORS.pop(0) if ERRORS else {}
    return ranked, {"route_used": g.route, "strategy_errors": dict(errors),
                    "reranked_top_k": len(ranked), "strategies_used": ["semantic"]}
'''


def passage(pid, strategy="hybrid_hybrid", weight=0.65):
    return {"id": pid, "book_name": "以賽亞書", "chapter_num": 40, "title": "t",
            "verse_range": "1-11", "content": f"text {pid}", "source_strategy": strategy,
            "weight": weight, "book_id": "isa", "semantic_score": 0.5}


DENSE = [passage(f"ps:isa.{i}.1") for i in range(1, 6)]
RR = {f"ps:isa.{i}.1": 1 - i / 10 for i in range(1, 6)}


def deps(intent_replies=('{"intent": "cross_reference", "entities": [], "keywords": []}',),
         anchors=None, errors=(), gen_replies=()):
    routes = types.ModuleType("fake_routes")
    routes.__dict__.update(DENSE=DENSE, ANCHORS=anchors or {})
    exec(ROUTES_SRC, routes.__dict__)
    router = types.ModuleType("fake_router")
    router.__dict__.update(routes=routes, RR=RR, ERRORS=list(errors), CALLS=[])
    exec(ROUTER_SRC, router.__dict__)
    intent_client = FakeClient(intent_replies)
    gen_client = FakeClient(gen_replies)
    gen = generator_module(gen_client)
    d = drv.Deps(ic=intent_module(intent_client), router=router, routes=routes,
                 generator=gen, build_blocks=gen.build_context_blocks)
    return d, intent_client, gen_client


ANCHOR_Q = {"Q_ba": [passage("ps:isa.6.1", "book_anchor", 0.9),
                     passage("ps:isa.13.1", "book_anchor", 0.9)]}


def retrieve(d, qid="Q_ba", question="Q_ba", forced=False):
    return asyncio.run(drv.retrieve_question(qid, question, d, forced))


# ---------------------------------------------------------------- retrieve

def test_three_arms_on_one_intent_in_order():
    d, intent_client, _ = deps(anchors=ANCHOR_Q)
    row = retrieve(d)
    assert len(intent_client.calls) == 1
    assert d.router.CALLS == ["cross_reference", "cross_reference"]   # ctrl and off gather
    arms = row["arms"]
    assert arms["ctrl"]["ids"][:2] == ["ps:isa.6.1", "ps:isa.13.1"]
    assert arms["nopin"]["ids"] == [f"ps:isa.{i}.1" for i in range(1, 6)]
    assert arms["off"]["ids"] == arms["nopin"]["ids"]
    assert arms["ctrl"]["pins"][0]["pinned"] == ["ps:isa.6.1", "ps:isa.13.1"]
    assert arms["ctrl"]["ba_calls"] == 1 and arms["off"]["ba_calls"] == 1
    assert row["arms_skipped"] is None and row["intent_ok"] is True
    assert arms["ctrl"]["ctx_sha"] == bio.ctx_sha(arms["ctrl"]["results"], d.build_blocks)
    assert arms["ctrl"]["ctx_sha"] != arms["off"]["ctx_sha"]
    assert {p["id"] for p in arms["ctrl"]["pool"]} >= {"ps:isa.6.1", "ps:isa.1.1"}
    assert all("rerank_score" in p for p in arms["ctrl"]["pool"])
    json.loads(bio.dumps_line(row))


def test_m1_skips_nopin_and_off_when_book_anchor_was_never_called():
    d, _, _ = deps()
    row = retrieve(d, "Q_plain", "Q_plain")
    assert row["arms_skipped"] == drv.SKIPPED
    assert row["arms"]["nopin"] is None and row["arms"]["off"] is None
    assert d.router.CALLS == ["cross_reference"]


def test_m1_forced_questions_run_every_arm():
    d, _, _ = deps()
    row = retrieve(d, "Q_plain", "Q_plain", forced=True)
    assert row["arms_skipped"] is None and row["forced"] is True
    assert row["arms"]["nopin"]["ctx_sha"] == row["arms"]["off"]["ctx_sha"] == \
        row["arms"]["ctrl"]["ctx_sha"]


def test_strategy_errors_rerun_the_three_arms_on_the_same_intent():
    d, intent_client, _ = deps(anchors=ANCHOR_Q, errors=[{}, {"semantic": "Timeout"}])
    row = retrieve(d)
    assert row["arm_attempts"] == 2 and len(row["error_history"]) == 1
    assert row["error_history"][0] == {"nopin": {"semantic": "Timeout"}}
    assert len(intent_client.calls) == 1
    assert all(not row["arms"][a]["stats"]["strategy_errors"] for a in ("ctrl", "nopin", "off"))


def test_strategy_errors_after_two_reruns_are_kept_for_the_check():
    d, _, _ = deps(anchors=ANCHOR_Q, errors=[{"rerank": "x"}] * 9)
    row = retrieve(d)
    assert row["arm_attempts"] == 3 and len(row["error_history"]) == 3
    assert row["arms"]["ctrl"]["stats"]["strategy_errors"] == {"rerank": "x"}


def test_intent_failures_are_retried_and_recorded():
    d, intent_client, _ = deps(intent_replies=[RuntimeError("down"), "no json at all",
                                               '{"intent": "person", "entities": ["摩西"]}'])
    row = retrieve(d, "Q_plain", "Q_plain")
    assert row["intent"]["type"] == "person" and row["intent"]["entities"] == ["摩西"]
    assert row["intent_attempts"] == 3 and row["intent_ok"] is True
    assert len(intent_client.calls) == 3


def test_intent_that_never_parses_falls_back_like_prod_and_is_flagged():
    d, _, _ = deps(intent_replies=["a", "b", "c"])
    row = retrieve(d, "Q_plain", "Q_plain")
    assert row["intent"]["type"] == "topic" and row["intent_ok"] is False


def test_retrieve_all_writes_one_line_per_question_and_skips_done(tmp_path):
    d, _, _ = deps(intent_replies=['{"intent": "topic"}'] * 3, anchors=ANCHOR_Q)
    questions = [{"question_id": q, "question": q} for q in ("Q_a", "Q_ba", "Q_c")]
    todo = drv.select_questions(questions, ids=None, done={"Q_a"})
    assert [q["question_id"] for q in todo] == ["Q_ba", "Q_c"]
    out = io.StringIO()
    asyncio.run(drv.retrieve_all(d, todo, force={"Q_c"}, out=out))
    rows = bio.parse_lines(out.getvalue())
    assert [r["qid"] for r in rows] == ["Q_ba", "Q_c"]
    assert rows[1]["forced"] is True and rows[1]["arms_skipped"] is None
    with pytest.raises(drv.DriverError, match="unknown"):
        drv.select_questions(questions, ids=["Q_x"], done=set())


# ---------------------------------------------------------------- generate

def plan_items(row, arms=("ctrl", "nopin", "off"), rep=1):
    return [{"order": i, "qid": row["qid"], "arm": a, "rep": rep,
             "ctx_sha": row["arms"][a]["ctx_sha"]} for i, a in enumerate(arms)]


def stored(row):
    """The row as generate reads it back from retrieval.jsonl."""
    return bio.parse_lines(bio.dumps_line(row))[0]


def test_generate_checks_i7_and_hashes_the_messages():
    d, _, gen_client = deps(anchors=ANCHOR_Q, gen_replies=["答案"])
    row = stored(retrieve(d))
    item = plan_items(row, ("off",))[0]
    rec = asyncio.run(drv.generate_item(item, row, d))
    assert rec["ok"] is True and rec["answer"] == "答案" and rec["attempts"] == 1
    assert rec["ctx_sha"] == row["arms"]["off"]["ctx_sha"]
    assert rec["messages_match"] is True
    sent = gen_client.calls[0]
    assert rec["messages_sha"] == bio.messages_sha(sent["messages"])
    assert bio.context_text(row["arms"]["off"]["results"], d.build_blocks) in \
        sent["messages"][1]["content"]
    assert rec["llm_options"] == {"temperature": 0.1, "max_tokens": 10000}


def test_i7_mismatch_raises_before_any_llm_call():
    d, _, gen_client = deps(anchors=ANCHOR_Q, gen_replies=["答案"])
    row = stored(retrieve(d))
    row["arms"]["ctrl"]["results"][0]["content"] = "changed after retrieval"
    with pytest.raises(drv.I7Error):
        asyncio.run(drv.generate_item(plan_items(row, ("ctrl",))[0], row, d))
    row = stored(retrieve(d))
    with pytest.raises(drv.I7Error):
        asyncio.run(drv.generate_item({**plan_items(row, ("ctrl",))[0], "ctx_sha": "0" * 64},
                                      row, d))
    assert gen_client.calls == []


def test_generate_all_checks_every_item_before_generating(tmp_path):
    d, _, gen_client = deps(anchors=ANCHOR_Q, gen_replies=["a", "b"])
    row = stored(retrieve(d))
    items = plan_items(row, ("ctrl", "off"))
    items[1]["ctx_sha"] = "f" * 64
    with pytest.raises(drv.I7Error):
        asyncio.run(drv.generate_all(d, items, {row["qid"]: row}, done=set(), out=io.StringIO()))
    assert gen_client.calls == []


def test_failed_answers_are_retried_twice_then_written_as_they_are():
    d, _, gen_client = deps(anchors=ANCHOR_Q,
                            gen_replies=[RuntimeError("ReadTimeout"), "", "好答案",
                                         RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    row = stored(retrieve(d))
    first = asyncio.run(drv.generate_item(plan_items(row, ("ctrl",))[0], row, d))
    assert first["ok"] is True and first["attempts"] == 3 and first["answer"] == "好答案"
    assert first["failures"][0].startswith("生成回答時發生錯誤")
    second = asyncio.run(drv.generate_item(plan_items(row, ("nopin",))[0], row, d))
    assert second["ok"] is False and second["attempts"] == 3
    assert second["answer"].startswith("生成回答時發生錯誤：")
    assert len(gen_client.calls) == 6


def test_generate_all_resumes_and_writes_gen_lines():
    d, _, _ = deps(anchors=ANCHOR_Q, gen_replies=["x", "y"])
    row = stored(retrieve(d))
    items = plan_items(row)
    out = io.StringIO()
    done = {(row["qid"], "ctrl", 1)}
    asyncio.run(drv.generate_all(d, items, {row["qid"]: row}, done=done, out=out))
    rows = bio.parse_lines(out.getvalue())
    assert [(r["kind"], r["arm"]) for r in rows] == [("gen", "nopin"), ("gen", "off")]


def test_a_plan_arm_that_retrieval_skipped_raises():
    d, _, _ = deps()
    row = stored(retrieve(d, "Q_plain", "Q_plain"))
    item = {"order": 0, "qid": "Q_plain", "arm": "off", "rep": 1, "ctx_sha": "0" * 64}
    with pytest.raises(drv.DriverError, match="skipped"):
        asyncio.run(drv.generate_item(item, row, d))


# ---------------------------------------------------------------- CLI and files

def test_cli_parses_the_prereg_commands():
    a = drv.parse_args(["retrieve", "--questions", "/in/questions.json", "--ids-file",
                        "/in/batch_a.json", "--force-ids", "/in/force_ids.json",
                        "--resume", "/in/retrieval.jsonl"])
    assert a.cmd == "retrieve" and a.ids_file == Path("/in/batch_a.json")
    g = drv.parse_args(["generate", "--plan", "/in/checks/gen_plan.json", "--retrieval",
                        "/in/retrieval.jsonl", "--resume", "/in/gen.jsonl", "--retry-failed"])
    assert g.cmd == "generate" and g.retry_failed is True
    with pytest.raises(SystemExit):
        drv.parse_args(["retrieve"])


def test_retrieval_rows_refuse_duplicates(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text(bio.dumps_line({"kind": "meta"}) + bio.dumps_line({"kind": "q", "qid": "A"})
                    + bio.dumps_line({"kind": "q", "qid": "A"}), encoding="utf-8")
    with pytest.raises(drv.DriverError, match="twice"):
        drv.retrieval_rows(path)


def test_backend_files_are_the_prereg_eighteen():
    assert len(drv.BACKEND_FILES) == 18 == len(set(drv.BACKEND_FILES))
    assert all((_REPO / "backend" / f).is_file() for f in drv.BACKEND_FILES)


def test_the_context_hash_is_generator_build_contexts_string():
    d, _, _ = deps(anchors=ANCHOR_Q)
    row = retrieve(d)
    results = row["arms"]["ctrl"]["results"]
    assert row["arms"]["ctrl"]["ctx_sha"] == bio.sha256_bytes(
        d.generator._build_context(results).encode("utf-8"))
    d.generator._build_context = lambda sources: "something else"
    with pytest.raises(drv.DriverError, match="_build_context"):
        drv.prod_ctx_sha(d, results)


@pytest.mark.parametrize("exc, code", [(drv.I7Error("x"), 3), (drv.DriverError("y"), 2),
                                       (bio.BaIoError("z"), 2), (RuntimeError("w"), 2)])
def test_main_exit_codes(monkeypatch, exc, code, capsys):
    async def boom(args, out, argv):
        raise exc

    monkeypatch.setattr(drv, "_claim_stdout", lambda: io.StringIO())
    monkeypatch.setattr(drv, "_run_generate", boom)
    assert drv.main(["generate", "--plan", "p", "--retrieval", "r"]) == code
    err = capsys.readouterr().err.strip().splitlines()
    assert err[-1].startswith("ba_driver: ")


def test_main_succeeds_quietly(monkeypatch):
    out = io.StringIO()

    async def fine(args, stream, argv):
        stream.write(bio.dumps_line({"kind": "end"}))

    monkeypatch.setattr(drv, "_claim_stdout", lambda: out)
    monkeypatch.setattr(drv, "_run_retrieve", fine)
    assert drv.main(["retrieve", "--questions", "q"]) == 0
    assert bio.parse_lines(out.getvalue()) == [{"kind": "end"}]


# ---------------------------------------------------------------- container entry (fakes)

EVAL3C_RUN_META = Path("/mnt/ollama-data/bible_rag_store/reports/eval3c_20261014/full/"
                       "run_meta.json")
SYNTH_FP = {"embedder": {"tokenizer_sha": "e" * 64, "unk_count": 3},
            "reranker": {"tokenizer_sha": "r" * 64, "unk_count": 2}}
SETTINGS = dict(ck.EXPECT_SETTINGS, strict_build_check=True, default_top_k=5,
                rag_event_registry_slots=1, llm_provider="ollama",
                ollama_base_url="http://ollama:11434", semantic_search_top_k=20)
EXP_META = {"image_id": ck.IMAGE_PREFIX + "e48b", "refusal_v2_sha256": ck.REFUSAL_SHA_PREFIX + "x",
            "ollama_digests": {ck.GEN_MODEL: "d", ck.JUDGE_MODEL: "j"}}


def eval3c_encoder():
    """eval3c full's run_meta encoder_fingerprint (the /health shape) or a stand-in."""
    if EVAL3C_RUN_META.exists():
        return json.loads(EVAL3C_RUN_META.read_text(encoding="utf-8"))["encoder_fingerprint"]
    return SYNTH_FP


def _return_keys(rel, func):
    tree = ast.parse((_REPO / "backend" / rel).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == func)
    return fn


def test_load_models_keys_are_renamed_to_the_health_shape():
    load_models = _return_keys("main.py", "load_models")
    ret = next(n for n in ast.walk(load_models) if isinstance(n, ast.Return))
    assert {k.value for k in ret.value.keys} == set(drv.LOAD_MODELS_TO_HEALTH) == \
        {"bge_m3", "reranker"}
    health = _return_keys("routers/health.py", "health_check")
    encoder = next(kw.value for n in ast.walk(health) if isinstance(n, ast.Call)
                   for kw in n.keywords if kw.arg == "encoder")
    assert {k.value for k in encoder.keys} == set(drv.LOAD_MODELS_TO_HEALTH.values())
    if EVAL3C_RUN_META.exists():
        assert set(eval3c_encoder()) == {"embedder", "reranker"}
    with pytest.raises(drv.DriverError, match="load_models"):
        drv.health_encoder({"embedder": {}, "reranker": {}})


class FakeLLM:
    provider_name = "ollama"

    def __init__(self, ok):
        self.ok = ok

    async def health_check(self):
        return self.ok


@pytest.fixture
def backend(monkeypatch):
    """Fake backend modules for the driver's container imports; .state steers them."""
    enc = eval3c_encoder()
    state = types.SimpleNamespace(llm_ok=True, mismatches=(), load_calls=0, stopped=0,
                                  fingerprints={"bge_m3": enc["embedder"],
                                                "reranker": enc["reranker"]})
    d, _, _ = deps(intent_replies=['{"intent": "cross_reference"}'] * 9, anchors=ANCHOR_Q,
                   gen_replies=["答案"] * 9)

    def load_models():
        state.load_calls += 1
        return dict(state.fingerprints)

    async def run(fingerprints):
        assert fingerprints == state.fingerprints          # startup gets load_models' own dict
        return types.SimpleNamespace(ok=not state.mismatches, mismatches=state.mismatches,
                                     to_json=lambda: {"ok": not state.mismatches})

    async def stop():
        state.stopped += 1

    mods = {"main": types.SimpleNamespace(load_models=load_models),
            "torch": types.SimpleNamespace(get_num_threads=lambda: 24),
            "config": types.SimpleNamespace(settings=types.SimpleNamespace(**SETTINGS)),
            "serving": types.SimpleNamespace(
                context=types.SimpleNamespace(active=lambda: types.SimpleNamespace(
                    build=types.SimpleNamespace(build_id=ck.BUILD_ID))),
                startup=types.SimpleNamespace(run=run, stop=stop)),
            "utils": types.SimpleNamespace(embedder=types.SimpleNamespace(get_device=lambda: "cpu"),
                                           generator=d.generator, intent_classifier=d.ic),
            "utils.llm": types.SimpleNamespace(get_llm_client=lambda: FakeLLM(state.llm_ok)),
            "utils.retrieval": types.SimpleNamespace(router=d.router, routes=d.routes)}
    for name, mod in mods.items():
        module = types.ModuleType(name)
        module.__dict__.update(vars(mod))
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(drv, "BACKEND_ROOT", _REPO / "backend")
    monkeypatch.setenv("RAG_ENV", "prod")
    state.deps = d
    return state


def _main(monkeypatch, argv):
    out = io.StringIO()
    monkeypatch.setattr(drv, "_claim_stdout", lambda: out)
    return drv.main(argv), bio.parse_lines(out.getvalue())


def _i0(metas, mode="retrieve"):
    return ck.check_i0(metas, backend_expected=drv.file_shas(_REPO / "backend", ck.BACKEND_FILES),
                       exp_expected=drv.file_shas(_EXP, sorted(p.name for p in _EXP.glob("*.py"))),
                       encoder_expected=eval3c_encoder(), exp_meta=EXP_META, mode=mode)


def _questions(tmp_path, qids=("Q_ba", "Q_c")):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps([{"question_id": q, "question": q} for q in qids]))
    return path


def test_retrieve_meta_passes_i0_against_eval3c_run_meta(backend, monkeypatch, tmp_path):
    code, lines = _main(monkeypatch, ["retrieve", "--questions", str(_questions(tmp_path))])
    assert code == 0 and [x["kind"] for x in lines] == ["meta", "q", "q", "end"]
    meta = lines[0]
    assert set(meta["encoder_fingerprint"]) == {"embedder", "reranker"}
    assert meta["load_models_fingerprint"] == backend.fingerprints
    assert _i0([meta]) == []
    assert backend.stopped == 1


def test_a_failed_llm_health_check_writes_nothing_and_a_resume_passes_i0(
        backend, monkeypatch, tmp_path):
    questions = _questions(tmp_path)
    backend.llm_ok = False
    code, lines = _main(monkeypatch, ["retrieve", "--questions", str(questions)])
    assert code == 2 and lines == [] and backend.stopped == 1
    backend.llm_ok = True
    code, lines = _main(monkeypatch, ["retrieve", "--questions", str(questions)])
    assert code == 0 and _i0([x for x in lines if x["kind"] == "meta"]) == []


def test_a_failed_handshake_writes_nothing(backend, monkeypatch, tmp_path):
    backend.mismatches = ("postgres: no build_info row",)
    code, lines = _main(monkeypatch, ["retrieve", "--questions", str(_questions(tmp_path))])
    assert code == 2 and lines == []


def test_retrieve_with_nothing_to_do_loads_nothing_and_writes_nothing(
        backend, monkeypatch, tmp_path):
    resume = tmp_path / "retrieval.jsonl"
    resume.write_text("".join(bio.dumps_line({"kind": "q", "qid": q}) for q in ("Q_ba", "Q_c")))
    code, lines = _main(monkeypatch, ["retrieve", "--questions", str(_questions(tmp_path)),
                                      "--resume", str(resume)])
    assert code == 0 and lines == [] and backend.load_calls == 0 and backend.stopped == 0


def _generate_inputs(backend, tmp_path):
    row = retrieve(backend.deps)
    retrieval = tmp_path / "retrieval.jsonl"
    retrieval.write_text(bio.dumps_line(row), encoding="utf-8")
    plan = tmp_path / "gen_plan.json"
    plan.write_text(json.dumps({"items": plan_items(stored(row))}))
    return ["generate", "--plan", str(plan), "--retrieval", str(retrieval)]


def test_generate_meta_passes_i0_and_a_failed_health_check_writes_nothing(
        backend, monkeypatch, tmp_path):
    argv = _generate_inputs(backend, tmp_path)
    backend.llm_ok = False
    assert _main(monkeypatch, argv) == (2, [])
    backend.llm_ok = True
    code, lines = _main(monkeypatch, argv)
    assert code == 0 and [x["kind"] for x in lines] == ["meta", "gen", "gen", "gen", "end"]
    assert _i0([lines[0]], mode="generate") == []


def test_generate_with_nothing_to_do_still_checks_i7_and_writes_nothing(
        backend, monkeypatch, tmp_path):
    argv = _generate_inputs(backend, tmp_path)
    plan = json.loads(Path(argv[2]).read_text())["items"]
    resume = tmp_path / "gen.jsonl"
    resume.write_text("".join(bio.dumps_line({"kind": "gen", "qid": i["qid"], "arm": i["arm"],
                                              "rep": i["rep"], "ok": True}) for i in plan))
    backend.llm_ok = False                                  # never asked: nothing to generate
    assert _main(monkeypatch, [*argv, "--resume", str(resume)]) == (0, [])
    plan[0]["ctx_sha"] = "0" * 64
    Path(argv[2]).write_text(json.dumps({"items": plan}))
    assert _main(monkeypatch, [*argv, "--resume", str(resume)]) == (3, [])
