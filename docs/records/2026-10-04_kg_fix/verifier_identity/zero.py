import sys, glob
sys.path.insert(0,'/home/kenzx0521/Bible_RAG/scripts')
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
txt=''.join(open(f,encoding='utf-8').read() for f in glob.glob('/home/kenzx0521/Bible_RAG/bible_md/**/*.md',recursive=True))
print(len(txt))
for t,d in [('Person',PERSON_DICT),('Place',PLACE_DICT),('Group',GROUP_DICT)]:
    z=sorted({a for c,al in d.items() for a in al if txt.count(a)==0})
    print(t,len(z),z)
for w in ['撒馬利亞','塞魯士','凱撒利亞','泰爾','本丟‧彼拉多','西門‧彼得','客西馬尼','巴旦‧亞蘭','尼哥德慕','呂便','流便','西庇太的兒子雅各','亞勒腓的兒子雅各','奮銳黨的西門','加略人猶大']:
    print(w, txt.count(w))
