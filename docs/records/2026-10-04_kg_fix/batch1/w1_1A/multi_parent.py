"""Children with 2+ non-female parents in a sim_1a_w1.py clean2_*.jsonl (after the 10.2 generic-event delete).
Usage: multi_parent.py CLEAN2_JSONL [--out-dir DIR]; see docs/records/2026-10-04_kg_fix/README.md."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import argparse, json, sys, yaml
from collections import defaultdict, Counter
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument('clean2', help='file name inside --out-dir (or an absolute path)')
ap.add_argument('--out-dir', type=Path, default=Path(__file__).resolve().parent, help="sim_1a_w1.py's --out-dir")
args = ap.parse_args()
fem=set(yaml.safe_load(open(BIBLE_RAG_ROOT + '/config/kg_probes.yaml'))['female_persons'])
GEN=["日子","長子","結局","問候","吩咐","工程","大會","建築","大事","醜事","使用","艱難","爭論","坐席","生日","探子","兒子","時候","事情","話","早晨","晚上","夜間","明天"]
ents={}
for l in open(BIBLE_RAG_ROOT + '/output/entities.jsonl'):
    r=json.loads(l); ents[r['entity_id']]=r
generic={k for k,v in ents.items() if v['type']=='Event' and v.get('canonical_name') in GEN}
rows=[json.loads(l) for l in open(args.out_dir / args.clean2)]
rows=[r for r in rows if r['head_id'] not in generic and r['tail_id'] not in generic]
par=defaultdict(list)
for r in rows:
    if r['relation'] in ('FATHER_OF','MOTHER_OF'): p,c=r['head_id'],r['tail_id']
    elif r['relation'] in ('SON_OF','DAUGHTER_OF'): p,c=r['tail_id'],r['head_id']
    else: continue
    par[c].append((p,r['source'],r['relation'],r.get('source_pericope_id'),r.get('verse')))
multi={c:v for c,v in par.items() if len({p for p,*_ in v}-fem)>=2}
print('children',len(par),'2plus_nonfem',len(multi),'gt2',sum(1 for v in par.values() if len({p for p,*_ in v})>2))
only_anch=0; anch_edges=0; mixed=0
lower_bound_wrong=0
for c,v in multi.items():
    nf=[x for x in v if x[0] not in fem]
    srcs={x[1] for x in nf}
    ap={x[0] for x in nf if x[1]=='anchored_rule'}
    anch_edges+=sum(1 for x in nf if x[1]=='anchored_rule')
    # conflicting parents (not the same) from anchored
    other={x[0] for x in nf if x[1]!='anchored_rule'}
    if srcs=={'anchored_rule'}: only_anch+=1
    # at most one correct parent: wrong >= distinct nonfemale parents -1 among anchored if non-anchored exist then all anchored differing from them wrong
    pset={x[0] for x in nf}
    if other:
        lower_bound_wrong+=len(ap-other)
    else:
        lower_bound_wrong+=len(ap)-1
print('only_anchored_children',only_anch,'anchored edges in groups',anch_edges,'lower bound wrong anchored parent ids',lower_bound_wrong)
anch=[r for r in rows if r['source']=='anchored_rule']
print('anchored rows',len(anch))
for c,v in sorted(multi.items(), key=lambda kv:-len(kv[1]))[:12]:
    print(c,[(p,s,rel,pid,vv) for p,s,rel,pid,vv in v])
