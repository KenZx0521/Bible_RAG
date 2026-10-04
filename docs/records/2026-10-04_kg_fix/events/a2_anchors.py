import json,re
P={}
for l in open('output/pericopes.jsonl'):
    p=json.loads(l); P[p['id']]=p
r=json.load(open('backend/data/event_registry.json'))
for e in r['events']:
    if e['id'] in ('event:shounanzhou','event:shanshangbaoxun'): 
        print('##',e['name'],e['triggers'],len(e['anchors']),'anchors')
        for a in e['anchors']:
            p=P[a]; vs=re.findall(r'\*\*(\d+)\*\*',p['content'])
            print('   ',a,p['title'],f"v{vs[0]}-{vs[-1]}" if vs else '')
        continue
    print('##',e['name'],e['triggers'])
    for a in e['anchors']:
        p=P.get(a)
        if not p: print('   MISSING',a); continue
        vs=re.findall(r'\*\*(\d+)\*\*',p['content'])
        txt=re.sub(r'\*\*\d+\*\*\s*','',p['content']).replace('\n','')
        print('   ',a,'|',p['title'],'|',f"v{vs[0]}-{vs[-1]}" if vs else '','|',txt[:70])
