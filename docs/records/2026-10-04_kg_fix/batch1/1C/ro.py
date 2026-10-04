"""Read-only Neo4j query helper: python ro.py prod|staging 'CYPHER'"""
import os, sys, json
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values("/home/kenzx0521/Bible_RAG/.env")
target = sys.argv[1]
uri = "bolt://localhost:7687" if target == "prod" else "bolt://localhost:7688"
user = env.get("NEO4J_USER", "neo4j")
pw = env.get("NEO4J_PASSWORD") if target == "prod" else os.environ.get("NEO4J_PASSWORD", env.get("NEO4J_PASSWORD", "neo4j_password"))
def run(q):
    d = GraphDatabase.driver(uri, auth=(user, pw))
    with d.session(default_access_mode=READ_ACCESS) as s:
        rows = [r.data() for r in s.run(q)]
    d.close()
    return rows
if __name__ == "__main__":
    for r in run(sys.argv[2]):
        print(json.dumps(r, ensure_ascii=False))
