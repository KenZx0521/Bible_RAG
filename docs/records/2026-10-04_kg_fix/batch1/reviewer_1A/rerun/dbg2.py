import json
from collections import Counter
from common import load_entities, load_mentions, load_pericopes, verses_of
import anchored_sim as A
ents, types = load_entities()
ment = load_mentions(apply_dan=True)
lex=set()
for e in ents.values():
    lex.add((e['canonical_name'] or '').strip()); lex.update(a.strip() for a in (e.get('aliases') or []))
lex.update(m['span'] for m in ment)
big = A.build_tokenizer(lex)
peri = load_pericopes()
swallow=Counter(); verses=0
for pid,p in peri.items():
    for v,t in verses_of(p['content']):
        hit=False
        for s,e,nm in A.tokens(t,big):
            if (nm.startswith('兒子') or nm.startswith('女兒') or nm.startswith('妻子')) and len(nm)>2 and s>0 and t[s-1]=='的':
                swallow[nm]+=1; hit=True
        verses+=hit
print('verses where a 的+兒子X/女兒X/妻子X junk token swallows the slot:', verses, 'tokens:', sum(swallow.values()))
print(swallow.most_common(20))
