import sys
from pathlib import Path

import pytest

# Backend modules import each other as top-level packages (`from config import
# settings`, `from utils...`), the same way uvicorn runs them from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# ragcommon lives in packages/; the image puts it on PYTHONPATH, a bare
# `pytest backend/tests` does not.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))


@pytest.fixture
def active():
    """A served build with the router_fakes lexicon (v2) and the router_fakes.EVENT registry."""
    from router_fakes import EVENT, LEXICON
    from serving import context
    from serving.build import Build
    from serving.handshake import Handshake

    build = Build("b20261008_1bb6912e", "bb20261008_1bb6912e", "passages__b", Path("/c"), False, 9)
    context.install(context.make_active(build, LEXICON, (EVENT,)),
                    Handshake(build.build_id, (), True))
    yield
    context.reset()


@pytest.fixture
def scores(monkeypatch):
    """rerank_score = table[id] (0.5 when absent), sorted like the real reranker."""
    from utils import reranker

    table = {}

    def rerank(query, passages, top_k=5, text_key="content"):
        for p in passages:
            p["rerank_score"] = table.get(p["id"], 0.5)
        return sorted(passages, key=lambda p: p["rerank_score"], reverse=True)[:top_k]

    monkeypatch.setattr(reranker, "rerank", rerank)
    return table
