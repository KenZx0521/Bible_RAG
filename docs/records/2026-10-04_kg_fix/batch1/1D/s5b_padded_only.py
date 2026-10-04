"""S5b: frozen-table resolution applied ONLY to rows whose CKIP surface was padded
(what 1C's normalize_surface changes). Expect: twin merges only; 0 renames; 0 new homophone merges."""
import sys, json
from collections import Counter, defaultdict
sys.path.insert(0, '.'); sys.path.insert(0, '/home/kenzx0521/Bible_RAG/scripts')
from ro import OUT, jsonl, dump
from s1_whitespace import norm, mint
from s5_id_resolution import frozen_id, live, ner_types
from entity_extraction.entity_dict import find_canonical_name
cat = Counter(); ids_after = defaultdict(set); old_ids = set(); naive_cat = Counter()
for m in jsonl(OUT / "ner_mentions.jsonl"):
    O = m["entity_id"]; t, _ = ner_types[O]; raw = m["text_span"]; span = norm(raw)
    c = find_canonical_name(span, t)
    if span != raw:
        X = frozen_id(t, c) or mint(t, c)
        N = mint(t, c)
    else:
        X = O; N = O   # unchanged minting path
    old_ids.add(O)
    ids_after[X].add(norm(c))
    if X != O:
        cat["moved_" + ("to_clean_twin" if X in live and not any(ch.isspace() for ch in X) else "other")] += 1
    if N != O:
        naive_cat["naive_moved_" + ("existing" if N in live else "new_id")] += 1
gone = old_ids - set(ids_after)
res = {"moves": dict(cat), "naive_moves": dict(naive_cat), "old_ids_gone": len(gone),
       "gone_all_have_clean_twin": all(frozen_id(ner_types[g][0], norm(ner_types[g][1])) not in (None, g) for g in gone),
       "entities_after": len(ids_after)}
print(json.dumps(res, ensure_ascii=False))
dump("s5b_padded_only.json", res)
