import json,re,collections,sys
S=sys.argv[1]
raw=open(S+'/live_events.json').read()
try: rows=json.loads(raw)
except Exception:
    rows=json.loads(raw[raw.index('['):])
print('rows',len(rows))
from importlib import util
sys.path.insert(0,'scripts')
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
names=set()
for d in (PERSON_DICT,PLACE_DICT,GROUP_DICT):
    for k,v in d.items(): names.add(k); names.update(v)
RULES=[
 ('mangled_xref', lambda n: n.startswith(('（','(','－','-')) or n.endswith('；約') ),
 ('dirty_whitespace', lambda n: n!=n.strip() or ' ' in n),
 ('person_or_place_or_group_name', lambda n: n.strip() in names),
 ('king_title', lambda n: re.match(r'^(猶大|以色列|亞蘭|埃及|巴比倫|波斯|亞述)王',n) is not None),
 ('genealogy_list', lambda n: re.search(r'(後代|後裔|子孫|家譜|族譜|名單|數點|人數|宗族|族長|支派的|首領|邊界|地業|分地|城邑|祭司的班次|利未人的|統計)',n) is not None),
 ('law_regulation', lambda n: re.search(r'(條例|律例|法則|規例|的例|規則|規定|條規|典章|律法)',n) is not None),
 ('psalm_prayer_hymn', lambda n: re.search(r'(求主|禱告|祈禱|頌讚|讚美|稱頌|之歌|的歌|的詩|詩歌|聖詩|哀歌|感恩|信靠|求救|求助|祈求|頌)',n) is not None),
 ('oracle_prophecy', lambda n: re.search(r'(預言|責備|警告|異象|默示|神諭|的審判|受罰|刑罰|懲罰|有禍|災禍|將來|未來)',n) is not None),
 ('epistolary_teaching', lambda n: re.search(r'(問安|問候|結語|引言|序言|勸勉|勉勵|祝福|祝禱|教導|教訓|忠告|訓誨|勸|論|比喻|箴言)',n) is not None or n.startswith('論')),
]
cat=collections.Counter(); ex=collections.defaultdict(list); single=collections.Counter()
for r in rows:
    n=r['n']; c='narrative_or_other'
    for name,f in RULES:
        if f(n): c=name; break
    cat[c]+=1; ex[c].append(n)
    if r['k']==1: single[c]+=1
for c,v in cat.most_common(): print(f'{c:32s} {v:5d}  single-pericope={single[c]}  e.g. {ex[c][:12]}')
json.dump(ex, open(S+'/event_categories.json','w'), ensure_ascii=False, indent=0)
