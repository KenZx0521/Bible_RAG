"""Batch-1A offline simulation of Step 6.05 over output/relations.jsonl.

Read-only: reads output/*.jsonl, config/*, the 2026-10-04 live edge dump
(kgfix/relverify/edges.json). Writes only into this scratch directory.
Usage: uv run --project /home/kenzx0521/Bible_RAG/scripts python sim_1a.py [--begot off|father]
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from common import (KIN, KGFIX, OUT, REPO, jl, load_chunk_parent, load_entities, load_mentions, load_pericopes,
                    load_schema, female_persons, probes, r6, support_set, verses_of)
import anchored_sim

HERE = Path(__file__).resolve().parent
SOURCE_RANK = {'curated': 0, 'prior': 1, 'llm': 2, 'anchored_rule': 3}   # plan §4: prior > LLM > anchored
PHASE_SOURCE = {2: 'rule', 3: 'prior', 4: 'llm', 5: 'inverse'}
NO_INVERSE_NAME_SAME_TYPE = {'LOCATED_IN', 'PRECEDED_BY', 'CAUSED', 'SUCCEEDED_BY'}
GENERIC_EVENT_STOPLIST = ["日子", "長子", "結局", "問候", "吩咐", "工程", "大會", "建築", "大事", "醜事", "使用", "艱難",
                          "爭論", "坐席", "生日", "探子", "兒子", "時候", "事情", "話", "早晨", "晚上", "夜間", "明天"]


def parent_child(r):
    if r['relation'] in ('FATHER_OF', 'MOTHER_OF'):
        return (r['head_id'], r['tail_id'])
    if r['relation'] in ('SON_OF', 'DAUGHTER_OF'):
        return (r['tail_id'], r['head_id'])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--begot', default='father', choices=['off', 'father', 'gei'])
    ap.add_argument('--surface', default='any', choices=['any', 'declared'])
    args = ap.parse_args()

    ents, types = load_entities()
    schema = load_schema()
    cp = load_chunk_parent()
    ment = load_mentions(apply_dan=True)
    sup = support_set(ment, cp)
    sup_nodan = support_set(load_mentions(apply_dan=False), cp)
    R = jl(OUT / 'relations.jsonl')
    log = Counter()
    drops = defaultdict(Counter)        # reason -> relation counts
    kin_drops = Counter()

    def drop(r, reason):
        drops[reason][r['relation']] += 1
        if r['relation'] in KIN:
            kin_drops[reason] += 1

    for r in R:
        r['source'] = PHASE_SOURCE[r['extraction_phase']]
    log['input'] = len(R)
    log['input_kin'] = sum(r['relation'] in KIN for r in R)

    # (1) rule (phase 2) and inverse (phase 5) out
    keep = []
    for r in R:
        if r['source'] == 'rule':
            drop(r, '1_rule_phase2')
        elif r['source'] == 'inverse':
            drop(r, '2_inverse_phase5')
        else:
            keep.append(r)
    # (2) LLM Event-Event out
    k2 = []
    for r in keep:
        if r['source'] == 'llm' and types.get(r['head_id']) == 'Event' and types.get(r['tail_id']) == 'Event':
            drop(r, '3_llm_event_event')
        else:
            k2.append(r)
    keep = k2

    # (3) anchored rules
    peri = load_pericopes()
    lex = set()
    for e in ents.values():
        lex.add((e['canonical_name'] or '').strip())
        lex.update(a.strip() for a in (e.get('aliases') or []))
    lex.update(m['span'] for m in ment)
    declared = None
    if args.surface == 'declared':
        declared = {eid: {(e['canonical_name'] or '').strip(), *[(a or '').strip() for a in (e.get('aliases') or [])]}
                    for eid, e in ents.items()}
    anchored, astats = anchored_sim.run(peri, ment, cp, lex, verses_of, begot_mode=args.begot, declared=declared)
    adedup = {}
    for a in anchored:
        adedup.setdefault((a['head_id'], a['relation'], a['tail_id']), a)
    log['anchored_raw'] = len(anchored)
    log['anchored_unique'] = len(adedup)
    for a in adedup.values():
        keep.append({**a, 'source': 'anchored_rule', 'extraction_phase': 6, 'confidence': None,
                     'head_canonical': ents.get(a['head_id'], {}).get('canonical_name', ''),
                     'tail_canonical': ents.get(a['tail_id'], {}).get('canonical_name', ''), 'notes': a['pattern']})

    # (4) domain/range with final labels
    k2 = []
    for r in keep:
        e = schema.get(r['relation'])
        if e is None or not e.accepts_pair(types.get(r['head_id']), types.get(r['tail_id'])):
            drop(r, '4_domain_range')
        else:
            k2.append(r)
    keep = k2

    # (5) provenance gate (prior exempt)
    k2 = []
    gate_dan_only = Counter()
    for r in keep:
        if r['source'] == 'prior':
            k2.append(r)
            continue
        pid = r['source_pericope_id']
        ok = pid and (pid, r['head_id']) in sup and (pid, r['tail_id']) in sup
        if not ok:
            drop(r, '5_provenance_gate')
            if pid and (pid, r['head_id']) in sup_nodan and (pid, r['tail_id']) in sup_nodan:
                gate_dan_only[r['relation']] += 1
        else:
            k2.append(r)
    keep = k2
    log['gate_drops_due_to_dan_filter'] = dict(gate_dan_only)

    # (6) phase-4 same-type relations without an inverse name: contradiction with prior -> drop, else flag
    prior_keys = {(r['head_id'], r['relation'], r['tail_id']) for r in keep if r['source'] == 'prior'}
    flagged = Counter()
    k2 = []
    for r in keep:
        if r['source'] == 'llm' and r['relation'] in NO_INVERSE_NAME_SAME_TYPE:
            if (r['tail_id'], r['relation'], r['head_id']) in prior_keys:
                drop(r, '6_contradicts_prior_direction')
                continue
            r['direction_verified'] = False
            flagged[r['relation']] += 1
        k2.append(r)
    keep = k2
    log['direction_unverified'] = dict(flagged)

    # (7) kinship contradiction resolution: one direction per parent/child pair, by source rank
    pc_best = {}
    for r in keep:
        pc = parent_child(r)
        if pc is None:
            continue
        key = frozenset(pc)
        cur = pc_best.get(key)
        if cur is None or SOURCE_RANK[r['source']] < SOURCE_RANK[cur[1]]:
            pc_best[key] = (pc, r['source'])
    conflicts = []
    k2 = []
    for r in keep:
        pc = parent_child(r)
        if pc is not None and pc != pc_best[frozenset(pc)][0]:
            drop(r, '7_kin_direction_conflict')
            conflicts.append((r['head_id'], r['relation'], r['tail_id'], r['source'],
                              pc_best[frozenset(pc)][1]))
            continue
        k2.append(r)
    keep = k2

    # (7b) undirected relations: canonical orientation, one edge per pair
    k2, seen_und = [], {}
    for r in keep:
        e = schema.get(r['relation'])
        if e.direction == 'undirected':
            a, b = sorted((r['head_id'], r['tail_id']))
            key = (a, r['relation'], b)
            if key in seen_und:
                old = seen_und[key]
                if SOURCE_RANK[r['source']] < SOURCE_RANK[old['source']]:
                    seen_und[key] = r
                    drop(old, '7b_undirected_duplicate')
                else:
                    drop(r, '7b_undirected_duplicate')
                continue
            seen_und[key] = r
        k2.append(r)
    keep = [r for r in k2 if schema.get(r['relation']).direction != 'undirected'] + list(seen_und.values())

    # (8) one row per (head, rel, tail): priority winner + multi-source evidence
    by_key = defaultdict(list)
    for r in keep:
        by_key[(r['head_id'], r['relation'], r['tail_id'])].append(r)
    multi_source = sum(1 for v in by_key.values() if len({x['source'] for x in v}) > 1)
    final = []
    for key, rows in by_key.items():
        rows.sort(key=lambda x: (SOURCE_RANK[x['source']], x.get('source_pericope_id') or ''))
        w = dict(rows[0])
        w['sources'] = sorted({x['source'] for x in rows})
        w['evidence_count'] = len(rows)
        final.append(w)
    log['multi_source_keys'] = multi_source
    log['output'] = len(final)

    # ---- metrics -----------------------------------------------------------
    edges = [(r['head_id'], r['relation'], r['tail_id']) for r in final]
    fem = female_persons()
    before_edges = [(r['head_id'], r['relation'], r['tail_id']) for r in R]
    live = json.load(open(KGFIX / 'relverify/edges.json'))
    live_edges = [(e['h'], e['rel'], e['t']) for e in live]
    res = {
        'begot_mode': args.begot, 'surface_mode': args.surface, 'log': dict(log), 'anchored_stats': astats,
        'drops': {k: dict(v) for k, v in sorted(drops.items())},
        'drops_total': {k: sum(v.values()) for k, v in sorted(drops.items())},
        'kin_drops': dict(kin_drops),
        'final_by_source': dict(Counter(s for r in final for s in [r['source']])),
        'final_kin_total': sum(1 for r in final if r['relation'] in KIN),
        'final_kin_by_rel': dict(Counter(r['relation'] for r in final if r['relation'] in KIN)),
        'final_kin_by_source': dict(Counter(r['source'] for r in final if r['relation'] in KIN)),
        'final_by_rel': dict(sorted(Counter(r['relation'] for r in final).items())),
        'r6_relations_jsonl_before': {k: v for k, v in r6(before_edges, fem).items() if 'samples' not in k},
        'r6_live_before': {k: v for k, v in r6(live_edges, fem).items() if 'samples' not in k},
        'r6_after': r6(edges, fem),
        'kin_conflicts': conflicts[:40], 'kin_conflicts_n': len(conflicts),
    }
    # probes
    ek = set(edges)
    res['probes'] = {p['id']: ((p['head'], p['rel'], p['tail']) in ek) == (p['expect'] == 'present') for p in probes()}
    # same-type directed head<tail ratio (n>=30)
    ratio = {}
    by_rel = defaultdict(list)
    for r in final:
        e = schema.get(r['relation'])
        if e.direction == 'directed' and types.get(r['head_id']) == types.get(r['tail_id']):
            by_rel[r['relation']].append(r['head_id'] < r['tail_id'])
    for rel, v in by_rel.items():
        ratio[rel] = (len(v), round(sum(v) / len(v), 3))
    res['same_type_directed_head_lt_tail'] = ratio
    json.dump(res, open(HERE / f'sim_1a_{args.begot}_{args.surface}.json', 'w'), ensure_ascii=False, indent=1)
    with open(HERE / f'relations_clean_sim_{args.begot}_{args.surface}.jsonl', 'w', encoding='utf-8') as f:
        for r in sorted(final, key=lambda x: (x['head_id'], x['relation'], x['tail_id'])):
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(HERE / f'anchored_sim_{args.begot}_{args.surface}.jsonl', 'w', encoding='utf-8') as f:
        for a in sorted(adedup.values(), key=lambda x: (x['source_pericope_id'], x['verse'], x['head_id'])):
            f.write(json.dumps(a, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in res.items() if k not in ('kin_conflicts',)}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
