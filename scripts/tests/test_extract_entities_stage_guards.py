"""Step 1 stage guards: what freeze-grounded and merge refuse (plan M6, batch 0).

Split from test_extract_entities_stages.py, which holds the split/merge
round-trip tests, to keep both files under 800 lines; the fixture, helpers
and pytest fixtures below come from there.

The frozen grounded half is the only LLM-free copy of Phase 4 and ner_*.jsonl
become the Person/Place/Group half of every later rebuild, so a partial,
sampled, wiped, stale or edited half must be refused (or overridden with
--force / --accept-grounded-drift) instead of passing silently.
"""

import json
import logging
import shutil
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

import extract_entities as ee
from entity_extraction import stages
# fake_ner, queue and the autouse scratch_cwd are pytest fixtures: importing
# them is what makes them available (and scratch_cwd active) here.
from test_extract_entities_stages import (  # noqa: F401
    FIXTURE_DIR, GROUNDED, _frozen_with_ner_half, _seed_output, _sha, _split, _types,
    _write_ner_files, fake_ner, queue, scratch_cwd,
)

# ------------------------------------------- NER provenance (ner_manifest) ---
# A sampled or hand-made ner_*.jsonl lands in the same canonical files as a
# full --stage ner, and merge would silently make it the P/P/G half of every
# later rebuild (review B, medium). The manifest records where it came from.

def _without(halves: "stages.Halves", *entity_ids: str) -> "stages.Halves":
    """Drop entities, and the mentions that point at them, from both halves."""
    def keep(line: bytes) -> bool:
        return json.loads(line)["entity_id"] not in entity_ids
    return stages.Halves(*(tuple(filter(keep, getattr(halves, f.name)))
                           for f in fields(halves)))


def _write_build(out: Path, halves: "stages.Halves") -> None:
    """Write entities.jsonl / entity_mentions.jsonl as the pipeline would."""
    entity_lines, mention_lines = stages.merge_halves(halves)
    (out / "entities.jsonl").write_bytes(b"".join(entity_lines))
    (out / "entity_mentions.jsonl").write_bytes(b"".join(mention_lines))


def _ner_only(halves: "stages.Halves") -> "stages.Halves":
    return stages.Halves(halves.ner_entities, halves.ner_mentions, (), ())


def _warnings(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def _edit_json(path: Path, change) -> None:
    """Rewrite a manifest after change(manifest) has edited it in place."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_ner_stage_writes_manifest(tmp_path, queue, fake_ner):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "ner", "-i", str(queue), "-o", str(out)])

    manifest = json.loads((out / "ner_manifest.json").read_text(encoding="utf-8"))
    for name, lines in (("ner_entities.jsonl", 9), ("ner_mentions.jsonl", 10)):
        assert manifest["files"][name] == {"sha256": _sha(out / name), "lines": lines}
    assert manifest["sampled"] is False and manifest["sample"] is None
    assert manifest["input"] == {"path": str(queue), "sha256": _sha(queue)}
    assert "git_commit" in manifest and "git_dirty" in manifest
    datetime.fromisoformat(manifest["created_at"])


def test_ner_manifest_records_the_queue_ner_read(tmp_path, queue, monkeypatch):
    """The queue sha is taken before NER (~30 min), so a queue rewritten during
    the run cannot get the manifest's endorsement for output NER never read."""
    out = _seed_output(tmp_path, FIXTURE_DIR)
    read_sha = _sha(queue)

    def ner_then_queue_changes(items, ckip_config):
        queue.write_text(queue.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        from test_extract_entities_stages import _ner_raw
        return _ner_raw()
    monkeypatch.setattr(ee, "run_ner_extraction", ner_then_queue_changes)
    ee.main(["--stage", "ner", "-i", str(queue), "-o", str(out)])

    manifest = json.loads((out / "ner_manifest.json").read_text(encoding="utf-8"))
    assert manifest["input"]["sha256"] == read_sha != _sha(queue)


def test_ner_stage_with_sample_marks_manifest_sampled(tmp_path, queue, fake_ner, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "ner", "--sample", "1", "-i", str(queue), "-o", str(out)])

    manifest = json.loads((out / "ner_manifest.json").read_text(encoding="utf-8"))
    assert manifest["sampled"] is True and manifest["sample"] == 1
    assert "--sample" in _warnings(caplog)


def test_ner_stage_crash_leaves_no_stale_manifest(tmp_path, queue, fake_ner, monkeypatch):
    # The previous run's manifest must not vouch for half-rewritten files.
    out = _frozen_with_ner_half(tmp_path)

    def crash(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(ee, "save_mentions", crash)
    with pytest.raises(OSError):
        ee.main(["--stage", "ner", "-i", str(queue), "-o", str(out)])
    assert not (out / "ner_manifest.json").exists()


def test_merge_refuses_sampled_ner_half_without_force(tmp_path, queue, fake_ner, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    ee.main(["--stage", "ner", "--sample", "1", "-i", str(queue), "-o", str(out)])
    (out / "entities.jsonl").unlink()   # nothing else may stand in the way

    for argv in (["--stage", "merge"], ["--stage", "merge", "--dry-run"]):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            ee.main(argv + ["-i", str(queue), "-o", str(out)])
        assert exc.value.code == 1
        assert "sample" in caplog.text and "--force" in caplog.text
        assert not (out / "entities.jsonl").exists()

    caplog.clear()
    ee.main(["--stage", "merge", "-i", str(queue), "-o", str(out), "--force"])
    assert "sample" in _warnings(caplog)
    assert (out / "entities.jsonl").exists()


def test_merge_refuses_ner_half_without_manifest(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _write_ner_files(out, _split(FIXTURE_DIR), manifest=False)
    before = (out / "entities.jsonl").read_bytes()

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "merge", "-o", str(out)])
    assert exc.value.code == 1
    assert "ner_manifest.json" in caplog.text and "--force" in caplog.text
    assert (out / "entities.jsonl").read_bytes() == before

    caplog.clear()
    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert "ner_manifest.json" in _warnings(caplog)
    assert (out / "entities.jsonl").read_bytes() == (FIXTURE_DIR / "entities.jsonl").read_bytes()


def test_merge_refuses_ner_half_edited_after_its_manifest(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    mentions = out / "ner_mentions.jsonl"
    mentions.write_bytes(b"".join(stages.read_jsonl_lines(mentions)[:-1]))

    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "ner_mentions.jsonl does not match" in caplog.text
    ee.main(["--stage", "merge", "-o", str(out), "--force"])


@pytest.mark.parametrize("name, forced_ok", [
    ("ner_manifest.json", True),                 # provenance only: --force may override
    ("frozen/grounded_manifest.json", False),    # frozen files cannot be verified at all
])
def test_merge_reports_unreadable_manifest_cleanly(tmp_path, caplog, name, forced_ok):
    out = _frozen_with_ner_half(tmp_path)
    (out / name).write_text('{"files": ', encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "merge", "-o", str(out)])
    assert exc.value.code == 1
    assert Path(name).name in caplog.text and "unreadable" in caplog.text

    if forced_ok:
        ee.main(["--stage", "merge", "-o", str(out), "--force"])
    else:
        with pytest.raises(SystemExit):
            ee.main(["--stage", "merge", "-o", str(out), "--force"])


@pytest.mark.parametrize("change", [
    lambda m: m.pop("sampled"),
    lambda m: m.update(sampled=None),
], ids=["sampled-missing", "sampled-null"])
def test_merge_counts_an_unknown_sampled_flag_as_sampled(tmp_path, caplog, change):
    # Only an explicit "sampled": false vouches for the whole queue.
    out = _frozen_with_ner_half(tmp_path)
    _edit_json(out / "ner_manifest.json", change)

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "merge", "-o", str(out)])
    assert exc.value.code == 1
    assert "sampled" in caplog.text and "--force" in caplog.text


@pytest.mark.parametrize("change", [
    lambda m: m.update(files=None),
    lambda m: m.update(files=[]),
    lambda m: m["files"].update({"ner_entities.jsonl": "0" * 64}),
    lambda m: m["files"]["ner_mentions.jsonl"].update(lines="10"),
    lambda m: m.update(input=None),
], ids=["files-null", "files-list", "digest-str", "lines-str", "input-null"])
def test_merge_refuses_a_malformed_ner_manifest_cleanly(tmp_path, caplog, change):
    # Valid JSON of the wrong shape is a provenance problem like any other: a
    # clean refusal that --force may override, never a traceback.
    out = _frozen_with_ner_half(tmp_path)
    _edit_json(out / "ner_manifest.json", change)

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "merge", "-o", str(out)])
    assert exc.value.code == 1 and "ner_manifest.json" in caplog.text
    caplog.clear()
    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert "ner_manifest.json" in _warnings(caplog)


def test_merge_refuses_ner_half_extracted_from_another_queue(tmp_path, caplog):
    # Step 0 re-ran after --stage ner: the old NER half still equals the frozen
    # build's, so the NER-drift report cannot see that it is stale.
    out = _frozen_with_ner_half(tmp_path)
    (out / "embedding_queue.jsonl").write_text('{"id": "gen:1:0"}\n', encoding="utf-8")
    before = (out / "entities.jsonl").read_bytes()

    for extra in ([], ["--dry-run"]):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            ee.main(["--stage", "merge", "-o", str(out)] + extra)
        assert exc.value.code == 1
        assert "different embedding queue" in caplog.text and "--force" in caplog.text
        assert (out / "entities.jsonl").read_bytes() == before

    caplog.clear()
    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert "different embedding queue" in _warnings(caplog)


def test_merge_checks_queue_content_not_its_path(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    elsewhere = tmp_path / "queue_copy.jsonl"
    shutil.copyfile(out / "embedding_queue.jsonl", elsewhere)
    (out / "embedding_queue.jsonl").unlink()

    with pytest.raises(SystemExit):        # nothing to check the NER half against
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "output/embedding_queue.jsonl not found" in caplog.text

    caplog.clear()
    ee.main(["--stage", "merge", "-i", str(elsewhere), "-o", str(out)])
    assert _warnings(caplog) == ""


# ------------------------------------ freeze: empty / partial grounded half ---
# The snapshot is the only LLM-free copy of Phase 4; freezing a wiped or
# partial build must not pass silently (review B, low).

def test_freeze_refuses_empty_grounded_half_without_force(tmp_path, caplog):
    out = tmp_path / "output"
    out.mkdir()
    _write_build(out, _ner_only(_split(FIXTURE_DIR)))

    for extra in ([], ["--dry-run"]):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            ee.main(["--stage", "freeze-grounded", "-o", str(out)] + extra)
        assert exc.value.code == 1
        assert "empty" in caplog.text and "--force" in caplog.text
        assert not (out / "frozen").exists()

    caplog.clear()
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert (out / "frozen" / "grounded_entities.jsonl").read_bytes() == b""
    assert "empty" in _warnings(caplog)


def test_freeze_refuses_grounded_half_missing_a_type(tmp_path, caplog):
    out = tmp_path / "output"
    out.mkdir()
    _write_build(out, _without(_split(FIXTURE_DIR), "theme:jiushu"))

    with pytest.raises(SystemExit):
        ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    assert "Theme" in caplog.text
    assert not (out / "frozen").exists()
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])


def test_refreeze_refuses_large_grounded_drift(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    manifest_path = out / "frozen" / "grounded_manifest.json"
    first = manifest_path.read_bytes()
    # 6 -> 4 grounded entities, 7 -> 5 mentions; every grounded type survives.
    _write_build(out, _without(_split(FIXTURE_DIR), "event:guohonghai", "object:huimu"))

    for extra in (["--force"], ["--force", "--dry-run"]):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            ee.main(["--stage", "freeze-grounded", "-o", str(out)] + extra)
        assert exc.value.code == 1
        assert "entities 6 -> 4" in caplog.text and "mentions 7 -> 5" in caplog.text
        assert "--accept-grounded-drift" in caplog.text
        assert manifest_path.read_bytes() == first

    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force",
             "--accept-grounded-drift"])
    assert json.loads(manifest_path.read_bytes())["files"]["grounded_entities.jsonl"][
        "lines"] == 4


def test_refreeze_from_wiped_build_is_refused_even_with_force(tmp_path, caplog, queue,
                                                              fake_ner):
    # Review B's reproduction: --ner-only --force wipes E/O/T, then a forced
    # re-freeze would replace the snapshot with an empty one.
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    snapshot = (out / "frozen" / "grounded_entities.jsonl").read_bytes()
    ee.main(["--ner-only", "--force", "-i", str(queue), "-o", str(out)])

    with pytest.raises(SystemExit):
        ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert "entities 6 -> 0" in caplog.text
    assert (out / "frozen" / "grounded_entities.jsonl").read_bytes() == snapshot


def test_refreeze_over_unreadable_manifest_needs_accept_drift(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    (out / "frozen" / "grounded_manifest.json").write_text("garbage", encoding="utf-8")

    with pytest.raises(SystemExit):
        ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert "--accept-grounded-drift" in caplog.text
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force",
             "--accept-grounded-drift"])


@pytest.mark.parametrize("change", [
    lambda m: m["files"]["grounded_entities.jsonl"].update(lines="6"),
    lambda m: m.update(files=None),
    lambda m: m["files"].pop("grounded_mentions.jsonl"),
], ids=["lines-str", "files-null", "file-missing"])
def test_refreeze_over_malformed_manifest_needs_accept_drift(tmp_path, caplog, change):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _edit_json(out / "frozen" / "grounded_manifest.json", change)

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert exc.value.code == 1 and "--accept-grounded-drift" in caplog.text
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force",
             "--accept-grounded-drift"])


def test_refreeze_without_its_manifest_compares_the_frozen_files(tmp_path, caplog):
    # The manifest is written last: a first freeze that crashed, or a restore
    # that left it out, must not let a plain --force replace the snapshot unchecked.
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    frozen = out / "frozen"
    (frozen / "grounded_manifest.json").unlink()
    snapshot = (frozen / "grounded_entities.jsonl").read_bytes()
    _write_build(out, _ner_only(_split(FIXTURE_DIR)))   # wiped, as after --ner-only --force

    with pytest.raises(SystemExit):
        ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert "entities 6 -> 0" in caplog.text and "mentions 7 -> 0" in caplog.text
    assert (frozen / "grounded_entities.jsonl").read_bytes() == snapshot

    _write_build(out, _split(FIXTURE_DIR))              # the full build again: no drift
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert (frozen / "grounded_manifest.json").exists()


def test_refreeze_over_half_a_snapshot_without_manifest_needs_accept_drift(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    for name in ("grounded_manifest.json", "grounded_mentions.jsonl"):
        (out / "frozen" / name).unlink()

    with pytest.raises(SystemExit):
        ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert "grounded_mentions.jsonl" in caplog.text and "--accept-grounded-drift" in caplog.text
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force",
             "--accept-grounded-drift"])


def _grounded_build(n: int) -> "stages.Halves":
    """The fixture's NER half plus n grounded entities with one mention each,
    cycling through Event/Object/Theme so every grounded type is present."""
    types = sorted(GROUNDED)
    entities, mentions = [], []
    for i in range(n):
        etype = types[i % len(types)]
        eid = f"{etype.lower()}:g{i:02d}"
        entities.append(json.dumps({"entity_id": eid, "type": etype,
                                    "mention_count": 1}).encode() + b"\n")
        mentions.append(json.dumps({"mention_id": f"m:g:{i:04d}",
                                    "entity_id": eid}).encode() + b"\n")
    ner = _split(FIXTURE_DIR)
    return stages.Halves(ner.ner_entities, ner.ner_mentions, tuple(entities), tuple(mentions))


@pytest.mark.parametrize("change, refused", [(-2, False), (2, False), (-3, True), (3, True)])
def test_refreeze_drift_tolerance_is_five_percent(tmp_path, caplog, change, refused):
    # 40 grounded entities and mentions: 2 lines either way is exactly 5% and
    # passes a plain --force; 3 (7.5%) needs --accept-grounded-drift.
    out = tmp_path / "output"
    out.mkdir()
    _write_build(out, _grounded_build(40))
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _write_build(out, _grounded_build(40 + change))
    argv = ["--stage", "freeze-grounded", "-o", str(out), "--force"]

    if refused:
        with pytest.raises(SystemExit):
            ee.main(argv)
        assert f"entities 40 -> {40 + change}" in caplog.text
    else:
        ee.main(argv)
    manifest = json.loads((out / "frozen" / "grounded_manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["grounded_entities.jsonl"]["lines"] == (
        40 if refused else 40 + change)


# ----------------------------------- merge: grounded guards never skip empty ---

def test_merge_refuses_when_current_build_lost_its_grounded_half(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    _write_build(out, _ner_only(_split(FIXTURE_DIR)))   # as after --ner-only --force
    wiped = (out / "entities.jsonl").read_bytes()

    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "no Event/Object/Theme" in caplog.text and "--force" in caplog.text
    assert (out / "entities.jsonl").read_bytes() == wiped

    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert (out / "entities.jsonl").read_bytes() == (FIXTURE_DIR / "entities.jsonl").read_bytes()


def test_merge_refuses_empty_frozen_snapshot_without_force(tmp_path, caplog):
    out = tmp_path / "output"
    out.mkdir()
    ner_only = _ner_only(_split(FIXTURE_DIR))
    _write_build(out, ner_only)
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])  # empty, forced
    _write_ner_files(out, ner_only)
    (out / "entities.jsonl").unlink()

    caplog.clear()
    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "snapshot is empty" in caplog.text
    assert not (out / "entities.jsonl").exists()
    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert _types(out / "entities.jsonl") == {"Person", "Place", "Group"}


@pytest.mark.parametrize("change", [
    lambda m: m.update(files=None),
    lambda m: m["files"].update({"grounded_entities.jsonl": None}),
    lambda m: m.update(ner_half=[]),
    lambda m: m["ner_half"].update(mentions="10"),
    lambda m: m["ner_half"].update(type_counts={"Group": "2"}),
], ids=["files-null", "digest-null", "ner_half-list", "ner_half-digest-str",
        "type_counts-str"])
def test_merge_refuses_a_malformed_grounded_manifest_even_with_force(tmp_path, caplog,
                                                                     change):
    # It vouches for the frozen files: if its shape is wrong none of it can be
    # trusted, so not even --force proceeds, and the refusal is never a traceback.
    out = _frozen_with_ner_half(tmp_path)
    _edit_json(out / "frozen" / "grounded_manifest.json", change)

    for extra in ([], ["--force"]):
        caplog.clear()
        with pytest.raises(SystemExit) as exc:
            ee.main(["--stage", "merge", "-o", str(out)] + extra)
        assert exc.value.code == 1
        assert "grounded_manifest.json is unreadable" in caplog.text


# ------------------------------------------- merge: NER half drift is logged ---
# 1C changes NER on purpose, so a different NER half must not block; it must
# be loud, with counts, instead of one INFO line.

def test_merge_warns_with_counts_when_ner_half_differs(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _write_ner_files(out, _without(_split(FIXTURE_DIR), "group:liweiren"))

    caplog.clear()
    result = stages.merge_stage(out, out / "frozen", out / "embedding_queue.jsonl")
    warning = _warnings(caplog)
    assert "NER half differs from the frozen build's" in warning
    assert "entities 9 -> 8 (-1)" in warning and "mentions 10 -> 9 (-1)" in warning
    assert "Group 2 -> 1 (-1)" in warning and "Person" not in warning
    assert result["ner_reproduced"] is False
    assert _types(out / "entities.jsonl") >= GROUNDED   # written, not blocked


def test_merge_does_not_warn_when_ner_half_is_reproduced(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    caplog.clear()
    caplog.set_level(logging.INFO)
    result = stages.merge_stage(out, out / "frozen", out / "embedding_queue.jsonl")
    assert result["ner_reproduced"] is True
    assert _warnings(caplog) == ""
    assert "NER half identical to the frozen build's" in caplog.text
