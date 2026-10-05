"""Batch-1A offline simulation of Step 6.05 over output/relations.jsonl.

Read-only: reads output/*.jsonl, config/*, the 2026-10-04 live edge dump
(kgfix/relverify/edges.json). Writes only into --out-dir (default: this directory).

W1 archive of the scratch sim_1a_v3.py: sim_1a_v2 plus --disagree (pass-2 anchored
disagreement guard) and --anchored on|off. common.py is ../planner_1A/common.py;
roots and replay commands: docs/records/2026-10-04_kg_fix/README.md.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / 'planner_1A'))   # common.py
from common import (KIN, KGFIX, OUT, REPO, jl, load_chunk_parent, load_entities, load_mentions, load_pericopes,
                    load_schema, female_persons, probes, r6, support_set, verses_of)
import anchored_w1 as anchored_sim
import hashlib
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST

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
    ap.add_argument('--lexicon', default='full', choices=['full', 'ppg'])
    ap.add_argument('--stop-de', default='off', choices=['off', 'all', 'cont'])
    ap.add_argument('--guard', default='off', choices=['off', 'any', 'nonfemale', 'nonmother'])
    ap.add_argument('--homonym', default='', help='comma list of ids that abstain in kinship slots')
    ap.add_argument('--tag', default='')
    ap.add_argument('--anchored', default='on', choices=['on', 'off'])
    ap.add_argument('--disagree', default='off', choices=['off', 'nonfemale', 'nonfemale_p3', 'any'])
    ap.add_argument('--out-dir', type=Path, default=HERE, help='where sim2_/clean2_/anch2_* go')
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    anchored_sim.STOP_DE = args.stop_de

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
    PPG = ('Person', 'Place', 'Group')
    for eid, e in ents.items():
        if args.lexicon == 'ppg' and types[eid] not in PPG:
            continue
        lex.add((e['canonical_name'] or '').strip())
        lex.update(a.strip() for a in (e.get('aliases') or []))
    lex.update(m['span'] for m in ment if args.lexicon == 'full' or types.get(m['eid']) in PPG)
    fem_set = female_persons()
    parents = defaultdict(set)
    for r in keep:
        if r['source'] in ('curated', 'prior', 'llm'):
            pc = parent_child(r)
            if pc:
                parents[pc[1]].add(pc[0])
    mothers = {r['head_id'] for r in keep if r['source'] in ('curated', 'prior', 'llm') and r['relation'] == 'MOTHER_OF'}
    homonym = {x for x in args.homonym.split(',') if x}
    def guard(child, parent):
        if child in homonym or parent in homonym:
            return {'homonym'}
        if args.guard == 'off':
            return set()
        others = parents.get(child, set()) - {parent}
        if args.guard in ('nonfemale', 'nonmother'):
            excl = fem_set | (mothers if args.guard == 'nonmother' else set())
            if parent in excl:
                return set()
            others = others - excl
        return others
    guard_conflicts = []
    declared = None
    if args.surface == 'declared':
        declared = {eid: {(e['canonical_name'] or '').strip(), *[(a or '').strip() for a in (e.get('aliases') or [])]}
                    for eid, e in ents.items()}
    anchored, astats = anchored_sim.run(peri, ment, cp, lex, verses_of, begot_mode=args.begot, declared=declared,
                                        guard=None if args.guard == 'off' and not args.homonym else guard, conflicts=guard_conflicts)
    # v3: anchored-vs-anchored disagreement (two-pass): a child whose anchored hits name >=2 distinct
    # parents (non-female by the 31-person list) is a merged homonym node -> abstain every parent hit for it
    def _pc(a):
        if a['relation'] in ('SON_OF', 'DAUGHTER_OF'):
            return a['tail_id'], a['head_id']
        if a['relation'] == 'FATHER_OF':
            return a['head_id'], a['tail_id']
        return None
    dis_conf = []
    if args.disagree != 'off':
        cpar = defaultdict(set)
        cpar_p3 = defaultdict(set)
        for a in anchored:
            pc = _pc(a)
            if pc:
                if args.disagree == 'any' or pc[0] not in fem_set:
                    cpar[pc[1]].add(pc[0])
                if a['pattern'] == 'P3_begot':
                    cpar_p3[pc[1]].add(pc[0])
        bad = {c for c, ps in cpar.items() if len(ps) >= 2}
        kept = []
        for a in anchored:
            pc = _pc(a)
            if pc and pc[1] in bad:
                if args.disagree == 'nonfemale_p3' and len(cpar_p3[pc[1]]) == 1 and a['pattern'] == 'P3_begot':
                    kept.append(a); continue
                dis_conf.append({**a, 'reason': 'anchored_disagreement', 'other_parents': sorted(cpar[pc[1]] - {pc[0]})})
                continue
            kept.append(a)
        log['anchored_disagreement_children'] = len(bad)
        log['anchored_disagreement_abstain_raw'] = len(dis_conf)
        anchored = kept
    if args.anchored == 'off':
        anchored = []
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
    # --- v2 extras ---------------------------------------------------------
    res['guard_conflicts_n'] = len(guard_conflicts)
    res['disagree_conflicts'] = dis_conf
    res['anchored_key_sha'] = hashlib.sha256('\n'.join(sorted(f"{a['head_id']}\t{a['relation']}\t{a['tail_id']}" for a in adedup.values())).encode()).hexdigest()
    res['guard_conflicts'] = guard_conflicts[:60]
    res['anchored_final_by_rel'] = dict(Counter(r['relation'] for r in final if r['source'] == 'anchored_rule'))
    res['anchored_keys_unique'] = len({(r['head_id'], r['relation'], r['tail_id']) for r in final if 'anchored_rule' in r['sources']})
    generic = {k for k, v in ents.items() if v['type'] == 'Event' and v.get('canonical_name') in GENERIC_EVENT_STOPLIST}
    after = [r for r in final if r['head_id'] not in generic and r['tail_id'] not in generic]
    res['generic_event_ids'] = len(generic)
    res['edges_on_generic_events'] = len(final) - len(after)
    res['after_10_2'] = len(after)
    lines = sorted(f"{r['head_id']}\t{r['relation']}\t{r['tail_id']}\t{r['source']}" for r in after)
    res['after_10_2_sha256'] = hashlib.sha256('\n'.join(lines).encode()).hexdigest()
    res['after_10_2_by_source'] = dict(Counter(r['source'] for r in after))
    res['after_10_2_kin'] = sum(1 for r in after if r['relation'] in KIN)
    res['after_10_2_kin_by_rel'] = dict(sorted(Counter(r['relation'] for r in after if r['relation'] in KIN).items()))
    # all-parent encoding (reviewer finding 6)
    def allpar(edges):
        par = defaultdict(set)
        for h, rel, t in edges:
            if rel in ('FATHER_OF', 'MOTHER_OF'): par[t].add(h)
            elif rel in ('SON_OF', 'DAUGHTER_OF'): par[h].add(t)
        two_nonfem = sum(1 for c, ps in par.items() if len(ps - fem) >= 2)
        gt2 = sum(1 for ps in par.values() if len(ps) > 2)
        return {'children': len(par), 'children_2plus_nonfemale_parents': two_nonfem, 'children_gt2_parents': gt2}
    res['allparent_live'] = allpar(live_edges)
    res['allparent_after'] = allpar([(r['head_id'], r['relation'], r['tail_id']) for r in after])
    res['r6_after_10_2'] = {k: v for k, v in r6([(r['head_id'], r['relation'], r['tail_id']) for r in after], fem).items() if 'samples' not in k}
    # relationships / ee_edges vs live
    PH = {'prior': 3, 'llm': 4, 'anchored_rule': 6}
    a = Counter(e['rel'] for e in live); b = Counter(r['relation'] for r in after)
    res['relationships_diff'] = {k: b.get(k, 0) - a.get(k, 0) for k in sorted(set(a) | set(b)) if a.get(k, 0) != b.get(k, 0)}
    kb = Counter(f"{r['relation']} phase={PH[r['source']]} source={r['source']}" for r in after)
    res['ee_new_keys'] = dict(sorted(kb.items()))
    res['ee_new_by_source'] = {s: sum(v for k, v in kb.items() if k.endswith('source=' + s)) for s in PH}
    res['ee_new_key_counts'] = {s: sum(1 for k in kb if k.endswith('source=' + s)) for s in PH}
    extra_probes = {
        'kin-david-son-of-jesse': (('person:dawei', 'SON_OF', 'person:yexi'), True),
        'kin-esau-father-of-jeush': (('person:yisao', 'FATHER_OF', 'person:yewushi'), True),
        'kin-amram-father-of-moses': (('person:anlan', 'FATHER_OF', 'person:moxi'), True),
        'edge-no-dan-near-jordan': (('place:dan', 'NEAR', 'place:yuedan'), False),
        'edge-no-galilee-in-nazareth': (('place:jialili', 'LOCATED_IN', 'place:nasalei'), False),
        'kin-peter-not-son-of-john': (('person:bide', 'SON_OF', 'person:yuehan（shitu）'), False),
        'kin-jethro-not-son-of-esau': (('person:yeteluo', 'SON_OF', 'person:yisao'), False),
        'kin-nahath-not-son-of-jethro': (('person:naha', 'SON_OF', 'person:yeteluo'), False),
        'kin-reuel-son-of-esau(liuer)': (('person:liuer', 'SON_OF', 'person:yisao'), None),
    }
    ek2 = {(r['head_id'], r['relation'], r['tail_id']) for r in after}
    res['new_probes'] = {pid: (k in ek2) if want is None else ((k in ek2) == want) for pid, (k, want) in extra_probes.items()}
    res['liuer_edges'] = sorted(f"{r['head_id']} {r['relation']} {r['tail_id']} [{r['source']}]" for r in after if 'person:liuer' in (r['head_id'], r['tail_id']))
    json.dump(res, open(args.out_dir / ('sim2_' + f"{args.begot}_{args.surface}_{args.lexicon}_{args.stop_de}_{args.guard}" + ("_hom" + str(len(args.homonym.split(","))) if args.homonym else "") + ("_dis" + args.disagree if args.disagree != 'off' else "") + ("_noanch" if args.anchored == 'off' else "") + '.json'), 'w'), ensure_ascii=False, indent=1)
    with open(args.out_dir / ('clean2_' + f"{args.begot}_{args.surface}_{args.lexicon}_{args.stop_de}_{args.guard}" + ("_hom" + str(len(args.homonym.split(","))) if args.homonym else "") + ("_dis" + args.disagree if args.disagree != 'off' else "") + ("_noanch" if args.anchored == 'off' else "") + '.jsonl'), 'w', encoding='utf-8') as f:
        for r in sorted(final, key=lambda x: (x['head_id'], x['relation'], x['tail_id'])):
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(args.out_dir / ('anch2_' + f"{args.begot}_{args.surface}_{args.lexicon}_{args.stop_de}_{args.guard}" + ("_hom" + str(len(args.homonym.split(","))) if args.homonym else "") + ("_dis" + args.disagree if args.disagree != 'off' else "") + ("_noanch" if args.anchored == 'off' else "") + '.jsonl'), 'w', encoding='utf-8') as f:
        for a in sorted(adedup.values(), key=lambda x: (x['source_pericope_id'], x['verse'], x['head_id'])):
            f.write(json.dumps(a, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in res.items() if k not in ('kin_conflicts','guard_conflicts','ee_new_keys')}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
