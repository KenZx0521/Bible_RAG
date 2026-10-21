"""The Genesis age card read from the new release's contracts (plan 2026-10-21 §3.1 A1 (c), A6).

test_gen_card_store reads the two GEN files from the confirmation records and serves them with build
b20261019_a86f2b06's contracts. Here the backend reads build b20261021_dfa1e3e3's contract directory the
way startup does (``contracts.verify``, then ``startup._parsed_contracts``), and the cards it serves are
checked again: 48 run/cards.json ``g`` cards and 10 none on the confirmation set, and stage-0's F1/F5 14
equal plus F3 4 none. The regnal layer and lexicon are the ones b20261019_a86f2b06 serves, byte for byte.

Skipped where the store or that build's contract directory is absent; assertions compare counts and
sha256 only.
"""

from __future__ import annotations

import hashlib

import pytest

import test_gen_card_store as S
import test_regnal_r4_cards as R4
from serving import contracts as contracts_mod
from serving import handshake as hs
from serving import startup
from serving.build import Build
from utils import gen_card
from utils.regnal.layer import LAYER_FILE as REGNAL_FILE

BUILD_ID = "b20261021_dfa1e3e3"
CONTRACTS = S.STORE / "contracts" / BUILD_ID
BUILD = Build(BUILD_ID, "b" + BUILD_ID, "passages__" + BUILD_ID, CONTRACTS, False, 34058)
REGNAL_SHA = "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"
pytestmark = pytest.mark.skipif(not ((CONTRACTS / contracts_mod.MANIFEST).is_file()
                                     and all(p.is_file() for p in S.NEEDED)),
                                reason=f"build {BUILD_ID}'s contracts or the GEN confirmation records not in the store")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def found():
    return contracts_mod.verify(CONTRACTS, BUILD_ID)


@pytest.fixture(scope="module")
def parsed(found):
    parsed, problems = startup._parsed_contracts(found)
    n_problems = len(problems)
    assert n_problems == 0
    return parsed


def test_the_contracts_verify_and_carry_both_gen_files_and_the_regnal_layer(found, parsed):
    mismatches = len(found.mismatches) + len(hs.check_manifest(BUILD, found.manifest))
    assert mismatches == 0
    shas = {name: _sha(found.files[name]) for name in (*gen_card.FILES, REGNAL_FILE)}
    assert shas == {gen_card.LAYER_FILE: S.GEN_LAYER_SHA, gen_card.NAMES_FILE: S.GEN_NAMES_SHA,
                    REGNAL_FILE: REGNAL_SHA}
    lexicons = (_sha(found.files["routing_lexicon.json"]), _sha(R4.LEXICON.read_bytes()))
    assert lexicons[0] == lexicons[1]
    gen = parsed[gen_card.LAYER_FILE]
    assert (gen.gen_layer_sha256, gen_card.chain_size(gen)) == (S.GEN_LAYER_SHA, {5: 10, 11: 9})


def test_the_confirmation_cards_from_the_new_release(found, parsed):
    served = S.through_query(BUILD, found.files[REGNAL_FILE], CONTRACTS / "routing_lexicon.json",
                             parsed[gen_card.LAYER_FILE])
    assert S.g_outcome(served) == {"card": 48, "none": 10}


def test_the_stage0_cards_from_the_new_release(parsed):
    S.test_the_stage0_gen_items_f1_f5_cards_and_f3_none(parsed[gen_card.LAYER_FILE])
