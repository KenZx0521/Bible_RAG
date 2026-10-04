import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
sys.path.insert(0, BIBLE_RAG_ROOT)
from collections import defaultdict, Counter
from itertools import combinations
from scripts.relation_extraction.schema_loader import RelationSchema
from scripts.relation_extraction.pair_miner import _trim_grounding
from scripts.relation_extraction.models import RelationCandidate
from scripts.relation_extraction.rule_classifier import classify_by_rules
from pathlib import Path
schema = RelationSchema.load(Path(BIBLE_RAG_ROOT + '/config/relations/biblical_relations.yaml'))
M = json.load(open('ment.json'))
P = {json.loads(l)['id']: json.loads(l)['content'] for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')}
by = defaultdict(dict)
for m in M:
    if m['bf']: continue  # approximate pre-P0 state: exclude verse-backfilled mentions
    by[m['pid']][m['eid']] = m
stats = Counter()
for pid in sorted(by):
    ents = sorted(by[pid].values(), key=lambda x: x['eid'])
    if len(ents) < 2: continue
    text = P.get(pid, '')
    pend = []; n=0
    for a, b in combinations(ents, 2):
        if a['eid']==b['eid']: continue
        if not (schema.candidates_for(a['t'], b['t']) or schema.candidates_for(b['t'], a['t'])): continue
        g = _trim_grounding(text, a['n'] or '', b['n'] or '', 1)
        c = RelationCandidate(a['eid'], b['eid'], a['t'], b['t'], a['n'] or '', b['n'] or '', pid, g)
        n += 1
        rm = classify_by_rules(c, schema)
        if rm and rm.confidence >= 0.85: stats['rule_hit'] += 1
        else: pend.append(c)
        if n >= 80: stats['truncated_pericopes'] += 1; break
    for i in range(0, len(pend), 8):
        batch = pend[i:i+8]; ctx = batch[0].grounding_text
        for k, c in enumerate(batch):
            stats['llm_pairs'] += 1
            own_ok = (c.head_canonical in c.grounding_text and c.tail_canonical in c.grounding_text) or c.head_type=='Event' or c.tail_type=='Event'
            shown_ok = all((nm in ctx) for nm, ty in ((c.head_canonical, c.head_type), (c.tail_canonical, c.tail_type)) if ty != 'Event')
            stats[f'k0' if k==0 else 'k>0'] += 1
            if k>0 and not shown_ok: stats['k>0_names_missing_from_shown_ctx'] += 1
            if k>0 and c.grounding_text != ctx: stats['k>0_ctx_differs'] += 1
print(dict(stats))
