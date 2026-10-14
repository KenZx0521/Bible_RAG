"""§3 arms of the GD experiment: dense ranking D(q), the bip name graph, PPR and each arm's extra.

prereg.md §3 in this directory is the spec (the archived probe scripts are only references;
nothing here imports them or reads /tmp). The lexical side (G name linking, L / LEXPRF BM25)
lives in _gd_lex.py and is re-exported here. For every question of one set:

* D(q): exact float64 cosine of the question vector against the emb layer's vectors.npy,
  passage score = max over the passage's records, argsort(-best, stable) over sorted(pid).
  R20 (the §4 D5≈ input): the passages of the top-20 records by argsort(-cosine, stable),
  first appearance order; evaluate.py takes its top 5 by (−reranker score, pid).
* each arm's extra (<= 10 passages outside D[0:20], no padding when fewer exist):
  C = D[20:30]; GD = PPR on the bip graph seeded with D[0:10] at 1/rank; GD_DEGNORM = GD's
  r / max(deg, 1); G = GD seeds and linked question names at 0.5 / 0.5; L = CJK-bigram BM25
  over all passages; LEXPRF = BM25 with the q(t) feedback query, positive scores only.

CLI:  arms.py --set new82 --vectors <encode jsonl> --out <lists.json>
writes {"meta": {...}, "lists": {qid: {"D30": [30 pid], "R20": [...], "C": [...], "GD": [...],
...}}} (shape: gd_common / _gd_pool.py); the pool of an arm is D30[:20] + its extra. Only
sets whose prereg appendices are filled and acceptance files passed run (gd.assert_set_allowed).
--overwrite replaces an existing --out (accept_a.py regenerates the NEW82 lists with it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Container, Iterable, Mapping, Sequence

import numpy as np

import gd_common as gd
from _gd_lex import (BM25_B, BM25_K1, LEXPRF_MIX, LEXPRF_TERMS, MIN_SURFACE,  # noqa: F401
                     Bm25Index, NameLinker, bigrams, book_masks, build_bm25, build_linker, by_score,
                     lexprf_query, passage_bigrams, surf_table)

N_DENSE, N_BASE, N_EXTRA, N_SEEDS = gd.N_DENSE, gd.N_BASE, gd.N_EXTRA, gd.N_SEEDS
N_D5_RECORDS = gd.N_D5_RECORDS
PPR_ALPHA = 0.5
PPR_ITERS = 40
PPR_ROUND = 12              # sort key -round(r, 12)
PPR_MIN = 1e-12             # keep r > 1e-12
NAME_MASS = 0.5             # G: share of the name seeds (dense seeds get the rest)
ARMS = gd.ARMS
SET_NAMES = ("new82", "old31", "ho")
SCRIPT_FILES = tuple(gd.EXP_DIR / n for n in ("arms.py", "_gd_lex.py"))


# ------------------------------------------------------------------ dense D(q)

@dataclass(frozen=True)
class DenseIndex:
    matrix: np.ndarray          # (records, dim) float64
    row_pidx: np.ndarray        # record row -> index into pids
    pids: tuple[str, ...]       # sorted passage ids

    def search(self, vec: np.ndarray) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(D, R20): all passages by argsort(-best, stable) over sorted(pid), best = max record
        cosine; and the passages of the top-20 records by argsort(-cosine, stable), deduplicated."""
        sims = self.matrix @ np.asarray(vec, dtype=np.float64)
        best = np.full(len(self.pids), -np.inf)
        np.maximum.at(best, self.row_pidx, sims)
        rank = tuple(self.pids[i] for i in np.argsort(-best, kind="stable"))
        top = np.argsort(-sims, kind="stable")[:N_D5_RECORDS]
        return rank, tuple(dict.fromkeys(self.pids[self.row_pidx[i]] for i in top))

    def ranking(self, vec: np.ndarray) -> tuple[str, ...]:
        return self.search(vec)[0]


def build_dense(matrix: np.ndarray, row_pids: Sequence[str]) -> DenseIndex:
    if len(row_pids) != matrix.shape[0]:
        raise gd.GdError(f"{len(row_pids)} record passages for {matrix.shape[0]} vector rows")
    pids = tuple(sorted(set(row_pids)))
    index = {p: i for i, p in enumerate(pids)}
    mat = np.array(matrix, dtype=np.float64)                # one float64 copy, never the caller's
    rows = np.array([index[p] for p in row_pids], dtype=np.int64)
    mat.flags.writeable = rows.flags.writeable = False
    return DenseIndex(mat, rows, pids)


# ------------------------------------------------------------------ bip graph and PPR

@dataclass(frozen=True)
class BipGraph:
    passages: tuple[str, ...]   # nodes 0..P-1 in passages.jsonl row order (the 列序)
    names: tuple[str, ...]      # nodes P.. as sorted norm_keys
    src: np.ndarray             # both directions of every edge, sorted by (src, dst)
    dst: np.ndarray
    deg: np.ndarray             # float64 degree per node
    row: Mapping[str, int]
    name_node: Mapping[str, int]

    @property
    def n_pass(self) -> int:
        return len(self.passages)

    @property
    def n_nodes(self) -> int:
        return len(self.passages) + len(self.names)

    @property
    def n_edges(self) -> int:
        return len(self.src) // 2


def build_bip(passages: Sequence[str], edges: Iterable[tuple[str, str]]) -> BipGraph:
    """Unweighted passage–name graph from (passage_id, norm_key) pairs, edge list sorted."""
    row = {p: i for i, p in enumerate(passages)}
    edges = set(edges)
    stray = sorted({p for p, _ in edges} - set(row))
    if stray:
        raise gd.GdError(f"bip edges on passages outside the passage list: {stray[:5]}")
    names = tuple(sorted({n for _, n in edges}))
    name_node = {n: len(passages) + i for i, n in enumerate(names)}
    und = np.array(sorted((row[p], name_node[n]) for p, n in edges), dtype=np.int64).reshape(-1, 2)
    src = np.concatenate([und[:, 0], und[:, 1]])
    dst = np.concatenate([und[:, 1], und[:, 0]])
    order = np.lexsort((dst, src))
    src, dst = src[order], dst[order]
    deg = np.bincount(src, minlength=len(passages) + len(names)).astype(np.float64)
    for arr in (src, dst, deg):
        arr.flags.writeable = False
    return BipGraph(tuple(passages), names, src, dst, deg, MappingProxyType(row),
                    MappingProxyType(name_node))


def ppr(graph: BipGraph, seeds: Mapping[int, float], iters: int = PPR_ITERS,
        alpha: float = PPR_ALPHA) -> np.ndarray:
    """Passage scores of r <- a*e + (1-a)*(P^T r + (sum of dangling r)*e), r0 = e, sum(e) = 1."""
    e = np.zeros(graph.n_nodes)
    for node, weight in seeds.items():
        e[node] += weight
    total = e.sum()
    if not total > 0:
        raise gd.GdError("PPR needs seeds with positive mass")
    e /= total
    step = 1.0 / graph.deg[graph.src]
    dangling = graph.deg == 0
    r = e.copy()
    for _ in range(iters):
        spread = np.bincount(graph.dst, weights=r[graph.src] * step, minlength=graph.n_nodes)
        r = alpha * e + (1 - alpha) * (spread + r[dangling].sum() * e)
    return r[:graph.n_pass]


def ppr_order(scores: np.ndarray) -> list[int]:
    """Passage rows with score > 1e-12, by (-round(score, 12), row)."""
    keyed = sorted((-round(s, PPR_ROUND), i) for i, s in enumerate(scores.tolist()) if s > PPR_MIN)
    return [i for _, i in keyed]


def scaled(weights: Mapping, mass: float) -> dict:
    """Weights rescaled to sum to `mass` (analyze.py norm(): v * mass / total)."""
    total = sum(weights.values())
    if not total > 0:
        raise gd.GdError("cannot rescale weights with no positive mass")
    return {k: v * mass / total for k, v in weights.items()}


def take_extra(order: Iterable[str], exclude: Container[str], n: int = N_EXTRA) -> list[str]:
    """First `n` distinct passages of `order` outside `exclude`; fewer is returned as is."""
    out: list[str] = []
    for pid in order:
        if pid not in exclude and pid not in out:
            out.append(pid)
            if len(out) == n:
                break
    return out


# ------------------------------------------------------------------ arms per question

@dataclass(frozen=True)
class ArmContext:
    dense: DenseIndex
    graph: BipGraph
    linker: NameLinker
    bm25: Bm25Index

    def question_names(self, question: str) -> tuple[str, ...]:
        return tuple(n for n in self.linker.link(question) if n in self.graph.name_node)

    def lists(self, question: str, vec: np.ndarray) -> dict[str, list[str]]:
        """D30, R20 and the extra of every arm for one question."""
        rank, r20 = self.dense.search(vec)
        base, seeds = set(rank[:N_BASE]), rank[:N_SEEDS]
        g, rows = self.graph, [self.graph.row[p] for p in seeds]
        dense_w = {r: 1.0 / (i + 1) for i, r in enumerate(rows)}
        r_gd = ppr(g, scaled(dense_w, 1.0))
        out = {gd.D_KEY: list(rank[:N_DENSE]), gd.R20_KEY: list(r20), "C": list(rank[N_BASE:N_DENSE]),
               "GD": take_extra((g.passages[i] for i in ppr_order(r_gd)), base),
               "GD_DEGNORM": take_extra((g.passages[i] for i in
                                         ppr_order(r_gd / np.maximum(g.deg[:g.n_pass], 1.0))), base)}
        names = {g.name_node[n]: 1.0 / g.deg[g.name_node[n]] for n in self.question_names(question)}
        if names:
            r_g = ppr(g, {**scaled(dense_w, 1 - NAME_MASS), **scaled(names, NAME_MASS)})
            out["G"] = take_extra((g.passages[i] for i in ppr_order(r_g)), base)
        else:
            out["G"] = list(out["GD"])
        bm = self.bm25
        s_l = bm.scores(dict.fromkeys(bigrams(question), 1.0))
        out["L"] = take_extra(by_score(bm, s_l, range(len(bm.pids))), base)
        s_x = bm.scores(lexprf_query(bm, question, [bm.index_of[p] for p in seeds]))
        out["LEXPRF"] = take_extra(by_score(bm, s_x, (i for i, s in s_x.items() if s > 0)), base)
        return out


def checked_lists(ctx: ArmContext, questions: Sequence[gd.Question],
                  vecs: Mapping[str, np.ndarray]) -> dict[str, dict[str, list[str]]]:
    """Every question's lists, each checked against the shared §3 shape (gd.check_entry)."""
    lists = {q.qid: ctx.lists(q.question, vecs[q.qid]) for q in questions}
    for qid, entry in lists.items():
        gd.check_entry(qid, entry)
    return lists


def load_context(root: Path = gd.LAYERS_ROOT) -> ArmContext:
    """Every §3 structure from the pinned store layers (gd_common checks the pins)."""
    passages = gd.load_passages(root)
    emb, vindex = gd.load_emb(root), gd.load_verse_index(root)
    edges = {(vindex.passage_of[s.container_id], s.norm_key) for s in gd.load_body_spans(root)}
    pids = [p.passage_id for p in passages]
    return ArmContext(build_dense(emb.matrix, emb.row_pids), build_bip(pids, edges),
                      build_linker(gd.load_book_names(root), gd.load_kg0_names(root),
                                   gd.load_query_aliases(root)),
                      build_bm25(pids, [p.content for p in passages]))


# ------------------------------------------------------------------ inputs, outputs, CLI

def load_query_vectors(path: Path, qids: Sequence[str]) -> tuple[dict[str, np.ndarray], dict]:
    """Encode jsonl: a container meta line, then {"type":"q","sid","vec_b64"}; sid is the qid
    (score.py encode) or '<qid>|<kind>' (PN/encode_out.jsonl), where only kind 'Q' is the question."""
    lines = [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]
    if not lines:
        raise gd.IntegrityError(f"{path}: empty vector file")
    meta = lines[0]
    gd.verify_container_meta(meta, "embedder")
    vecs: dict[str, np.ndarray] = {}
    for row in lines[1:]:
        if row.get("type") != "q":
            raise gd.IntegrityError(f"{path}: unexpected line type {row.get('type')!r}")
        qid, _, kind = row["sid"].partition("|")
        if kind not in ("", "Q"):
            continue
        if qid in vecs:
            raise gd.IntegrityError(f"{path}: two question vectors for {qid}")
        vecs[qid] = gd.decode_vector_b64(row["vec_b64"], f"{path}: {qid}")
    if set(vecs) != set(qids):
        raise gd.IntegrityError(f"{path}: question vectors {len(vecs)} do not match the set "
                                f"(missing {sorted(set(qids) - set(vecs))[:5]}, "
                                f"extra {sorted(set(vecs) - set(qids))[:5]})")
    return vecs, meta


lists_sha256 = gd.lists_sha256          # content hash of the lists part (score.py / evaluate.py check it)


def pool_sizes(lists: Mapping[str, Mapping[str, list[str]]]) -> dict[str, dict[str, int]]:
    return {qid: {arm: N_BASE + len(arms[arm]) for arm in ARMS} for qid, arms in lists.items()}


def run_meta(qs: gd.QuestionSet, ctx: ArmContext, vectors: Path, vec_meta: dict, lists: dict,
             names: dict, elapsed: float) -> dict:
    sizes = pool_sizes(lists)
    return gd.collect_meta(
        {**{p.name: p for p in SCRIPT_FILES}, "query_vectors": vectors},
        set=qs.name, n_questions=len(qs.questions), ids_sha256=qs.ids_sha256,
        question_sources=dict(qs.sources), query_vectors_meta=vec_meta,
        params={"n_dense": N_DENSE, "n_base": N_BASE, "n_extra": N_EXTRA, "n_seeds": N_SEEDS,
                "ppr_alpha": PPR_ALPHA, "ppr_iters": PPR_ITERS, "ppr_round": PPR_ROUND,
                "ppr_min": PPR_MIN, "name_mass": NAME_MASS, "n_d5_records": N_D5_RECORDS, "bm25_k1": BM25_K1, "bm25_b": BM25_B,
                "lexprf_terms": LEXPRF_TERMS, "lexprf_mix": LEXPRF_MIX, "min_surface": MIN_SURFACE},
        graph={"passages": ctx.graph.n_pass, "name_nodes": len(ctx.graph.names),
               "edges": ctx.graph.n_edges,
               "dangling_passages": int((ctx.graph.deg[:ctx.graph.n_pass] == 0).sum()),
               "dense_records": int(ctx.dense.matrix.shape[0])},
        pool_size=sizes,
        pool_lt30={arm: sorted(q for q, s in sizes.items() if s[arm] < N_DENSE) for arm in ARMS},
        g_question_names=names, lists_sha256=lists_sha256(lists), elapsed_s=round(elapsed, 2))


def write_json(path: Path, doc: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".partial")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, choices=SET_NAMES)
    ap.add_argument("--vectors", required=True, type=Path, help="encode jsonl (meta line + q lines)")
    ap.add_argument("--out", required=True, type=Path, help="lists.json to write")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    gd.assert_set_allowed(args.set)                    # before reading or computing anything
    if args.out.exists() and not args.overwrite:
        raise gd.GdError(f"{args.out} exists; pass --overwrite to replace it")
    t0 = time.perf_counter()
    qs = gd.load_question_set(args.set)
    vecs, vec_meta = load_query_vectors(args.vectors, qs.ids)
    ctx = load_context()
    lists = checked_lists(ctx, qs.questions, vecs)
    names = {q.qid: list(ctx.question_names(q.question)) for q in qs.questions}
    meta = run_meta(qs, ctx, args.vectors.resolve(), vec_meta, lists, names,
                    time.perf_counter() - t0)
    write_json(args.out, {"meta": meta, "lists": lists})
    print(f"{args.set}: {len(lists)} questions -> {args.out} (lists sha256 {meta['lists_sha256'][:12]}, "
          f"{meta['elapsed_s']} s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gd.GdError as err:
        print(f"arms.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
