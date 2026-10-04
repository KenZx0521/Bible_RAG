import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from collections import Counter
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
U=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations_unclassified.jsonl')]
ck=[json.loads(l)['pair_key'] for l in open(BIBLE_RAG_ROOT + '/output/relations_checkpoint.jsonl')]
ckset=set(ck)
print('ckpt lines',len(ck),'unique',len(ckset))
def pk(h,t,p): a,b=sorted((h,t)); return f"{a}|{b}|{p}"
uk={pk(u['head_id'],u['tail_id'],u['source_pericope_id']) for u in U}
llmk={pk(j['head_id'],j['tail_id'],j['source_pericope_id']) for j in J if j['extraction_phase']==4}
rulek={pk(j['head_id'],j['tail_id'],j['source_pericope_id']) for j in J if j['extraction_phase']==2}
print('unclassified unique',len(uk),'llm pairkeys',len(llmk),'rule pairkeys',len(rulek))
print('overlap u&llm',len(uk&llmk))
covered=uk|llmk|rulek
print('ckpt pairs not covered by any output', len(ckset-covered))
# order position of uncovered pairs in checkpoint
pos=[i for i,k in enumerate(ck) if k not in covered]
if pos: print('uncovered pos range', pos[0], pos[-1], 'first10', pos[:5])
