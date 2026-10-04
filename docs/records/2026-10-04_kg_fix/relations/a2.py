import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re
from collections import Counter, defaultdict
E = json.load(open('edges.json'))
P = {json.loads(l)['id']: json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')}
def text(pid): return P.get(pid, {}).get('content', '')
GAP = r'[^。；：，、\n]{0,6}?'  # allow titles like 先知/祭司
def anchored_son(x_child, y_parent, t):
    # Y的兒子X  /  X是Y的兒子 / Y之子X
    pats = [re.escape(y_parent)+r'的(?:長|次)?(?:兒子|子)'+GAP+re.escape(x_child),
            re.escape(x_child)+r'是'+GAP+re.escape(y_parent)+r'的(?:長|次)?(?:兒子|子)',
            re.escape(y_parent)+r'之子'+GAP+re.escape(x_child)]
    return any(re.search(p, t) for p in pats)
def anchored_father(x_parent, y_child, t):
    pats = [re.escape(x_parent)+r'(?:[^。；\n]{0,12}?)生(?:了)?[^。；\n]{0,30}?'+re.escape(y_child)]
    return any(re.search(p, t) for p in pats)
res = defaultdict(Counter)
conf_by = defaultdict(Counter)
for e in E:
    pr = e['props']; ph = pr.get('extraction_phase'); rel = e['rel']
    if ph != 2 or rel not in ('SON_OF','FATHER_OF'): continue
    t = text(pr.get('source_pericope_id'))
    h, tl = e['hn'], e['tn']
    if rel == 'SON_OF':
        fwd = anchored_son(h, tl, t); rev = anchored_son(tl, h, t)
    else:
        fwd = anchored_father(h, tl, t); rev = anchored_father(tl, h, t)
    k = 'fwd_only' if fwd and not rev else 'rev_only' if rev and not fwd else 'both' if fwd and rev else 'neither'
    res[rel][k] += 1
    res[rel+'|'+pr.get('notes','')][k] += 1
for k in sorted(res):
    print(k, dict(res[k]), sum(res[k].values()))
