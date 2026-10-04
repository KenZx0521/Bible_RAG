import json, collections
from pypinyin import lazy_pinyin, Style
ents={}
for l in open('/home/kenzx0521/Bible_RAG/output/entities.jsonl'):
    e=json.loads(l); ents[e['entity_id']]=e
spans=collections.defaultdict(collections.Counter)
for l in open('/home/kenzx0521/Bible_RAG/output/entity_mentions.jsonl'):
    m=json.loads(l); spans[m['entity_id']][m['text_span']]+=1
bytype=collections.Counter(); ids=[]
foreign_forms=0; minority=0; tone_unsep=0
for eid,c in spans.items():
    e=ents.get(eid)
    if not e: continue
    canon=e['canonical_name']; al=set(e.get('aliases') or [])
    # normalize whitespace
    forms=collections.Counter()
    for s,n in c.items(): forms[s.strip()]+=n
    foreign=[s for s in forms if s!=canon.strip() and s not in al]
    if foreign:
        bytype[e['type']]+=1; ids.append(eid)
        if e['type']=='Person':
            foreign_forms+=len(forms)
            top=forms.most_common(1)[0][0]
            if top!=canon.strip(): minority+=1
        t3=set(''.join(lazy_pinyin(s,style=Style.TONE3)) for s in forms)
        if len(t3)<len(forms): tone_unsep+=1
print('ids with foreign forms by type',dict(bytype),'total',sum(bytype.values()))
print('Person distinct forms total',foreign_forms,'minority canon',minority)
print('tone3 still colliding ids',tone_unsep)
# whitespace-only differences counted?
ws=sum(1 for eid in ids if all(s.strip() in (ents[eid]['canonical_name'].strip(),) for s in spans[eid]))
print('ids whose only foreign is whitespace variant',ws)
# check person:lude canon & ordering
print(ents['person:lude']['canonical_name'], spans['person:lude'])
json.dump(ids, open('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/verifier_identity/ids268.json','w'), ensure_ascii=False)
idset=set(ids)
for fn in ['relations.jsonl','relations_unclassified.jsonl']:
    tot=hit=sp=0; types=collections.Counter()
    for l in open('/home/kenzx0521/Bible_RAG/output/'+fn):
        r=json.loads(l); tot+=1
        if r.get('head_id') in idset or r.get('tail_id') in idset:
            hit+=1; sp+= bool(r.get('source_pericope_id'))
    print(fn,tot,'touch268',hit,'with_src_pid',sp)
r=json.loads(open('/home/kenzx0521/Bible_RAG/output/relations_unclassified.jsonl').readline()); print(sorted(r.keys()))
