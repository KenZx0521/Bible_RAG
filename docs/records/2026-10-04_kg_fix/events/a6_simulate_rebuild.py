"""Offline simulation: what would export_event_registry produce after a full
rebuild (Step 5 from current JSONL + Step 10.2/10.4/10.5 replay as coded)?
Pure file reads; no DB access."""
import json, sys, collections
sys.path.insert(0, 'scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('ex', 'scripts/export_event_registry.py')
# avoid importing (it imports backfill_head_events -> dotenv only; fine but keep pure)
from backfill_head_events import ALIAS_INJECTIONS, NEW_EVENTS, _pinyin_id
from export_event_registry import event_keywords, canonical_key
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST
books = {json.loads(l)['id']: json.loads(l)['order'] for l in open('output/books.jsonl')}
order = canonical_key(books)
nodes = {}
for l in open('output/entities.jsonl'):
    e = json.loads(l)
    if e['type'] == 'Event':
        nodes[e['entity_id']] = {'name': e['canonical_name'], 'aliases': list(e.get('aliases') or []), 'anchors': set()}
for l in open('output/entity_mentions.jsonl'):
    m = json.loads(l)
    if m['entity_id'] in nodes:
        nodes[m['entity_id']]['anchors'].add(m['source_id'].split(':v:')[0])
# 10.2
for eid in [k for k, v in nodes.items() if v['name'] in GENERIC_EVENT_STOPLIST]:
    del nodes[eid]
# 10.4
for eid, al in ALIAS_INJECTIONS.items():
    n = nodes[eid]; n['aliases'] = sorted(set(n['aliases'] + al) - {n['name']})
for ev in NEW_EVENTS:
    eid = _pinyin_id(ev['canonical_name'])
    n = nodes.setdefault(eid, {'name': ev['canonical_name'], 'aliases': [], 'anchors': set()})
    n['name'] = ev['canonical_name']; n['aliases'] = ev['aliases']; n['anchors'] |= set(ev['anchors'])
# 10.5 (ON CREATE SET only)
for l in open('config/curated/manual_graph_patches.jsonl'):
    r = json.loads(l)
    if r.get('kind') == 'node' and 'Event' in r['labels']:
        if r['entity_id'] not in nodes:
            p = r['props']; nodes[r['entity_id']] = {'name': p['canonical_name'], 'aliases': p.get('aliases') or [], 'anchors': set()}
    elif r.get('kind') == 'edge' and r['entity_id'] in nodes:
        nodes[r['entity_id']]['anchors'].add(r['pericope_id'])
# registry
ids = {eid: 'alias_injection' for eid in ALIAS_INJECTIONS}
for ev in NEW_EVENTS: ids[_pinyin_id(ev['canonical_name'])] = 'head_event_backfill'
for l in open('config/curated/manual_graph_patches.jsonl'):
    r = json.loads(l)
    if r.get('kind') == 'node' and 'Event' in r['labels']:
        ids.setdefault(r['entity_id'], 'manual_patch' if r.get('origin') == 'manual' else 'manual_edges')
kw = event_keywords()
sim = {}
for eid in sorted(ids):
    n = nodes[eid]; trig = sorted(k for k in kw if k in {n['name'], *n['aliases']})
    sim[eid] = (trig, sorted(n['anchors'], key=order))
cur = {e['id']: (e['triggers'], e['anchors']) for e in json.load(open('backend/data/event_registry.json'))['events']}
print('simulated events with triggers&anchors:', sum(1 for t, a in sim.values() if t and a), ' current:', len(cur))
for eid in sorted(set(sim) | set(cur)):
    s = sim.get(eid); c = cur.get(eid)
    s_eff = s if (s and s[0] and s[1]) else None
    if s_eff != c:
        print('DIFF', eid, '\n   current :', c, '\n   rebuilt :', s)
