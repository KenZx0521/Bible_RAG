"""Picking the GT version: --gt v1|v2 or the EVAL_GT_VERSION setting; v2 only as frozen."""

import hashlib
import json
from pathlib import Path

import pytest

from src import data_loader, gt_v2
from src.gt_v2 import GroundTruthItemV2, GtV2Error

_REPO = Path(__file__).resolve().parents[2]


def test_v1_carries_its_version_and_the_sha_of_its_bytes():
    gt = data_loader.load_gt("v1")

    assert gt.meta() == {"gt_version": "v1",
                         "gt_sha": hashlib.sha256((_REPO / "ground_truth.json").read_bytes()).hexdigest()}
    assert len(gt.items) == 500 and gt.slot_universe is None
    assert gt.by_id()["VERSE_LOOKUP_001"].reference == "約翰福音 3:16"


def test_v2_is_the_frozen_file_with_slots():
    gt = data_loader.load_gt("v2")
    freeze = json.loads((_REPO / "config" / "gold" / "gt_v2_freeze.json").read_text())

    assert gt.meta() == {"gt_version": "v2", "gt_sha": freeze["sha256"]}
    assert gt.slot_universe == freeze["slot_universe"]
    assert all(isinstance(item, GroundTruthItemV2) for item in gt.items)


def test_the_setting_picks_the_version_when_none_is_given(monkeypatch):
    monkeypatch.setattr(data_loader.settings, "eval_gt_version", "v2")

    assert data_loader.load_gt().version == "v2"


def test_v2_that_fails_the_freeze_check_does_not_load(tmp_path, monkeypatch):
    freeze = tmp_path / "gt_v2_freeze.json"
    freeze.write_text(json.dumps({"sha256": "0" * 64, "slot_universe": "text@ddb48c599861"}))
    monkeypatch.setattr(gt_v2, "FREEZE_PATH", freeze)

    with pytest.raises(GtV2Error, match="sha256"):
        data_loader.load_gt("v2")


def test_an_unknown_version_is_refused():
    with pytest.raises(ValueError, match="v3"):
        data_loader.load_gt("v3")
