"""Anchored sim (planner code) with tokenizer lexicon restricted to P/P/G names vs full lexicon."""
import json
from collections import Counter
from common import load_entities, load_mentions, load_pericopes, verses_of, load_chunk_parent
import anchored_sim as A
ents, types = load_entities()
ment = load_mentions(apply_dan=True)
cp = load_chunk_parent(); peri = load_pericopes()
declared = {eid: {(e['canonical_name'] or '').strip(), *[(a or '').strip() for a in (e.get('aliases') or [])]} for eid, e in ents.items()}
def lexicon(ppg_only):
    lex=set()
    for eid,e in ents.items():
        if ppg_only and types[eid] not in ('Person','Place','Group'): continue
        lex.add((e['canonical_name'] or '').strip()); lex.update(a.strip() for a in (e.get('aliases') or []))
    lex.update(m['span'] for m in ment if (not ppg_only) or types.get(m['eid']) in ('Person','Place','Group'))
    return lex
out={}
for name,ppg in (('full',False),('ppg_only',True)):
    rows, st = A.run(peri, ment, cp, lexicon(ppg), verses_of, begot_mode='gei', declared=declared)
    keys={(r['head_id'],r['relation'],r['tail_id']) for r in rows}
    out[name]=(len(rows), len(keys), keys, st)
f,p=out['full'],out['ppg_only']
print('full raw/unique', f[0], f[1], f[3]); print('ppg_only raw/unique', p[0], p[1], p[3])
print('gained', len(p[2]-f[2]), 'lost', len(f[2]-p[2]))
ent={k:v['canonical_name'] for k,v in ents.items()}
for k in sorted(p[2]-f[2])[:15]: print('  +', ent[k[0]], k[1], ent[k[2]])
rows, st = A.run(peri, ment, cp, lexicon(True), verses_of, begot_mode='gei', declared=declared)
for r in rows:
    if (r['head_id'],r['tail_id']) in (('person:bide','person:maliya'),('person:dawei','person:xiluya')):
        print(r['head_id'], r['relation'], r['tail_id'], r['source_pericope_id'], r['verse'], r['evidence_span'][:90])
