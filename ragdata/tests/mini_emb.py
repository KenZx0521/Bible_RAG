"""Build the mini emb layer with the stand-in encoder, and the old output/ it is checked against.

The legacy directory holds three old records whose text is word for word a mini
record text (so the compatibility sample of 3 finds its twins) and one old
template text that has no twin, with the stand-in vectors of their texts.
"""

from __future__ import annotations

import json
from pathlib import Path

import fake_encoder
import mini_build
from ragdata.stages.s06_emb.build import EmbInputs, build_emb

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
SAMPLE = 3
LEGACY = {
    "psa:42:0:v:1": mini_build.VERSE_EMBED["vs:psa.42.1"],
    "eph:6:0:v:2-3": mini_build.VERSE_EMBED["vs:eph.6.2-3"],
    "eph:6:0": mini_build.EMBED["ps:eph.6.1"],
    "act:10:0:v:1": "使徒行傳 第10章 (無標題) 第1節：在凱撒利亞有一個人名叫哥尼流。",
}


def legacy_dir(root: Path, texts: dict[str, str] = LEGACY) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    queue = [{"id": i, "type": "verse", "text": t} for i, t in texts.items()]
    vecs = [{"id": i, "type": "verse", "embedding": fake_encoder.vector(t).tolist()}
            for i, t in texts.items()]
    for name, rows in (("embedding_queue.jsonl", queue), ("embeddings.jsonl", vecs)):
        (root / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                 encoding="utf-8")
    return root


def inputs(root: Path, **changes) -> EmbInputs:
    fields = {"legacy_dir": legacy_dir(root / "legacy"), "compat_sample": SAMPLE,
              "encoder": fake_encoder.make()}
    return EmbInputs(**{**fields, **changes})


def build(root: Path, store: str = "store", counts: Path = MINI_COUNTS, given=None, **changes):
    """(text, struct, BuildResult) of the mini layers in ``root/given`` and their emb build."""
    text, struct = given or mini_build.write_layers(root / "given")
    result = build_emb(struct.path, text.path, root / store, counts_path=counts,
                       inputs=inputs(root, **changes))
    return text, struct, result
