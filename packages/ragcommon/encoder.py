"""Pinned BGE-M3 / reranker tokenizers shared by the build pipeline and services.

G28: transformers 5.0.0's AutoTokenizer path for these models skips the NFKC
normaliser (full-width punctuation becomes <unk>) and builds pairs with a single
</s>, while 5.3.0 (index side) is correct. Loading the snapshot's tokenizer.json
as PreTrainedTokenizerFast gives identical ids under both. This module pins that
file by sha256 and fingerprints the ids of fixed probes; every check raises
EncoderContractError instead of degrading.

Depends only on transformers (and its tokenizers backend).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from transformers import PreTrainedTokenizerFast

# XLM-R special tokens; both pinned tokenizers use this vocabulary layout.
XLMR_SPECIAL_TOKENS = MappingProxyType({
    "bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>", "pad_token": "<pad>",
    "cls_token": "<s>", "sep_token": "</s>", "mask_token": "<mask>",
})
SEP_ID = 2  # </s>; an XLM-R pair is <s> A </s></s> B </s>
FULLWIDTH_PUNCTUATION = "，。？！：；（）‧"


class EncoderContractError(RuntimeError):
    """A tokenizer does not match its pinned encoder contract."""


@dataclass(frozen=True)
class EncoderSpec:
    name: str
    repo_id: str
    revision: str  # HF snapshot the model loads from (refs/main)
    tokenizer_sha256: str
    probe_ids_sha: str  # pinned from the index side (transformers 5.3.0)
    probes: tuple[str, ...]
    pair_probes: tuple[tuple[str, str], ...]


BGE_M3_PROBES = (
    "約翰福音3:16說了什麼？",
    "創世記 第1章 神的創造 (1-31節)：起初，神創造天地。",
    "以賽亞書 第9章 和平的君 (6-7節)：",
    "撒母耳記上 第17章 大衛殺歌利亞 第49節：",
    "列王紀上 第4章 所羅門的智慧 第29-30節：",
    "羅馬書8章29-30節講預定與呼召嗎？",
    "馬太福音 第5章 論福 (3-12節)：「虛心的人有福了！因為天國是他們的。」",
    "哈薩‧書亞與示他‧波斯乃在哪裡？",
    "巴力‧免的意思是什麼？",
    "施洗約翰傳道（太3‧1－12）",
    "騾子與稗子有什麼不同？",
    "鴟鴞、鸕鶿和鷺鷥是潔淨的嗎？",
    "（大衛的詩，交與聖詠團長。）",
    "摩西說：「你們要記念這日！」",
    "誰是麥基洗德？",
    "以色列的支派：流便；西緬；利未；猶大。",
    "保羅歸主的經過？",
    "挪亞方舟（創世記6-9章）有多大？",
    "以斯帖記4:14「焉知你得了王后的位分不是為現今的機會呢？」",
    "詩篇23篇1-6節：耶和華是我的牧者",
    "撒迦利亞書的預言如何在受難週應驗？",
    "ＡＢＣ１２３：全形英數；半形 abc 123!",
    "主啊，你往哪裡去？",
    "約伯記 第42章 約伯復興 (10-17節)：耶和華使約伯從苦境轉回。",
)

RERANKER_PAIR_PROBES = (
    ("耶穌在哪裡出生？", "路加福音 第2章 耶穌降生 (1-7節)：她生了頭胎兒子，用布包起來，放在馬槽裡。"),
    ("大衛如何打敗歌利亞？", "撒母耳記上 第17章 大衛殺歌利亞 (41-54節)：大衛用手從袋中取出一塊石子來，用機弦甩去。"),
    ("約翰福音3:16說什麼？", "神愛世人，甚至將他的獨生子賜給他們，叫一切信他的，不致滅亡，反得永生。"),
    ("八福是哪些？", "馬太福音 第5章 論福 (3-12節)：「虛心的人有福了！因為天國是他們的。」"),
    ("保羅在哪裡歸主？", "使徒行傳 第9章 掃羅歸主 (1-19節)：掃羅行路，將到大馬士革，忽然從天上發光。"),
    ("哈薩‧書亞屬於哪一支派？", "約書亞記 第15章 猶大支派的地業：哈薩‧書亞、比伊斯拉。"),
    ("騾子在聖經哪裡出現？", "押沙龍騎着騾子，從大橡樹密枝底下經過。"),
    ("詩篇23篇的主題？", "（大衛的詩。）耶和華是我的牧者，我必不致缺乏。"),
    ("五旬節發生了什麼事；", "使徒行傳 第2章 聖靈降臨 (1-13節)：五旬節到了，門徒都聚集在一處。"),
    ("所羅門的智慧有多大？", "列王紀上 第4章 所羅門的智慧 第29-30節：神賜給所羅門極大的智慧聰明。"),
    ("十誡的第一條是什麼？", "出埃及記 第20章 十誡 (1-17節)：「除了我以外，你不可有別的神。」"),
    ("施洗約翰在哪裡傳道？", "（太3‧1－12）那時，施洗約翰出來，在猶太的曠野傳道！"),
)

BGE_M3 = EncoderSpec(
    name="bge-m3",
    repo_id="BAAI/bge-m3",
    revision="5617a9f61b028005a4858fdac845db406aefb181",
    tokenizer_sha256="21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
    probe_ids_sha="a0e8db608c923b243d6909dfa38d915989863349eadb2532dad262c106b8be3a",
    probes=BGE_M3_PROBES,
    pair_probes=RERANKER_PAIR_PROBES[:2],
)

RERANKER = EncoderSpec(
    name="bge-reranker-v2-m3",
    repo_id="BAAI/bge-reranker-v2-m3",
    revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    tokenizer_sha256="69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15",
    probe_ids_sha="0e7683debf6b3b5061e0c3cad60aea8fb1078d1b742d6e74595e38dfbae86b22",
    probes=(),
    pair_probes=RERANKER_PAIR_PROBES,
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_tokenizer(path: str | Path, expected_sha256: str) -> PreTrainedTokenizerFast:
    """Load tokenizer.json as PreTrainedTokenizerFast after checking its sha256."""
    path = Path(path)
    if not path.is_file():
        raise EncoderContractError(f"tokenizer.json not found: {path}")
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise EncoderContractError(f"{path}: sha256 {actual} != pinned {expected_sha256}")
    return PreTrainedTokenizerFast(tokenizer_file=str(path), **XLMR_SPECIAL_TOKENS)


def fingerprint(
    tokenizer: PreTrainedTokenizerFast,
    tokenizer_sha: str,
    probes: Sequence[str],
    pair_probes: Sequence[tuple[str, str]],
) -> dict:
    """{tokenizer_sha, probe_ids_sha, unk_count, pair_template_ok} of the probes.

    Raises when full-width punctuation encodes to <unk> or a pair lacks </s></s>.
    unk_count is report-only: rare characters (騾, 鴟) are <unk> in the XLM-R
    vocabulary under every version.
    """
    if not pair_probes:
        raise EncoderContractError("no pair probe: the pair template cannot be checked")
    unk_id = tokenizer.unk_token_id
    _check_punctuation(tokenizer, unk_id)
    single = [tokenizer(text)["input_ids"] for text in probes]
    pairs = [tokenizer(a, b)["input_ids"] for a, b in pair_probes]
    broken = [pair for pair, ids in zip(pair_probes, pairs) if not _has_double_sep(ids)]
    if broken:
        raise EncoderContractError(f"pair template lacks </s></s> for {broken[:3]}")
    payload = json.dumps({"single": single, "pair": pairs}, separators=(",", ":"))
    return {
        "tokenizer_sha": tokenizer_sha,
        "probe_ids_sha": hashlib.sha256(payload.encode()).hexdigest(),
        "unk_count": sum(ids.count(unk_id) for ids in single + pairs),
        "pair_template_ok": True,
    }


def _check_punctuation(tokenizer: PreTrainedTokenizerFast, unk_id: int) -> None:
    bad = [ch for ch in FULLWIDTH_PUNCTUATION
           if unk_id in tokenizer(ch, add_special_tokens=False)["input_ids"]]
    if bad:
        raise EncoderContractError(f"full-width punctuation encodes to <unk>: {''.join(bad)}")


def _has_double_sep(ids: Sequence[int]) -> bool:
    return any(a == SEP_ID and b == SEP_ID for a, b in zip(ids, ids[1:]))


def hub_cache_dir(env: Mapping[str, str] = os.environ) -> Path:
    """The HF hub cache directory, resolved the way huggingface_hub does."""
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"]).expanduser()
    if env.get("HF_HOME"):
        return Path(env["HF_HOME"]).expanduser() / "hub"
    cache_home = Path(env["XDG_CACHE_HOME"]) if env.get("XDG_CACHE_HOME") else Path.home() / ".cache"
    return cache_home.expanduser() / "huggingface" / "hub"


def pinned_tokenizer_file(spec: EncoderSpec, hub_cache: Path) -> Path:
    """tokenizer.json of the pinned snapshot, refusing when refs/main moved.

    Services load the model by repo id, i.e. from the snapshot refs/main names;
    the tokenizer must come from that same snapshot.
    """
    repo_dir = Path(hub_cache) / ("models--" + spec.repo_id.replace("/", "--"))
    ref = repo_dir / "refs" / "main"
    if not ref.is_file():
        raise EncoderContractError(f"{spec.repo_id}: no cached refs/main under {repo_dir}")
    main = ref.read_text().strip()
    if main != spec.revision:
        raise EncoderContractError(
            f"{spec.repo_id}: refs/main is {main} but the tokenizer is pinned to {spec.revision}"
        )
    return repo_dir / "snapshots" / spec.revision / "tokenizer.json"


def load_pinned(
    spec: EncoderSpec,
    tokenizer_file: str | Path | None = None,
    hub_cache: Path | None = None,
) -> tuple[PreTrainedTokenizerFast, dict]:
    """Load the pinned tokenizer and its fingerprint; raise on any mismatch.

    Without `tokenizer_file` the file comes from the HF cache (pinned_tokenizer_file).
    """
    if tokenizer_file is None:
        tokenizer_file = pinned_tokenizer_file(spec, hub_cache or hub_cache_dir())
    tokenizer = load_tokenizer(tokenizer_file, spec.tokenizer_sha256)
    fp = fingerprint(tokenizer, spec.tokenizer_sha256, spec.probes, spec.pair_probes)
    if fp["probe_ids_sha"] != spec.probe_ids_sha:
        raise EncoderContractError(
            f"{spec.name}: probe_ids_sha {fp['probe_ids_sha']} != pinned {spec.probe_ids_sha}"
        )
    return tokenizer, fp


def check_model_name(spec: EncoderSpec, model_name: str) -> None:
    """The configured model must be the one whose tokenizer is pinned."""
    if model_name != spec.repo_id:
        raise EncoderContractError(f"model {model_name!r} is not the pinned {spec.repo_id!r}")
