"""Predict validate_kg H3/H9/R6/W and diff_kg (relationships, ee_edges) for a staging-1A rebuild
vs prod, from a simulated relations_clean.jsonl. Phase codes: prior 3, llm 4, anchored_rule 6."""
import json, sys
from collections import Counter, defaultdict
from common import KGFIX, OUT, jl, load_chunk_parent, load_mentions, support_set, load_schema, female_persons, r6, KIN
f = sys.argv[1]
lab = {}
for r in jl(OUT / 'frozen/live_state/20261004/entities.jsonl'):
    t = [l for l in r['labels'] if l != 'Entity']
    lab[r['entity_id']] = t[0] if t else None
PHASE = {'prior': 3, 'llm': 4, 'anchored_rule': 6}
F = [json.loads(l) for l in open(f)]
final = [r for r in F if r['head_id'] in lab and r['tail_id'] in lab]   # 10.2 generic-events DETACH DELETE
live = json.load(open(KGFIX / 'relverify/edges.json'))
# relationships
a = Counter(e['rel'] for e in live)
b = Counter(r['relation'] for r in final)
rel_diff = {k: (a.get(k, 0), b.get(k, 0), b.get(k, 0) - a.get(k, 0)) for k in sorted(set(a) | set(b)) if a.get(k, 0) != b.get(k, 0)}
# ee_edges
ka = Counter(f"{e['rel']} phase={e['props'].get('extraction_phase', '-')} source={e['props'].get('source', '-') or '-'}" for e in live)
kb = Counter(f"{r['relation']} phase={PHASE[r['source']]} source={r['source']}" for r in final)
ee = {k: (ka.get(k, 0), kb.get(k, 0), kb.get(k, 0) - ka.get(k, 0)) for k in sorted(set(ka) | set(kb)) if ka.get(k, 0) != kb.get(k, 0)}
# H3 with the post-10.x mention set (dan filtered + curated)
cp = load_chunk_parent()
sup = support_set(load_mentions(apply_dan=True, with_curated=True), cp)
h3 = [r for r in final if r['source'] != 'prior' and not (r.get('source_pericope_id') and (r['source_pericope_id'], r['head_id']) in sup and (r['source_pericope_id'], r['tail_id']) in sup)]
schema = load_schema()
h9 = [r for r in final if not schema.get(r['relation']).accepts_pair(lab[r['head_id']], lab[r['tail_id']])]
# live H3/H9 for reference
live_h9 = [e for e in live if not schema.get(e['rel']).accepts_pair(lab.get(e['h']), lab.get(e['t']))]
fem = female_persons()
both_enc = 0
pc = defaultdict(set)
for r in final:
    if r['relation'] in ('FATHER_OF', 'MOTHER_OF'): pc[(r['head_id'], r['tail_id'])].add('P')
    if r['relation'] in ('SON_OF', 'DAUGHTER_OF'): pc[(r['tail_id'], r['head_id'])].add('C')
both_enc = sum(1 for v in pc.values() if v == {'P', 'C'})
out = {'final_edges': len(final), 'live_edges': len(live), 'delta': len(final) - len(live),
       'kin_final': sum(r['relation'] in KIN for r in final), 'kin_live': sum(e['rel'] in KIN for e in live),
       'H3_unsupported': len(h3), 'H3_samples': [(r['head_id'], r['relation'], r['tail_id'], r.get('source_pericope_id')) for r in h3[:5]],
       'H9_violations': len(h9), 'H9_live': len(live_h9), 'H9_live_by': dict(Counter(f"{e['rel']}|phase={e['props'].get('extraction_phase')}|bf={bool(e['props'].get('backfilled'))}|{e['h']}->{e['t']}" for e in live_h9)),
       'R6': {k: v for k, v in r6([(r['head_id'], r['relation'], r['tail_id']) for r in final], fem).items() if 'samples' not in k},
       'parent_child_pairs_encoded_both_ways': both_enc,
       'source_null': sum(1 for r in final if not r.get('source')),
       'relationships_diff': rel_diff, 'ee_edges_diff': ee}
print(json.dumps(out, ensure_ascii=False, indent=1))
