"""Reviewer: independent re-implementation of the non-anchored part of 6.05.

Does not import the planner's common.py / sim_1a.py. Reads output/*.jsonl,
config yaml, and the prod edge dump (kgfix/relverify/edges.json). Writes only here.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REPO = Path('/home/kenzx0521/Bible_RAG')
OUT = REPO / 'output'
HERE = Path(__file__).resolve().parent
EDGES = Path('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/edges.json')
sys.path.insert(0, str(REPO / 'scripts'))
from cleanup_noise_entities import compute_dan_keep_sources, GENERIC_EVENT_STOPLIST  # noqa: E402

KIN = {'FATHER_OF', 'SON_OF', 'MOTHER_OF', 'DAUGHTER_OF', 'SIBLING_OF', 'SPOUSE_OF', 'ANCESTOR_OF', 'DESCENDANT_OF'}


def jl(p):
    with open(p, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


schema = yaml.safe_load(open(REPO / 'config/relations/biblical_relations.yaml', encoding='utf-8'))['relations']
ents = {r['entity_id']: r for r in jl(OUT / 'entities.jsonl')}
typ = {k: v['type'] for k, v in ents.items()}
typ['group:yehehua'] = 'Person'
chunk_parent = {r['id']: r['parent_id'] for r in jl(OUT / 'chunks.jsonl')}
keep_dan = compute_dan_keep_sources(OUT / 'entity_mentions.jsonl')

support = set()
support_nodan = set()
for m in jl(OUT / 'entity_mentions.jsonl'):
    raw = m['source_id']
    if m.get('source_type') == 'chunk':
        src, pid = raw, chunk_parent[raw]
    else:
        src = pid = raw.split(':v:')[0]
    support_nodan.add((pid, m['entity_id']))
    if m['entity_id'] == 'place:dan' and src not in keep_dan:
        continue
    support.add((pid, m['entity_id']))


def accepts(rel, h, t):
    e = schema[rel]
    ht, tt = typ.get(h), typ.get(t)
    if e['direction'] == 'undirected':
        return (ht in e['domain_types'] and tt in e['range_types']) or (tt in e['domain_types'] and ht in e['range_types'])
    return ht in e['domain_types'] and tt in e['range_types']


R = list(jl(OUT / 'relations.jsonl'))
keys = Counter((r['head_id'], r['relation'], r['tail_id']) for r in R)
flow = Counter()
drop = defaultdict(Counter)
kept = []
missing_endpoint = Counter()
for r in R:
    ph, rel, h, t = r['extraction_phase'], r['relation'], r['head_id'], r['tail_id']
    if h not in ents or t not in ents:
        missing_endpoint[rel] += 1
    if ph == 2:
        drop['rule'][rel] += 1; continue
    if ph == 5:
        drop['inverse'][rel] += 1; continue
    if ph == 4 and typ.get(h) == 'Event' and typ.get(t) == 'Event':
        drop['llm_EE'][rel] += 1; continue
    if not accepts(rel, h, t):
        drop['domain_range'][rel] += 1; continue
    if ph != 3:
        pid = r['source_pericope_id']
        if not ((pid, h) in support and (pid, t) in support):
            drop['gate'][rel] += 1
            if (pid, h) in support_nodan and (pid, t) in support_nodan:
                drop['gate_due_to_dan'][rel] += 1
            continue
    kept.append(r)

# same-type directed, no inverse name in ORIGINAL yaml
same_type_noinv = sorted(k for k, e in schema.items() if e['direction'] == 'directed' and not e.get('inverse')
                         and set(e['domain_types']) == set(e['range_types']))
prior_keys = {(r['head_id'], r['relation'], r['tail_id']) for r in kept if r['extraction_phase'] == 3}
flag = Counter(); contra_prior = []
k2 = []
for r in kept:
    if r['extraction_phase'] == 4 and r['relation'] in same_type_noinv:
        if (r['tail_id'], r['relation'], r['head_id']) in prior_keys:
            contra_prior.append((r['head_id'], r['relation'], r['tail_id'])); continue
        flag[r['relation']] += 1
    k2.append(r)
kept = k2

# what if C6a nulls kin inverse and C4g/H11 re-derive "no inverse name" from yaml?
kin_null = {'FATHER_OF', 'MOTHER_OF', 'SON_OF', 'DAUGHTER_OF'}
would_flag_after_c6a = Counter(r['relation'] for r in kept if r['extraction_phase'] == 4 and r['relation'] in kin_null)

# generic events deleted by 10.2 (by canonical name)
generic_ids = {k for k, v in ents.items() if v['type'] == 'Event' and v.get('canonical_name') in GENERIC_EVENT_STOPLIST}
on_generic = sum(1 for r in kept if r['head_id'] in generic_ids or r['tail_id'] in generic_ids)

res = {
    'input': len(R), 'dup_keys': sum(1 for v in keys.values() if v > 1),
    'phase_counts': dict(Counter(r['extraction_phase'] for r in R)),
    'missing_endpoint_in_entities_jsonl': dict(missing_endpoint),
    'drops': {k: (sum(v.values()), dict(v)) for k, v in drop.items()},
    'same_type_noinv_types': same_type_noinv,
    'flagged_direction_unverified': dict(flag), 'contradicts_prior': contra_prior,
    'would_be_flagged_if_noinv_derived_after_C6a': dict(would_flag_after_c6a),
    'kept_non_anchored': len(kept),
    'kept_kin_by_phase': dict(Counter((r['extraction_phase']) for r in kept if r['relation'] in KIN)),
    'kept_kin_total': sum(1 for r in kept if r['relation'] in KIN),
    'generic_event_ids': len(generic_ids), 'kept_edges_on_generic_events': on_generic,
}
# compare with live non-backfilled, by relation
live = json.load(open(EDGES))
live_by = Counter(e['rel'] for e in live)
kept_by = Counter(r['relation'] for r in kept if r['head_id'] not in generic_ids and r['tail_id'] not in generic_ids)
res['live_total'] = len(live)
res['kept_after_10.2_total'] = sum(kept_by.values())
res['rel_live_vs_kept_nonanchored'] = {k: (live_by.get(k, 0), kept_by.get(k, 0)) for k in sorted(set(live_by) | set(kept_by))}
json.dump(res, open(HERE / 'r1_flow.json', 'w'), ensure_ascii=False, indent=1)
with open(HERE / 'r1_kept.jsonl', 'w', encoding='utf-8') as f:
    for r in kept:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(json.dumps(res, ensure_ascii=False, indent=1))
