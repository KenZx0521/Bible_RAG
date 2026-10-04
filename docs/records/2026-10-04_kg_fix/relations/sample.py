import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, random, re
E = json.load(open('edges.json'))
P = {}
for line in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    r = json.loads(line); P[r['id']] = r
KIN = ['FATHER_OF','SON_OF','MOTHER_OF','DAUGHTER_OF','SIBLING_OF','SPOUSE_OF','ANCESTOR_OF','DESCENDANT_OF']
def verse_ctx(pid, hn, tn):
    p = P.get(pid)
    if not p: return ''
    vs = [v for v in p['content'].split('\n') if v.strip()]
    hit = [v for v in vs if hn in v and tn in v]
    if hit: return ' || '.join(hit[:2])[:260]
    hv = [v for v in vs if hn in v][:1]; tv=[v for v in vs if tn in v][:1]
    return ('H:'+ (hv[0][:120] if hv else '-') + ' || T:' + (tv[0][:120] if tv else '-'))
random.seed(20261004)
kin = [e for e in E if e['rel'] in KIN]
strata = {2: 22, 4: 16, 5: 10, 3: 6}
out = []
for ph, k in strata.items():
    pool = [e for e in kin if e['props'].get('extraction_phase') == ph]
    for e in random.sample(pool, min(k, len(pool))):
        pr = e['props']
        out.append(dict(ph=ph, rel=e['rel'], h=e['h'], hn=e['hn'], tn=e['tn'], t=e['t'], conf=pr.get('confidence'),
             pid=pr.get('source_pericope_id'), notes=pr.get('notes'), ev=(pr.get('evidence_span') or '')[:100],
             ctx=verse_ctx(pr.get('source_pericope_id'), e['hn'], e['tn'])))
json.dump(out, open('kin_sample.json','w'), ensure_ascii=False, indent=0)
for i, o in enumerate(out):
    print(f"#{i} ph{o['ph']} {o['hn']}({o['h']}) -{o['rel']}-> {o['tn']}({o['t']}) c={o['conf']} pid={o['pid']} notes={o['notes']}\n   EV: {o['ev']}\n   CTX: {o['ctx']}")
