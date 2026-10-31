"""Intent parity: vLLM runs (this harness) vs Ollama runs (step2 graph collections, same classifier code).

Agreement = same final intent type; entity overlap = Jaccard of entity sets. Within-provider
pairs give the noise floor; cross-provider pairs are compared against it.
"""
import itertools
import json
import random
from pathlib import Path

P = Path("/mnt/ollama-data/bible_rag_store/reports/vllm_switch_20261031")
STEP2 = Path("/mnt/ollama-data/bible_rag_store/reports/step2_20261029")


def load_vllm(name):
    rows = [json.loads(l) for l in (P / f"{name}.jsonl").read_text().splitlines() if l.strip()]
    return {r["qid"]: (r["type"], frozenset(r["entities"])) for r in rows}


def load_ollama(run):
    d = json.loads((STEP2 / run / "raw_responses.json").read_text())
    return {x["question_id"]: (x["intent"]["type"], frozenset(x["intent"].get("entities") or []))
            for x in d if x.get("intent")}


def jacc(a, b):
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def boot_ci(xs, n=2000, seed=0):
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def pair(a, b):
    qids = sorted(set(a) & set(b))
    agree = [float(a[q][0] == b[q][0]) for q in qids]
    ent = [jacc(a[q][1], b[q][1]) for q in qids]
    return qids, agree, ent


def main():
    runs = {"vllm_A": load_vllm("int_vllm_A"), "vllm_B": load_vllm("int_vllm_B")}
    # page2_graph is left out: its 495 intents equal p20_graph's (same collection)
    for r in ("ret_r7_graph", "p20_graph"):
        runs[f"ollama_{r}"] = load_ollama(r)
    for k, v in runs.items():
        print(f"{k}: {len(v)} questions")
    groups = {"vllm×vllm": [], "ollama×ollama": [], "vllm×ollama": []}
    for x, y in itertools.combinations(runs, 2):
        px, py = x.split("_")[0], y.split("_")[0]
        key = "vllm×vllm" if px == py == "vllm" else "ollama×ollama" if px == py == "ollama" else "vllm×ollama"
        qids, agree, ent = pair(runs[x], runs[y])
        groups[key].append((x, y, qids, agree, ent))
        print(f"  {x:22s} vs {y:22s} n={len(qids)} type_agree={sum(agree)/len(agree):.3f} "
              f"entity_jaccard={sum(ent)/len(ent):.3f}")
    print()
    for key, pairs in groups.items():
        agree = [a for *_, ag, _ in pairs for a in ag]
        ent = [e for *_, en in pairs for e in en]
        lo, hi = boot_ci(agree)
        print(f"{key:14s} pairs={len(pairs)} type_agree={sum(agree)/len(agree):.3f} "
              f"[{lo:.3f},{hi:.3f}] entity_jaccard={sum(ent)/len(ent):.3f}")
    # type distribution per provider
    from collections import Counter
    print()
    for k, v in runs.items():
        c = Counter(t for t, _ in v.values())
        print(k, dict(sorted(c.items())))


if __name__ == "__main__":
    main()
