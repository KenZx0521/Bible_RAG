import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import os, json
from dotenv import load_dotenv
load_dotenv(BIBLE_RAG_ROOT + '/.env')
import psycopg2
c=psycopg2.connect(host=os.getenv("POSTGRES_HOST","localhost"),port=int(os.getenv("POSTGRES_PORT","5432")),dbname=os.getenv("POSTGRES_DB","bible_rag"),user=os.getenv("POSTGRES_USER","bible"),password=os.getenv("POSTGRES_PASSWORD"))
c.set_session(readonly=True)
cur=c.cursor()
cur.execute("SELECT id, content FROM pericopes WHERE id = ANY(%s)", (['gen:1:0','gen:11:3','1ch:2:4'],))
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
for i,t in cur.fetchall():
    print(i, repr(t[:120]), 'same_as_jsonl=', t==P.get(i))
cur.execute("SELECT count(*) FROM pericopes"); print(cur.fetchone())
# compare all
cur.execute("SELECT id, content FROM pericopes"); diff=0; n=0
for i,t in cur.fetchall():
    n+=1
    if P.get(i)!=t: diff+=1
print('pg rows',n,'diff from jsonl',diff)
