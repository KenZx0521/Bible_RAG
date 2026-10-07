"""G-DIFF: every difference to bible_md and canonical_full is classified and reconciles."""

from __future__ import annotations

import pytest
import yaml

from ragdata.gates import diff as gd
from ragdata.stages.diffs.md import DiffError


def _summaries(md_other=0, canonical_other=0, compared=3):
    md = {"units_compared": 5, "loss": {"units": 2, "chars": 9},
          "by_class": {"other": {"rows": md_other, "containers": md_other, "chars": 0},
                       "converter_offpage_clip": {"rows": 1, "containers": 1, "chars": 4}}}
    canonical = {"records_compared": compared, "layer_records": 3,
                 "by_class": {"errata": 1, "other": canonical_other}}
    return {"bible_md": md, "canonical_full": canonical}


EXPECT = {"bible_md": {"loss.units": 2, "by_class.converter_offpage_clip.chars": 4},
          "canonical_full": {"records_compared": 3}}


def test_a_fully_classified_reconciled_diff_passes():
    result = gd.check_diff(_summaries(), EXPECT)
    assert result.passed and (result.name, result.hard) == ("G-DIFF", True)
    assert result.observed["bible_md"]["loss.units"] == 2


@pytest.mark.parametrize("summaries, needle", [
    (_summaries(md_other=2), "bible_md: 2 differences"),
    (_summaries(canonical_other=1), "canonical_full: 1 differences"),
    (_summaries(compared=2), "records_compared"),
], ids=["md other", "canonical other", "coverage"])
def test_unclassified_or_uncovered_differences_are_red(summaries, needle):
    result = gd.check_diff(summaries, EXPECT)
    assert not result.passed and any(needle in d for d in result.details), result.details


def test_a_number_that_does_not_reconcile_with_the_audit_is_red():
    expect = {**EXPECT, "bible_md": {"loss.units": 268}}
    result = gd.check_diff(_summaries(), expect)
    assert any("loss.units: observed 2, expected 268" in d for d in result.details)


def test_an_expectation_naming_no_metric_is_red():
    expect = {**EXPECT, "bible_md": {"by_class.converter_selah.containers": 67}}
    result = gd.check_diff(_summaries(), expect)
    assert not result.passed and "no such metric" in " ".join(result.details)


def _write(tmp_path, doc):
    path = tmp_path / "diff_expect.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


def test_expectations_load_per_reference(tmp_path):
    loaded = gd.load_expect(_write(tmp_path, {"schema": gd.SCHEMA, **EXPECT}))
    assert loaded == EXPECT


@pytest.mark.parametrize("doc", [
    {"schema": "other"}, {"schema": gd.SCHEMA, "bible_md": {"loss.units": "268"}},
    {"schema": gd.SCHEMA, "elsewhere": {}},
], ids=["schema", "value", "reference"])
def test_malformed_expectations_are_refused(tmp_path, doc):
    with pytest.raises(DiffError):
        gd.load_expect(_write(tmp_path, doc))


def test_the_expectations_in_the_package_load():
    assert gd.load_expect()["bible_md"]
