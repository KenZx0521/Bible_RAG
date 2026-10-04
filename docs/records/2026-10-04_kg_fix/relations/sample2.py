import json, random
E = json.load(open('edges.json'))
P = {json.loads(l)['id']: json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl')}
def ctx(pid, hn, tn):
    p = P.get(pid)
    if not p: return ''
    vs=[v for v in p['content'].split('\n') if v.strip()]
    hit=[v for v in vs if hn in v and tn in v]
    if hit: return hit[0][:200]
    hv=[v for v in vs if hn in v][:1]; tv=[v for v in vs if tn in v][:1]
    return f"[title={p['title']}] H:{hv[0][:90] if hv else '-'} || T:{tv[0][:90] if tv else '-'}"
random.seed(7)
KIN={'FATHER_OF','SON_OF','MOTHER_OF','DAUGHTER_OF','SIBLING_OF','SPOUSE_OF','ANCESTOR_OF','DESCENDANT_OF'}
llm=[e for e in E if e['props']['extraction_phase']==4 and e['rel'] not in KIN and e['rel'] not in ('PARTICIPATED_IN','OCCURRED_IN')]
llm_eo=[e for e in E if e['props']['extraction_phase']==4 and e['rel'] in ('PARTICIPATED_IN','OCCURRED_IN')]
bf=[e for e in E if e['props'].get('backfilled')]
for name,pool,k in [('LLM-nonkin',llm,20),('LLM-event',llm_eo,10),('BACKFILL',bf,20)]:
    print('=====',name,len(pool))
    for e in random.sample(pool,k):
        pr=e['props']
        print(f"- {e['hn']} -{e['rel']}-> {e['tn']} pid={pr.get('source_pericope_id')} ev={(pr.get('evidence_span') or '')[:70]!r}\n    CTX {ctx(pr.get('source_pericope_id'),e['hn'],e['tn'])}")
