"""The Genesis age card (年歲推導卡) on the build's contract files (plan 2026-10-21 §2.2).

``utils.gencard`` is the GEN confirmation set's package (evaluation/experiments/2026-10-20_gen_confirm/
gencard), copied byte for byte (the sha256 its F1 manifest pins): the rule of prereg §5.2 (question text
only, no LLM, no fallback: the trigger fires exactly when the rule finds the seeds) and the card it
builds. Confirmed on the 58 frozen questions (H1 +0.546, H2 +0.420; results 2026-10-21) for the F1 and F5
shapes on Genesis 5 and 11; the rule abstains on everything else.

A build of contract 1.3.0 carries the card's two data files in its relations layer: ``gen_layer.json``
(stage-0's Genesis layer) and ``gen_names.json`` (the names and blockers the rule reads, built from the
text layer's name spans and the routing lexicon). ``load`` reads them from a verified contract directory:
a manifest listing neither is a build without the card; anything else that is not this build's Genesis
layer is a ValueError, which startup reports as one handshake mismatch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Iterable, Mapping

from utils.gencard import Card, Layer, card, parse, trigger

logger = logging.getLogger(__name__)

LAYER_FILE = "gen_layer.json"
NAMES_FILE = "gen_names.json"
FILES = (LAYER_FILE, NAMES_FILE)
LEXICON_FILE = "routing_lexicon.json"
# gencard.parse's errors on a malformed document (it raises ValueError on a well-formed one that is no layer)
MALFORMED = (KeyError, TypeError, IndexError, AttributeError)


def evidence(layer: Layer, rows: Iterable[str]) -> tuple[str, ...]:
    """The verse keys the rows' layer nodes rest on, first seen first."""
    nodes = {n["id"]: n for n in layer.gen["nodes"]}
    return tuple(dict.fromkeys(v for y in rows for v in nodes[y]["evidence"]))


def chain_size(layer: Layer) -> dict[int, int]:
    return {ch: len(ids) for ch, ids in layer.chains.items()}


def _read(layer_data: bytes, names_data: bytes) -> tuple[Layer, dict]:
    names = json.loads(names_data.decode("utf-8"))
    layer = parse(json.loads(layer_data.decode("utf-8")), names)
    evidence(layer, layer.order)                 # every row a card can hold has its verse keys
    sha = hashlib.sha256(layer_data).hexdigest()
    if layer.gen_layer_sha256 != sha:            # parse copies it from the names file unchecked
        raise ValueError(f"{LAYER_FILE} sha256 {sha[:12]} is not {NAMES_FILE}'s gen_layer_sha256 "
                         f"{str(layer.gen_layer_sha256)[:12]}")
    return layer, names


def parse_files(layer_data: bytes, names_data: bytes) -> Layer:
    """The Genesis layer of the two files' bytes (its ``gen_layer_sha256`` is then the layer file's);
    ValueError when they are not one."""
    try:
        return _read(layer_data, names_data)[0]
    except MALFORMED as exc:
        raise ValueError(f"not a Genesis layer: {exc!r}") from None


def _check_build(layer: Layer, names: dict, manifest: Mapping) -> None:
    """The names file was built from this build's text layer and with its routing lexicon (the source
    whose path ends in it: the path names the build the confirmation set read, not this one)."""
    text = manifest["layers"]["text"]
    read_from = layer.gen["text_digest"][:12]
    if read_from != text.partition("@")[2]:
        raise ValueError(f"{LAYER_FILE} was read from text@{read_from}, the build's text layer is {text}")
    lexicons = [sha for path, sha in names["sources"].items() if path.endswith("/" + LEXICON_FILE)]
    if lexicons != [manifest["files"].get(LEXICON_FILE)]:
        raise ValueError(f"{NAMES_FILE} names routing lexicon {[str(s)[:12] for s in lexicons]}, the build's "
                         f"is {str(manifest['files'].get(LEXICON_FILE))[:12]}")


def load(manifest: Mapping, files: Mapping[str, bytes]) -> Layer | None:
    """The build's Genesis layer, from ``contracts.verify``'s manifest and verified files. None when the
    manifest lists neither file, or a listed one did not verify (verify reported it); ValueError when
    it lists one alone, or the two are not a Genesis layer of this build."""
    listed = [name for name in FILES if name in manifest.get("files", {})]
    if not listed:
        return None
    if len(listed) == 1:
        raise ValueError(f"the manifest lists {listed[0]} without {(set(FILES) - set(listed)).pop()}")
    if not all(name in files for name in FILES):
        return None
    try:
        layer, names = _read(files[LAYER_FILE], files[NAMES_FILE])
        _check_build(layer, names, manifest)
    except MALFORMED as exc:
        raise ValueError(f"not a Genesis layer of this build: {exc!r}") from None
    return layer


def _qhash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


def card_of(question: str, layer: Layer) -> Card | None:
    """``gencard.card`` where the rule takes the question, else None; then one INFO line (the question's
    hash, never its text)."""
    hit = trigger(question, layer)
    if not hit.fired:
        return None
    built = card(question, layer)
    logger.info("gen card q=%s seeds=%s shape=%s lines=%d", _qhash(question), list(built.seeds), hit.shape,
                len(built.lines))
    return built
