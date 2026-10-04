"""Wave 2 effect on relations: 1A-clean edges re-gated with post-1C/1D MENTIONS and id remaps."""
import sys, os, pickle, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); kg = g["kg"]
clean = pickle.load(open(f"{D}/sim1a_clean.pkl", "rb"))["clean"]
s = pickle.load(open(f"{D}/sim1c1d.pkl", "rb"))
for stage, rows, rm in (("1C", s["after1c"], s["remap"]), ("1C+1D", s["after1d"], {**s["remap"], **s["remap_d"]})):
    sup = {(kg.chunk_parent.get(sid, sid) if lab == "Chunk" else sid, eid) for (lab, sid, eid, *_ ) in rows}
    dele = s["delete"] if stage == "1C+1D" else set()
    out, drop, ws = [], collections.Counter(), 0
    for r in clean:
        h, t = rm.get(r["head"], r["head"]), rm.get(r["tail"], r["tail"])
        ws += (h != r["head"]) or (t != r["tail"])
        if h in dele or t in dele: drop["endpoint_deleted"] += 1; continue
        if r["extraction_phase"] != 3 and not ((r["source_pericope_id"], h) in sup and (r["source_pericope_id"], t) in sup):
            drop["provenance_gate"] += 1; continue
        out.append((h, r["type"], t))
    dedup = len(set(out))
    print(stage, "1A-clean", len(clean), "-> kept", len(out), "unique", dedup, dict(drop), "endpoint remapped:", ws)
