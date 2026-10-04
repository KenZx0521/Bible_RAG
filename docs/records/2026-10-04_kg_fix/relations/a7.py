import json
from collections import Counter
R = [json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/relations.jsonl')]
P = {json.loads(l)['id']: json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl')}
c = Counter(); fallback = 0; ex=[]
for r in R:
    if r['extraction_phase'] != 4: continue
    ev = r['evidence_span'] or ''
    h, t = r['head_canonical'], r['tail_canonical']
    p = P.get(r['source_pericope_id'], {}).get('content','')
    if p and ev == p[:80]: fallback += 1
    hin, tin = h in ev, t in ev
    c[(hin, tin)] += 1
    if not hin and not tin and len(ex)<8: ex.append((h, r['relation'], t, ev[:60]))
print('LLM triples', sum(c.values()), dict(c), 'evidence==context[:80] fallback-like', fallback)
print(ex)
