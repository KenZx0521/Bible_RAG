import json
from common import load_entities, load_mentions, load_pericopes, verses_of, load_chunk_parent
import anchored_sim as A
ents, types = load_entities()
ment = load_mentions(apply_dan=True)
lex=set()
for e in ents.values():
    lex.add((e['canonical_name'] or '').strip()); lex.update(a.strip() for a in (e.get('aliases') or []))
lex.update(m['span'] for m in ment)
big = A.build_tokenizer(lex)
peri = load_pericopes()
for pid in ('1ch:29:2','2sa:23:0','act:13:2'):
    for v,t in verses_of(peri[pid]['content']):
        if '耶西的兒子大衛' in t:
            print(pid, v, t[:40])
            print('  tokens', A.tokens(t, big)[:8])
