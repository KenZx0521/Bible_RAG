"""Read-only Neo4j helper: every session is opened with READ access mode."""
import os, json, sys
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS
load_dotenv('/home/kenzx0521/Bible_RAG/.env')
_drv = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
def q(cypher, **params):
    with _drv.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])
