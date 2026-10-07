"""ragcommon.encoder: one pinned tokenizer path for build and services (G28).

Runs under every venv that encodes text (backend transformers 5.0.0, scripts
5.3.0, evaluation 4.57.6): the pinned probe_ids_sha must come out the same.
Contract failures are exercised on small synthetic tokenizers; the real
tokenizer.json files are only needed for the pinned-fingerprint tests.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from tokenizers import Regex, Tokenizer, models, pre_tokenizers, processors

from ragcommon import encoder
from ragcommon.encoder import EncoderContractError, EncoderSpec

ROOT = Path(__file__).resolve().parents[3]
HF_HUB = Path(os.environ.get("HF_HOME", "/mnt/ollama-data/huggingface")) / "hub"
M3_FILE = (HF_HUB / "models--BAAI--bge-m3" / "snapshots" / encoder.BGE_M3.revision
           / "tokenizer.json")
RERANKER_FILE = (Path("/mnt/ollama-data/bible_rag_store/models/bge-reranker-v2-m3")
                 / encoder.RERANKER.revision / "tokenizer.json")
REAL_FILES = {encoder.BGE_M3.name: M3_FILE, encoder.RERANKER.name: RERANKER_FILE}
VENVS = ("backend", "scripts", "evaluation")

needs_real_files = pytest.mark.skipif(
    not all(p.is_file() for p in REAL_FILES.values()),
    reason="pinned tokenizer.json files are not on this machine",
)

GOOD_PAIR = "<s> $A </s> </s> $B </s>"
CHARS = "問題段落答案神愛世人騾子，。？！：；（）‧"


def _write_tokenizer(path: Path, chars: str = CHARS, pair: str = GOOD_PAIR) -> Path:
    vocab = {"<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3, "<mask>": 4}
    vocab.update({ch: i for i, ch in enumerate(dict.fromkeys(chars), start=len(vocab))})
    tok = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Split(Regex("."), behavior="isolated")
    tok.post_processor = processors.TemplateProcessing(
        single="<s> $A </s>", pair=pair, special_tokens=[("<s>", 0), ("</s>", 2)],
    )
    tok.save(str(path))
    return path


def _spec(path: Path, **overrides) -> EncoderSpec:
    fields = dict(
        name="toy", repo_id="org/toy", revision="r" * 40,
        tokenizer_sha256=encoder.file_sha256(path), probe_ids_sha="",
        probes=("神愛世人。", "騾子？"), pair_probes=(("問題", "段落"),),
    )
    return EncoderSpec(**{**fields, **overrides})


def _hub(tmp_path: Path, spec: EncoderSpec, main: str, source: Path) -> Path:
    repo = tmp_path / "hub" / ("models--" + spec.repo_id.replace("/", "--"))
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text(main)
    snapshot = repo / "snapshots" / spec.revision
    snapshot.mkdir(parents=True)
    (snapshot / "tokenizer.json").write_bytes(source.read_bytes())
    return tmp_path / "hub"


# --- loading ------------------------------------------------------------------

def test_load_rejects_a_tokenizer_file_with_another_sha(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json")

    with pytest.raises(EncoderContractError, match="sha256"):
        encoder.load_tokenizer(path, "0" * 64)


def test_load_rejects_a_missing_file(tmp_path):
    with pytest.raises(EncoderContractError, match="not found"):
        encoder.load_tokenizer(tmp_path / "tokenizer.json", "0" * 64)


def test_loaded_tokenizer_knows_the_xlmr_special_tokens(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json")

    tok = encoder.load_tokenizer(path, encoder.file_sha256(path))

    assert (tok.bos_token_id, tok.pad_token_id, tok.sep_token_id, tok.unk_token_id) == (0, 1, 2, 3)
    assert tok(["神", "神愛"], padding=True)["input_ids"][0][-1] == tok.pad_token_id


# --- fingerprint --------------------------------------------------------------

def test_fingerprint_reports_sha_ids_unk_and_pair_template(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json", chars=CHARS.replace("騾", ""))
    spec = _spec(path)
    tok = encoder.load_tokenizer(path, spec.tokenizer_sha256)

    fp = encoder.fingerprint(tok, spec.tokenizer_sha256, spec.probes, spec.pair_probes)

    assert set(fp) == {"tokenizer_sha", "probe_ids_sha", "unk_count", "pair_template_ok"}
    assert fp["tokenizer_sha"] == spec.tokenizer_sha256
    assert fp["unk_count"] == 1  # 騾 is out of vocabulary: reported, not fatal
    assert fp["pair_template_ok"] is True
    assert len(fp["probe_ids_sha"]) == 64
    other = encoder.fingerprint(tok, spec.tokenizer_sha256, ("神愛世人！",), spec.pair_probes)
    assert other["probe_ids_sha"] != fp["probe_ids_sha"]


@pytest.mark.parametrize("missing", list("，。？！：；（）‧"))
def test_fingerprint_rejects_full_width_punctuation_as_unk(tmp_path, missing):
    path = _write_tokenizer(tmp_path / "tokenizer.json", chars=CHARS.replace(missing, ""))
    spec = _spec(path)
    tok = encoder.load_tokenizer(path, spec.tokenizer_sha256)

    with pytest.raises(EncoderContractError, match="<unk>"):
        encoder.fingerprint(tok, spec.tokenizer_sha256, spec.probes, spec.pair_probes)


def test_fingerprint_rejects_a_single_separator_pair_template(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json", pair="<s> $A </s> $B </s>")
    spec = _spec(path)
    tok = encoder.load_tokenizer(path, spec.tokenizer_sha256)

    with pytest.raises(EncoderContractError, match="pair template"):
        encoder.fingerprint(tok, spec.tokenizer_sha256, spec.probes, spec.pair_probes)


def test_fingerprint_needs_a_pair_probe(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json")
    spec = _spec(path)
    tok = encoder.load_tokenizer(path, spec.tokenizer_sha256)

    with pytest.raises(EncoderContractError, match="pair probe"):
        encoder.fingerprint(tok, spec.tokenizer_sha256, spec.probes, ())


# --- pinned specs -------------------------------------------------------------

@pytest.mark.parametrize("spec", [encoder.BGE_M3, encoder.RERANKER], ids=lambda s: s.name)
def test_probe_sets_cover_the_forms_that_broke(spec):
    texts = "".join(spec.probes) + "".join(a + b for a, b in spec.pair_probes)

    assert set("，。？！：；（）‧") <= set(texts)
    assert "29-30" in texts and "騾" in texts


def test_probe_set_sizes():
    assert len(encoder.BGE_M3.probes) >= 20
    assert len(encoder.RERANKER.pair_probes) >= 10


@needs_real_files
@pytest.mark.parametrize("spec", [encoder.BGE_M3, encoder.RERANKER], ids=lambda s: s.name)
def test_real_tokenizer_matches_its_pinned_fingerprint(spec):
    _, fp = encoder.load_pinned(spec, tokenizer_file=REAL_FILES[spec.name])

    assert fp["probe_ids_sha"] == spec.probe_ids_sha
    assert fp["tokenizer_sha"] == spec.tokenizer_sha256


def test_load_pinned_rejects_ids_that_drifted(tmp_path):
    path = _write_tokenizer(tmp_path / "tokenizer.json")
    spec = _spec(path, probe_ids_sha="f" * 64)

    with pytest.raises(EncoderContractError, match="probe_ids_sha"):
        encoder.load_pinned(spec, tokenizer_file=path)


_PRINT_FINGERPRINTS = (
    "import json; from ragcommon import encoder\n"
    "files = json.loads(input())\n"
    "print(json.dumps({s.name: encoder.load_pinned(s, tokenizer_file=files[s.name])[1]['probe_ids_sha']"
    " for s in (encoder.BGE_M3, encoder.RERANKER)}))\n"
)


@needs_real_files
def test_every_venv_produces_the_same_probe_ids():
    pythons = [ROOT / v / ".venv" / "bin" / "python" for v in VENVS]
    pythons = [p for p in pythons if p.exists()]
    if len(pythons) < 2:
        pytest.skip("needs at least two of the backend/scripts/evaluation venvs")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "packages"), "HF_HUB_OFFLINE": "1"}
    files = json.dumps({name: str(path) for name, path in REAL_FILES.items()})

    outputs = {
        str(py): subprocess.run([str(py), "-c", _PRINT_FINGERPRINTS], input=files, env=env,
                                capture_output=True, text=True, check=True).stdout.strip()
        for py in pythons
    }

    expected = {s.name: s.probe_ids_sha for s in (encoder.BGE_M3, encoder.RERANKER)}
    assert {k: json.loads(v) for k, v in outputs.items()} == {k: expected for k in outputs}


# --- HF cache resolution --------------------------------------------------------

def test_pinned_file_comes_from_the_snapshot_main_points_to(tmp_path):
    source = _write_tokenizer(tmp_path / "src.json")
    spec = _spec(source)
    hub = _hub(tmp_path, spec, spec.revision, source)

    path = encoder.pinned_tokenizer_file(spec, hub)

    assert path == hub / "models--org--toy" / "snapshots" / spec.revision / "tokenizer.json"


def test_pinned_file_refuses_when_main_moved(tmp_path):
    source = _write_tokenizer(tmp_path / "src.json")
    spec = _spec(source)
    hub = _hub(tmp_path, spec, "a" * 40, source)

    with pytest.raises(EncoderContractError, match="refs/main"):
        encoder.pinned_tokenizer_file(spec, hub)


def test_pinned_file_refuses_an_uncached_model(tmp_path):
    spec = _spec(_write_tokenizer(tmp_path / "src.json"))

    with pytest.raises(EncoderContractError, match="refs/main"):
        encoder.pinned_tokenizer_file(spec, tmp_path / "empty-hub")


def test_load_pinned_resolves_through_the_hub_cache(tmp_path):
    source = _write_tokenizer(tmp_path / "src.json")
    draft = _spec(source)
    tok = encoder.load_tokenizer(source, draft.tokenizer_sha256)
    probe_sha = encoder.fingerprint(tok, "", draft.probes, draft.pair_probes)["probe_ids_sha"]
    spec = _spec(source, probe_ids_sha=probe_sha)
    hub = _hub(tmp_path, spec, spec.revision, source)

    tok, fp = encoder.load_pinned(spec, hub_cache=hub)

    assert fp["probe_ids_sha"] == probe_sha and tok.unk_token_id == 3


@pytest.mark.parametrize(("env", "expected"), [
    ({"HF_HUB_CACHE": "/a/hub", "HF_HOME": "/b"}, "/a/hub"),
    ({"HF_HOME": "/b", "XDG_CACHE_HOME": "/c"}, "/b/hub"),
    ({"XDG_CACHE_HOME": "/c"}, "/c/huggingface/hub"),
])
def test_hub_cache_follows_the_hf_environment(env, expected):
    assert encoder.hub_cache_dir(env) == Path(expected)


def test_hub_cache_defaults_to_the_home_cache():
    assert encoder.hub_cache_dir({}) == Path.home() / ".cache" / "huggingface" / "hub"


def test_model_name_must_be_the_pinned_repo():
    encoder.check_model_name(encoder.BGE_M3, "BAAI/bge-m3")

    with pytest.raises(EncoderContractError, match="pinned"):
        encoder.check_model_name(encoder.BGE_M3, "BAAI/bge-large-zh")
