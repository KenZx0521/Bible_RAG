"""Pins, loaders and the pure selection rules of the QD experiment (plan.md §1–§4).

Imported unmodified (sha-checked, never written to):
* the GD experiment (evaluation/experiments/2026-10-14_graph_gd): store layers, dense index,
  bip graph, PPR, name linker, f(q) and unit statistics;
* new82_ans it_host.py (store reports/kg_effect_eval_20261014/new82_ans): the NEW82
  question texts, C5 from the frozen GD lists / scores, the iterq decomposer prompt and
  helpers, the container runner conventions.

Nothing here reads gold. The ORACLE names and the evaluation read it in their own processes.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
GD_DIR = HERE.parent / "2026-10-14_graph_gd"
STORE = Path("/mnt/ollama-data/bible_rag_store")
NEW82_ANS = STORE / "reports" / "kg_effect_eval_20261014" / "new82_ans"
OUT = STORE / "reports" / "graph_qd_20261018"
IT_HOST_SHA256 = "9df775349c5e404791892f1455f438e0e27c9162f2c200306f59a470963aaf84"


class QdError(RuntimeError):
    pass


def _import_pinned(name: str, directory: Path, sha: str | None):
    path = directory / f"{name}.py"
    if sha is not None:
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != sha:
            raise QdError(f"{path}: sha256 {got} != pinned {sha}")
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return __import__(name)


gd = _import_pinned("gd_common", GD_DIR, None)       # GD checks its own layer pins on load
gd_arms = _import_pinned("arms", GD_DIR, None)
H = _import_pinned("it_host", NEW82_ANS, IT_HOST_SHA256)

GD_APPENDIX_A = GD_DIR / "appendix_a_sha256.txt"
GD_IMPORTED = ("gd_common.py", "_gd_store.py", "_gd_sets.py", "_gd_pool.py", "_gd_gtv2.py",
               "arms.py", "_gd_lex.py", "_eval_metrics.py", "_eval_stats.py", "_eval_report.py",
               "_eval_inputs.py", "_e3_build.py", "_e3_run.py", "score.py", "_score_io.py",
               "rerank_stdin.py", "encode_stdin.py")

PROMPT_SHA256 = H.PROMPT_SHA256
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma4:e4b-it-q8_0"
OLLAMA_DIGEST = "9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923"
LLM_LABEL = f"Ollama ({OLLAMA_MODEL})"
LLM_MAX_TOKENS = 10000

N_C5 = 5
N_POOL = 20                 # QD pool: first 20 of D(s) outside C5 (= IT-D pool)
N_DEEP = 50                 # DEEP pool: D(question)[0:50] minus C5
N_NAMES = 5
N_RANKED = 30              # passages of a ranking the names come from (D30; PPR top 30)
N_REPS = 3
HUB_OCC = 300               # kg0 body_occurrences > 300 is a hub (14 names)
MIN_NAME_LEN = 2
NAMES_ANCHOR = "{context}\n\n---\n"
NAMES_LINE = "可能相關名稱：{names}"
NAMES_SEP = "、"
ARMS = ("DEEP", "QD", "QD+G", "QD+N", "QD+ORACLE")
LLM_ARMS = ("QD", "QD+G", "QD+N", "QD+ORACLE")
NAMED_ARMS = ("QD+G", "QD+N", "QD+ORACLE")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_gd_files() -> dict[str, str]:
    """sha256 of every imported GD file, each equal to its appendix A pin."""
    pins = {}
    for line in GD_APPENDIX_A.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            sha, name = line.split(maxsplit=1)
            pins[name.strip()] = sha
    out = {}
    for name in GD_IMPORTED:
        got = gd.file_sha256(GD_DIR / name)
        if pins.get(name) != got:
            raise QdError(f"GD {name}: sha256 {got} is not its appendix A pin {pins.get(name)}")
        out[name] = got
    return out


# ------------------------------------------------------------------ prompt with a names line

def names_template(user_template: str) -> str:
    """The frozen user template with 「可能相關名稱：{names}」 between the context and `---`."""
    if user_template.count(NAMES_ANCHOR) != 1:
        raise QdError("the user template must hold '{context}\\n\\n---\\n' exactly once")
    return user_template.replace(NAMES_ANCHOR, "{context}\n\n" + NAMES_LINE + "\n\n---\n")


def user_template_for(user_template: str, names: Sequence[str]) -> str:
    """No names: the frozen template itself; else the names line filled in."""
    if not names:
        return user_template
    return names_template(user_template).replace("{names}", NAMES_SEP.join(names))


# ------------------------------------------------------------------ graph and name pickers

def names_by_passage(graph) -> dict[str, frozenset[str]]:
    acc: dict[str, set[str]] = {p: set() for p in graph.passages}
    for s, d in zip(graph.src.tolist(), graph.dst.tolist()):
        if s < graph.n_pass:
            acc[graph.passages[s]].add(graph.names[d - graph.n_pass])
    return {p: frozenset(v) for p, v in acc.items()}


def context_exclusions(graph, c5: Sequence[str], question_names: Iterable[str]) -> frozenset[str]:
    """Names the decomposer already has: the question's names and every C5 body name."""
    by = names_by_passage(graph)
    out = set(question_names)
    for p in c5:
        out |= by[p]
    return frozenset(out)


def is_eligible(name: str, kg0_occ: Mapping[str, int], exclude: frozenset[str]) -> bool:
    return (name in kg0_occ and len(name) >= MIN_NAME_LEN and kg0_occ[name] <= HUB_OCC
            and name not in exclude)


def c5_seeds(graph, c5: Sequence[str]) -> dict[int, float]:
    return {graph.row[p]: 1.0 / (i + 1) for i, p in enumerate(c5)}


def ppr_ranking(graph, c5: Sequence[str]) -> tuple[str, ...]:
    """Passages by GD §3 PPR order (arms.ppr, α 0.5, 40 steps) seeded with C5 at 1/rank."""
    order = gd_arms.ppr_order(gd_arms.ppr(graph, c5_seeds(graph, c5)))
    return tuple(graph.passages[i] for i in order)


def ranked_names(graph, ranking: Sequence[str], c5: Sequence[str], kg0_occ: Mapping[str, int],
                 exclude: frozenset[str], n: int = N_NAMES) -> tuple[str, ...]:
    """ln(N/df)·Σ 1/(rank+1) over the first N_RANKED passages of `ranking` outside C5
    (rank 0-based in `ranking`, df = bip degree, N = passages); eligible names by
    (−round(score, 12), name)."""
    by, c5set = names_by_passage(graph), set(c5)
    weight: dict[str, float] = defaultdict(float)
    for rank, p in enumerate(ranking[:N_RANKED]):
        if p not in c5set:
            for name in by[p]:
                weight[name] += 1.0 / (rank + 1)
    keyed = []
    for name, w in weight.items():
        if is_eligible(name, kg0_occ, exclude):
            score = math.log(graph.n_pass / graph.deg[graph.name_node[name]]) * w
            if score > 0:
                keyed.append((-round(score, gd_arms.PPR_ROUND), name))
    return tuple(name for _, name in sorted(keyed)[:n])


def graph_names(graph, c5: Sequence[str], kg0_occ: Mapping[str, int], exclude: frozenset[str],
                n: int = N_NAMES) -> tuple[str, ...]:
    """QD+G: names of the PPR ranking around C5 (C5 → names → passages: two hops and more),
    put after C5 like QD+N's."""
    return ranked_names(graph, c5_first(c5, ppr_ranking(graph, c5)), c5, kg0_occ, exclude, n)


def eligible_names(names: Sequence[str], kg0_occ: Mapping[str, int], exclude: frozenset[str],
                   n: int = N_NAMES) -> tuple[str, ...]:
    """QD+ORACLE: the gold bridge names that QD+G / QD+N could output, in link order."""
    return tuple(x for x in dict.fromkeys(names) if is_eligible(x, kg0_occ, exclude))[:n]


def c5_first(c5: Sequence[str], ranking: Sequence[str]) -> tuple[str, ...]:
    """C5, then `ranking` without C5: the non-C5 passages take ranks 5.. as in the PPR ranking
    (C5 holds PPR ranks 0–4 for every NEW82 question), so both arms weigh 1/6 … 1/30."""
    c5set = set(c5)
    return tuple(c5) + tuple(p for p in ranking if p not in c5set)


def dense_names(graph, d30: Sequence[str], c5: Sequence[str], kg0_occ: Mapping[str, int],
                exclude: frozenset[str], n: int = N_NAMES) -> tuple[str, ...]:
    """QD+N: names of the question's dense ranking D30 put after C5 (a one-hop lookup)."""
    return ranked_names(graph, c5_first(c5, d30), c5, kg0_occ, exclude, n)


# ------------------------------------------------------------------ pools and the appended passage

def pool_of(rank: Sequence[str], c5: Sequence[str], n: int = N_POOL) -> tuple[str, ...]:
    return tuple(gd_arms.take_extra(rank, frozenset(c5), n))


def deep_pool(rank: Sequence[str], c5: Sequence[str]) -> tuple[str, ...]:
    c5set = set(c5)
    return tuple(p for p in rank[:N_DEEP] if p not in c5set)


def pick(pool: Sequence[str], scores: Mapping[str, float]) -> str:
    return min(pool, key=lambda p: (-scores[p], p))


# ------------------------------------------------------------------ decompositions and the gate

def dec_is_result(rec: Mapping) -> bool:
    """A fallback caused by an Ollama exception is infrastructure, not a decomposition."""
    return not (rec["fallback"] and any(a.get("error") for a in rec["attempts"]))


def gate_pass(cmp: Mapping) -> bool:
    """plan.md §4: unit W ≥ 2L, W − L ≥ 4 and mean unit difference > 0."""
    w, l = cmp["unit_W"], cmp["unit_L"]
    return w >= 2 * l and w - l >= 4 and cmp["mean_unit_diff"] > 0


# ------------------------------------------------------------------ loaders (no gold)

def load_kg0_occurrences() -> dict[str, int]:
    rows = gd._gd_store._jsonl(gd._gd_store._layer_bytes(gd.LAYERS_ROOT, "kg0", "names.jsonl"))
    return {r["norm_key"]: int(r["body_occurrences"]) for r in rows}


@dataclass(frozen=True)
class Step1Inputs:
    questions: dict[str, str]
    lists: dict
    c5: dict[str, tuple[str, ...]]
    d30: dict[str, tuple[str, ...]]
    ctx: object                      # arms.ArmContext (dense, graph, linker, bm25)
    prompt: dict


def load_step1_inputs() -> Step1Inputs:
    questions = H.load_questions()
    lists = H.load_lists()
    c_scores = H.load_c_scores(lists, list(questions))
    c5 = {q: tuple(H.c_top(lists, c_scores, q, N_C5)) for q in questions}
    d30 = {q: tuple(lists[q][gd.D_KEY]) for q in questions}
    ctx = gd_arms.load_context()
    H.assert_no_gold_loaded()
    return Step1Inputs(questions, lists, c5, d30, ctx, H.load_prompt())


def write_frozen(path: Path, text: str) -> str:
    """Write once; an existing file must already hold exactly `text`."""
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise QdError(f"{path} exists with different content (frozen; not overwritten)")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".partial")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    return sha256_text(text)


def dumps(doc) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
