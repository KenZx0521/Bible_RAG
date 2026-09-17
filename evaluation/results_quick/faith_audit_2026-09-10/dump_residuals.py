#!/usr/bin/env python
"""Dump residual negative verdicts (hdr_zh and hdr) with the matching answer sentence, for manual classification.
Also compare hdr vs hdr_zh on the hand-verified real-error cases (judge false-positive check)."""
import json, re, sys
from collections import defaultdict

SP = '/tmp/claude-1001/-home-kenzx0521-Bible-RAG/bf0f2dab-e373-4e67-94f3-73544818e90d/scratchpad'
EVAL = '/home/kenzx0521/Bible_RAG/evaluation/results_graph'
rows = [json.loads(l) for l in open(f'{SP}/refaith_results.jsonl')]
raw = {x['question_id']: x for x in json.load(open(f'{EVAL}/raw_responses.json'))}
res = json.load(open(f'{EVAL}/evaluation_results.json'))
fam = {s['question_id']: s.get('family') for s in res['samples']}
by = defaultdict(dict)
for r in rows:
    by[r['qid']][r['condition']] = r

def sentence_for(qid, stmt):
    a = raw[qid]['rag_answer']
    sents = [s.strip() for s in re.split(r'(?<=[。！？\n])', a) if s.strip()]
    # crude overlap: pick the sentence sharing most 2-grams with the statement
    def grams(t): return set(t[i:i+2] for i in range(len(t)-1))
    g = grams(stmt)
    best = max(sents, key=lambda s: len(g & grams(s))) if sents else ''
    return best[:160]

cond = sys.argv[1] if len(sys.argv) > 1 else 'hdr_zh'
print(f"=== residual negatives under {cond} ===")
n = 0
for qid in by:
    r = by[qid].get(cond)
    if not r or r.get('score') is None:
        continue
    for v in r['verdicts']:
        if v['verdict'] == 0:
            n += 1
            print(f"\n[{n}] {qid} ({fam[qid]}) score={r['score']:.2f}")
            print(f"   STMT : {v['statement'][:150]}")
            print(f"   ANS  : {sentence_for(qid, v['statement'])}")
            print(f"   WHY  : {v['reason'][:220]}")

REAL = ['GENERAL_BIBLE_QUESTION_071', 'GENERAL_BIBLE_QUESTION_081', 'GENERAL_BIBLE_QUESTION_077', 'EVENT_QUESTION_068',
        'PERSON_QUESTION_061', 'GENERAL_BIBLE_QUESTION_039', 'VERSE_LOOKUP_090', 'GENERAL_BIBLE_QUESTION_020',
        'PERSON_QUESTION_089', 'PERSON_QUESTION_063', 'GENERAL_BIBLE_QUESTION_052']
print("\n=== hand-verified error cases: score by condition (stored / orig / hdr / hdr_zh) ===")
for q in REAL:
    if q in by:
        print(f"  {q:30s} " + " ".join(f"{c}={by[q][c]['score']:.2f}" if c in by[q] and by[q][c].get('score') is not None else f"{c}=NA" for c in ['orig', 'hdr', 'hdr_zh']), f" stored={by[q][list(by[q])[0]]['stored']}")
