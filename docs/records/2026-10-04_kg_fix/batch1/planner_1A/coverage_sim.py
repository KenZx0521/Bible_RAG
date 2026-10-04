"""Event-layer coverage: live (with 10.3), live without 10.3 edges, and after 1A (6.05 output)."""
import json, sys
from collections import Counter
from common import KGFIX, OUT, jl
LS = OUT / 'frozen/live_state/20261004/entities.jsonl'
lab = {}
for r in jl(LS):
    t = [l for l in r['labels'] if l != 'Entity']
    lab[r['entity_id']] = t[0] if t else None
events = {e for e, t in lab.items() if t == 'Event'}
E = json.load(open(KGFIX / 'relverify/edges.json'))

def cov(edges):
    part = {t for h, r, t in edges if r == 'PARTICIPATED_IN' and lab.get(h) == 'Person' and t in events}
    plc = {h for h, r, t in edges if r == 'OCCURRED_IN' and h in events and lab.get(t) == 'Place'}
    any_sem = {x for h, r, t in edges for x in (h, t) if x in events}
    return {'events': len(events), 'with_participant': len(part), 'pct_participant': round(100 * len(part) / len(events), 1),
            'with_place': len(plc), 'pct_place': round(100 * len(plc) / len(events), 1),
            'with_any_semantic_edge': len(any_sem), 'pct_any': round(100 * len(any_sem) / len(events), 1)}

live = [(e['h'], e['rel'], e['t']) for e in E]
live_no103 = [(e['h'], e['rel'], e['t']) for e in E if not e['props'].get('backfilled')]
bf = Counter(e['rel'] for e in E if e['props'].get('backfilled'))
dan_bf = Counter(e['rel'] for e in E if e['props'].get('backfilled') and 'place:dan' in (e['h'], e['t']))
out = {'live_with_10.3': cov(live), 'live_without_10.3': cov(live_no103), 'live_10.3_edges': dict(bf),
       'live_10.3_edges_to_place_dan': dict(dan_bf)}
for f in sys.argv[1:]:
    F = [json.loads(l) for l in open(f)]
    edges = [(r['head_id'], r['relation'], r['tail_id']) for r in F if r['head_id'] in lab and r['tail_id'] in lab]
    out[f] = cov(edges)
    out[f]['dropped_missing_endpoint_after_10.2'] = len(F) - len(edges)
print(json.dumps(out, ensure_ascii=False, indent=1))
