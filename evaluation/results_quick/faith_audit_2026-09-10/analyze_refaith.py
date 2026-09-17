#!/usr/bin/env python
"""Summarise refaith_results.jsonl: per-condition scores, judge instability, residual negative verdicts."""
import json, re, statistics as st, sys
from collections import defaultdict, Counter

SP = '/tmp/claude-1001/-home-kenzx0521-Bible-RAG/bf0f2dab-e373-4e67-94f3-73544818e90d/scratchpad'
EVAL = '/home/kenzx0521/Bible_RAG/evaluation/results_graph'
rows = [json.loads(l) for l in open(f'{SP}/refaith_results.jsonl')]
res = json.load(open(f'{EVAL}/evaluation_results.json'))
raw = {x['question_id']: x for x in json.load(open(f'{EVAL}/raw_responses.json'))}
def metric(s, name):
    for m in s['metrics']:
        if m['name'] == name: return m['value'] if m['valid'] else None
stored = {s['question_id']: metric(s, 'ragas_faithfulness') for s in res['samples']}
qtype = {s['question_id']: s['question_type'] for s in res['samples']}
fam = {s['question_id']: s.get('family') for s in res['samples']}
by = defaultdict(dict)
for r in rows:
    by[r['qid']][r['condition']] = r
conds = ['orig', 'hdr', 'hdr_zh']
complete = [q for q in by if all(c in by[q] and by[q][c].get('score') is not None for c in conds)]
low = [q for q in complete if stored[q] < 1.0]
ctrl = [q for q in complete if stored[q] >= 1.0]
print(f"complete samples: {len(complete)} (non-perfect {len(low)}, controls {len(ctrl)})")

def mean(xs): return st.mean(xs) if xs else float('nan')
print("\n=== mean faithfulness by condition ===")
print(f"{'subset':16s} {'stored':>8s} {'orig':>8s} {'hdr':>8s} {'hdr_zh':>8s}")
for name, subset in [('non-perfect', low), ('controls', ctrl), ('all', complete)]:
    print(f"{name:16s} {mean([stored[q] for q in subset]):8.3f} " + " ".join(f"{mean([by[q][c]['score'] for q in subset]):8.3f}" for c in conds))

# corrected overall estimate: perfect ones (358) assumed to behave like controls
n_all = sum(1 for q in stored if stored[q] is not None)
n_perf = sum(1 for q in stored if stored[q] is not None and stored[q] >= 1.0)
n_low = n_all - n_perf
print(f"\n=== estimated overall faithfulness (n={n_all}; {n_perf} perfect scaled by control mean, {n_low} non-perfect measured) ===")
if low and ctrl:
    for c in conds:
        est = (n_perf * mean([by[q][c]['score'] for q in ctrl]) + sum(by[q][c]['score'] for q in low) + 0) / (n_perf + len(low))
        print(f"  {c:8s}: {est:.3f}   (stored overall 0.912)")

print("\n=== by question type (non-perfect subset) ===")
for t in sorted(set(qtype[q] for q in low)):
    qs = [q for q in low if qtype[q] == t]
    print(f"  {t:24s} n={len(qs):3d} stored={mean([stored[q] for q in qs]):.3f} orig={mean([by[q]['orig']['score'] for q in qs]):.3f} hdr={mean([by[q]['hdr']['score'] for q in qs]):.3f} hdr_zh={mean([by[q]['hdr_zh']['score'] for q in qs]):.3f}")

print("\n=== judge instability: stored vs orig (identical inputs, greedy) ===")
d = [by[q]['orig']['score'] - stored[q] for q in complete]
print(f"  mean |delta|={mean([abs(x) for x in d]):.3f}; moved >=0.2: {sum(1 for x in d if abs(x)>=0.2)}/{len(d)}; up: {sum(1 for x in d if x>0.05)} down: {sum(1 for x in d if x<-0.05)}")

# residual negatives under hdr_zh
CIT = re.compile(r"章節|標頭|出處|書卷|label|chapter|verse|citation", re.I)
print("\n=== residual negative verdicts under hdr_zh ===")
neg = []
for q in complete:
    for v in by[q]['hdr_zh'].get('verdicts', []):
        if v['verdict'] == 0:
            neg.append((q, v['statement'], v['reason']))
print(f"  {len(neg)} negative statements across {len(set(q for q,_,_ in neg))} samples")
for q, s, r in neg:
    print(f"  - {q} [{fam[q]}] | {s[:90]} || {r[:160]}")

print("\n=== residual negative verdicts under hdr (default English prompt) — classification ===")
cats = Counter(); n = 0
PREM = re.compile(r"identity|speaker|the name|names? of|who is|recipient|author|audience|'Jesus'|'Paul'|'Moses'|'David'|'Solomon'|'Thomas'|名字|說話者|對象|作者|身分", re.I)
META = re.compile(r"fragment|incomplete|heading|introductory|not a (factual|complete)|meta|rule about|引導|標題|片段", re.I)
INTERP = re.compile(r"interpret|inference|synthesis|analytical|theological|categoriz|stage|summar|comparison|comparative|解釋|推論|歸納|對比|階段", re.I)
for q in complete:
    for v in by[q]['hdr'].get('verdicts', []):
        if v['verdict'] == 0:
            n += 1; r = v['reason']
            if CIT.search(r): cats['citation/label'] += 1
            elif PREM.search(r): cats['question-premise entity'] += 1
            elif META.search(r): cats['meta/heading'] += 1
            elif INTERP.search(r): cats['interpretation/synthesis'] += 1
            else: cats['other (candidate real error)'] += 1
print(f"  {n} negatives:", dict(cats))
