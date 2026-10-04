import sys, json, collections, pickle
sys.path.insert(0,'/home/kenzx0521/Bible_RAG/scripts')
import importlib.util
spec=importlib.util.spec_from_file_location('tsk','/home/kenzx0521/Bible_RAG/scripts/import_tsk_crossrefs.py')
# avoid importing neo4j/dotenv side effects: load source and exec selected functions
src=open('/home/kenzx0521/Bible_RAG/scripts/import_tsk_crossrefs.py').read()
ns={'__file__':'/home/kenzx0521/Bible_RAG/scripts/import_tsk_crossrefs.py'}
exec(src.split('_MERGE_CYPHER')[0].replace('from dotenv import load_dotenv','load_dotenv=lambda *a,**k:None').replace('from neo4j import GraphDatabase',''),ns)
exec('\n'.join(['def build_verse_map'+src.split('def build_verse_map')[1].split('def main')[0]]),ns)
from pathlib import Path
vmap=ns['build_verse_map'](Path('/home/kenzx0521/Bible_RAG/output/embedding_queue.jsonl'))
print('vmap',len(vmap))
pairs=collections.defaultdict(lambda: {"votes":0,"verse_pairs":0,"vp":[]})
stats=collections.Counter()
with open('/home/kenzx0521/Bible_RAG/output/cross_references_tsk.txt') as f:
    next(f)
    for line in f:
        cols=line.rstrip('\n').split('\t')
        if len(cols)<3: continue
        stats['lines']+=1
        votes=int(cols[2])
        if votes<0: stats['neg']+=1; continue
        fr=ns['parse_ref'](cols[0])
        if not fr: stats['from_unparsed']+=1; continue
        fp=vmap.get(fr)
        if not fp: stats['from_unmapped']+=1; stats_unm=stats; continue
        tps=ns['expand_to_range'](cols[1],vmap)
        if not tps: stats['to_unmapped']+=1; continue
        for tp in tps:
            if tp==fp: stats['self']+=1; continue
            s=pairs[(fp,tp)]; s['votes']=max(s['votes'],votes); s['verse_pairs']+=1; s['vp'].append((cols[0],cols[1],votes))
print(stats, 'unique pairs',len(pairs))
pickle.dump({k:dict(v) for k,v in pairs.items()},open('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/xref/tsk_pairs.pkl','wb'))
rels=[json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/neo4j_relationships.jsonl')]
cur=collections.defaultdict(list)
for r in rels:
    if r['type']=='CROSS_REFERENCES': cur[(r['start'],r['end'])].append(r['properties']['source'])
ov=collections.Counter(); 
for k,v in cur.items():
    src=v[-1]
    ov[(src, k in pairs, (k[1],k[0]) in pairs)]+=1
print('curated pair overlap (source, same-dir in TSK, reverse in TSK):',ov)
print('tsk pairs - same-dir collisions =',len(pairs)-sum(1 for k in cur if k in pairs))
