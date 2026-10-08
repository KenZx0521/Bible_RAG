"""E0b: the backend encodes with the pinned tokenizers and will not start otherwise.

BGE-M3 (SentenceTransformer) and the reranker swap their AutoTokenizer for
ragcommon.encoder's pinned tokenizer.json (G28). A tokenizer that fails its
contract fails init, and with it the app's startup, before any store is opened.
"""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import sentence_transformers
import torch
from transformers import PreTrainedTokenizerFast

import main
from config import settings
from serving import startup
from ragcommon import encoder
from ragcommon.encoder import EncoderContractError
from utils import embedder, reranker

M3_FILE = (Path(os.environ.get("HF_HOME", "/mnt/ollama-data/huggingface")) / "hub"
           / "models--BAAI--bge-m3" / "snapshots" / encoder.BGE_M3.revision / "tokenizer.json")
RERANKER_FILE = (Path("/mnt/ollama-data/bible_rag_store/models/bge-reranker-v2-m3")
                 / encoder.RERANKER.revision / "tokenizer.json")

pytestmark = pytest.mark.skipif(
    not (M3_FILE.is_file() and RERANKER_FILE.is_file()),
    reason="pinned tokenizer.json files are not on this machine",
)


def _hub(root: Path, main_refs: dict | None = None, files: dict | None = None) -> Path:
    """An HF cache holding both pinned snapshots (tokenizer.json only)."""
    hub = root / "hub"
    for spec, source in ((encoder.BGE_M3, M3_FILE), (encoder.RERANKER, RERANKER_FILE)):
        repo = hub / ("models--" + spec.repo_id.replace("/", "--"))
        snapshot = repo / "snapshots" / spec.revision
        snapshot.mkdir(parents=True)
        (snapshot / "tokenizer.json").symlink_to((files or {}).get(spec.name, source))
        (repo / "refs").mkdir()
        (repo / "refs" / "main").write_text((main_refs or {}).get(spec.name, spec.revision))
    return hub


class _FakeSentenceTransformer:
    built: list = []

    def __init__(self, name, device=None):
        _FakeSentenceTransformer.built.append(name)
        self.tokenizer = "auto tokenizer"


class _FakeSequenceClassifier:
    """Records each batch of input_ids the reranker feeds it."""

    def __init__(self):
        self.batches = []

    def to(self, device):
        return self

    def eval(self):
        return self

    def __call__(self, input_ids, attention_mask, return_dict):
        self.batches.append(input_ids.tolist())
        return SimpleNamespace(logits=torch.zeros(len(input_ids), 1))


@pytest.fixture
def models(monkeypatch, tmp_path):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _FakeSentenceTransformer)
    monkeypatch.setattr(_FakeSentenceTransformer, "built", [])
    classifier = _FakeSequenceClassifier()
    monkeypatch.setattr(reranker, "AutoModelForSequenceClassification",
                        SimpleNamespace(from_pretrained=lambda name, **kw: classifier))
    for module in (embedder, reranker):
        monkeypatch.setattr(module, "_model", None)
        monkeypatch.setattr(module, "_fingerprint", None)
    monkeypatch.setattr(reranker, "_tokenizer", None)
    return SimpleNamespace(classifier=classifier, root=tmp_path)


def _use(monkeypatch, hub: Path) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))


# --- embedder -----------------------------------------------------------------

def test_embedder_encodes_with_the_pinned_tokenizer(models, monkeypatch):
    _use(monkeypatch, _hub(models.root))

    embedder.init_model()

    assert isinstance(embedder._model.tokenizer, PreTrainedTokenizerFast)
    assert embedder.get_fingerprint()["probe_ids_sha"] == encoder.BGE_M3.probe_ids_sha


def test_embedder_refuses_a_snapshot_other_than_the_pinned_one(models, monkeypatch):
    _use(monkeypatch, _hub(models.root, main_refs={"bge-m3": "9a0624b896d81da7492a910ffa53731274b6cf3d"}))

    with pytest.raises(EncoderContractError, match="refs/main"):
        embedder.init_model()
    assert embedder._model is None and embedder.get_fingerprint() is None


def test_embedder_refuses_a_tokenizer_file_with_another_sha(models, monkeypatch):
    _use(monkeypatch, _hub(models.root, files={"bge-m3": RERANKER_FILE}))

    with pytest.raises(EncoderContractError, match="sha256"):
        embedder.init_model()
    assert embedder._model is None


def test_embedder_refuses_an_unpinned_model_before_loading_it(models, monkeypatch):
    _use(monkeypatch, _hub(models.root))
    monkeypatch.setattr(settings, "embedding_model", "BAAI/bge-large-zh-v1.5")

    with pytest.raises(EncoderContractError, match="pinned"):
        embedder.init_model()
    assert _FakeSentenceTransformer.built == []


# --- reranker -----------------------------------------------------------------

def test_reranker_pairs_carry_the_double_separator(models, monkeypatch):
    _use(monkeypatch, _hub(models.root))
    reranker.init_reranker()

    reranker.rerank("誰說：「要有光」？", [{"content": "神說：「要有光」，就有了光。"}, {"content": "（創1‧3）"}])

    [batch] = models.classifier.batches
    assert all(any(a == b == 2 for a, b in zip(ids, ids[1:])) for ids in batch)
    assert not any(3 in ids for ids in batch)  # no <unk> from full-width punctuation
    assert reranker.get_fingerprint()["probe_ids_sha"] == encoder.RERANKER.probe_ids_sha


def test_reranker_refuses_a_tokenizer_file_with_another_sha(models, monkeypatch):
    _use(monkeypatch, _hub(models.root, files={"bge-reranker-v2-m3": M3_FILE}))

    with pytest.raises(EncoderContractError, match="sha256"):
        reranker.init_reranker()
    assert reranker._model is None and reranker.get_fingerprint() is None


def test_reranker_refuses_an_unpinned_model(models, monkeypatch):
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-large")

    with pytest.raises(EncoderContractError, match="pinned"):
        reranker.init_reranker()


# --- app startup -------------------------------------------------------------------

async def _start_app():
    async with main.lifespan(main.app):
        pass


def test_app_startup_fails_when_the_encoder_contract_fails(models, monkeypatch):
    _use(monkeypatch, _hub(models.root, files={"bge-m3": RERANKER_FILE}))
    reached = []

    async def run(fingerprints):
        reached.append(fingerprints)

    monkeypatch.setattr(startup, "run", run)

    with pytest.raises(EncoderContractError):
        asyncio.run(_start_app())
    assert reached == []  # no store is touched before the models pass their contract
