import json, re
SP='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/'
m="利未記=lev 民數記=num 申命記=deu 約書亞記=jos 士師記=jdg 路得記=rut 撒母耳記上=1sa 撒母耳記下=2sa 列王紀上=1ki 列王紀下=2ki 歷代志上=1ch 歷代志下=2ch 以斯拉記=ezr 尼希米記=neh 以斯帖記=est 約伯記=job 詩篇=psa 箴言=pro 傳道書=ecc 雅歌=sng 以賽亞書=isa 耶利米書=jer 耶利米哀歌=lam 以西結書=ezk 但以理書=dan 何西阿書=hos 約珥書=jol 阿摩司書=amo 俄巴底亞書=oba 約拿書=jon 彌迦書=mic 那鴻書=nam 哈巴谷書=hab 西番雅書=zep 哈該書=hag 撒迦利亞書=zec 瑪拉基書=mal 馬太福音=mat 馬可福音=mrk 路加福音=luk 約翰福音=jhn 使徒行傳=act 羅馬書=rom 哥林多前書=1co 哥林多後書=2co 加拉太書=gal 以弗所書=eph 腓立比書=php 歌羅西書=col 帖撒羅尼迦前書=1th 帖撒羅尼迦後書=2th 提摩太前書=1ti 提摩太後書=2ti 提多書=tit 腓利門書=phm 希伯來書=heb 雅各書=jas 彼得前書=1pe 彼得後書=2pe 約翰一書=1jn 約翰二書=2jn 約翰三書=3jn 猶大書=jud 啟示錄=rev 創世記=gen 出埃及記=exo"
B=dict(x.split('=') for x in m.split())
names=sorted(B,key=len,reverse=True)
def parse(ref):
    segs=[]; book=None
    for part in re.split(r'[;；]',ref):
        part=part.strip()
        if not part: continue
        for n in names:
            if part.startswith(n):
                book=B[n]; part=part[len(n):].strip(); break
        # chapter forms
        mm=re.fullmatch(r'(\d+)(?:-(\d+))?章',part)
        if mm:
            c0=int(mm.group(1)); c1=int(mm.group(2) or c0)
            for c in range(c0,c1+1): segs.append((book,c,1,999))
            continue
        mm=re.fullmatch(r'(\d+):(.+)',part)
        if mm:
            c=int(mm.group(1)); rest=mm.group(2)
            for piece in re.split(r'[,，]',rest):
                piece=piece.strip()
                if ':' in piece:  # new chapter inside list
                    c,piece=piece.split(':'); c=int(c)
                a=piece.split('-'); v0=int(a[0]); v1=int(a[1]) if len(a)>1 else v0
                segs.append((book,c,v0,v1))
            continue
        raise ValueError((ref,part))
    return segs
t=json.load(open(SP+'kg_xref/sel.json'))
rows=[]
for x in t:
    for s in parse(x['reference']):
        rows.append({'qid':x['qid'],'b':s[0],'c':s[1],'v0':s[2],'v1':s[3]})
json.dump(rows,open(SP+'kg_xref/segs.json','w'),ensure_ascii=False)
print(len(rows)); print(json.dumps(rows))
