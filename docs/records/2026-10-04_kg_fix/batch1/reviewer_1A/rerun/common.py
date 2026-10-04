"""Shared loaders for the batch-1A offline simulation (read-only on repo files)."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path('/home/kenzx0521/Bible_RAG')
OUT = REPO / 'output'
KGFIX = Path('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix')
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'scripts'))

KIN = {'FATHER_OF', 'SON_OF', 'MOTHER_OF', 'DAUGHTER_OF', 'SIBLING_OF', 'SPOUSE_OF', 'ANCESTOR_OF', 'DESCENDANT_OF'}
PARENT_HEAD = {'FATHER_OF', 'MOTHER_OF'}
PARENT_TAIL = {'SON_OF', 'DAUGHTER_OF'}
TYPE_OVERRIDES = {'group:yehehua': 'Person'}   # what 10.2 yehehua does (final label)


def jl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(x) for x in f if x.strip()]


def load_entities():
    ents = {r['entity_id']: r for r in jl(OUT / 'entities.jsonl')}
    types = {eid: TYPE_OVERRIDES.get(eid, r['type']) for eid, r in ents.items()}
    return ents, types


def load_chunk_parent():
    return {r['id']: r['parent_id'] for r in jl(OUT / 'chunks.jsonl')}


GEO = None


def dan_keep_sources():
    from cleanup_noise_entities import compute_dan_keep_sources  # pure function over the JSONL
    return compute_dan_keep_sources(OUT / 'entity_mentions.jsonl')


def load_mentions(apply_dan=True, with_curated=False):
    """Mention rows mapped as import_neo4j maps them; 10.2's dan filter applied
    (the deletion is a pure function of entity_mentions.jsonl)."""
    keep = dan_keep_sources() if apply_dan else None
    rows = []
    for r in jl(OUT / 'entity_mentions.jsonl'):
        sid, st = r['source_id'], r.get('source_type', '')
        if st == 'verse' or ':v:' in sid:
            label, s = 'Pericope', sid.split(':v:')[0]
        elif st == 'chunk':
            label, s = 'Chunk', sid
        else:
            label, s = 'Pericope', sid
        if apply_dan and r['entity_id'] == 'place:dan' and s not in keep:
            continue
        rows.append({'label': label, 'sid': s, 'eid': r['entity_id'], 'span': (r.get('text_span') or '').strip(),
                     'raw_sid': sid})
    if with_curated:
        for r in jl(OUT / 'frozen/live_state/20261004/curated_mentions.jsonl'):
            rows.append({'label': r['source_label'], 'sid': r['source_id'], 'eid': r['entity_id'], 'span': '',
                         'raw_sid': r['source_id']})
    return rows


def support_set(mentions, chunk_parent):
    sup = set()
    for m in mentions:
        pid = chunk_parent.get(m['sid'], m['sid']) if m['label'] == 'Chunk' else m['sid']
        sup.add((pid, m['eid']))
    return sup


def load_pericopes():
    return {r['id']: r for r in jl(OUT / 'pericopes.jsonl')}


VERSE_RE = re.compile(r'\*\*(\d+)\*\*\s*')


def verses_of(content):
    """[(verse_no, text)] from '**N** text' blocks."""
    parts = VERSE_RE.split(content)
    out = []
    for i in range(1, len(parts) - 1, 2):
        out.append((int(parts[i]), parts[i + 1].strip()))
    return out


def load_schema():
    from scripts.relation_extraction.schema_loader import RelationSchema
    return RelationSchema.load(REPO / 'config/relations/biblical_relations.yaml')


def female_persons():
    import yaml
    return set(yaml.safe_load(open(REPO / 'config/kg_probes.yaml', encoding='utf-8'))['female_persons'])


def probes():
    import yaml
    return [f for f in yaml.safe_load(open(REPO / 'config/kg_probes.yaml', encoding='utf-8'))['facts']
            if f['kind'] == 'relation']


def r6(edges, female):
    parent_of = set()
    for h, rel, t in edges:
        if rel in PARENT_HEAD:
            parent_of.add((h, t))
        elif rel in PARENT_TAIL:
            parent_of.add((t, h))
    fathers = [(h, t) for h, rel, t in edges if rel == 'FATHER_OF']
    contra = [(h, t) for h, t in fathers if (t, h) in parent_of]
    fem = [(h, t) for h, t in fathers if h in female]
    children = defaultdict(set)
    for h, t in fathers:
        children[t].add(h)
    multi = sum(1 for v in children.values() if len(v) > 1)
    return {'FATHER_OF': len(fathers), 'contradictions': len(contra), 'female_head': len(fem),
            'children': len(children), 'children_2plus_fathers': multi,
            'functional_violation_rate': round(multi / len(children), 4) if children else 0.0,
            'contra_samples': contra[:8], 'female_samples': fem[:8]}
