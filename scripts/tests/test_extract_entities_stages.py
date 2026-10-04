"""Step 1 split into NER / frozen-grounded halves (plan M6, batch 0).

The guarantee under test is merge(split(x)) == x byte-for-byte for any
entities.jsonl / entity_mentions.jsonl pair the pipeline writes, and that the
staged path (--stage ner + frozen grounded + --stage merge) reproduces the
monolithic default pipeline exactly.  NER itself (CKIP, ~30 min) is never run:
run_ner_extraction / run_grounded_extraction are replaced by synthetic raw
outputs shaped like the real ones.

fixtures/stages/{entities,entity_mentions}.jsonl were written by the current
monolithic pipeline (normalize_and_merge + save_entities/save_mentions) from
_ner_raw()/_grounded_raw() below; test_fixture_matches_monolithic_writer keeps
them honest.
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

import extract_entities as ee
from entity_extraction import stages
from entity_extraction.entity_normalizer import normalize_and_merge
from entity_extraction.models import Entity, EntityMention, EntityType, ExtractionMethod

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "stages"
REAL_OUTPUT = Path(__file__).resolve().parents[2] / "output"
GROUNDED = {"Event", "Object", "Theme"}


# ---------------------------------------------------------------- synthetic ---

def _ner_raw() -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """Fresh pre-normalisation NER output, shaped like run_ner_extraction().

    Covers what decides output order: mention_count ties (亞倫/米利暗,
    西奈山/西奈), an alias-overlap merge (主耶穌 folds into 耶穌, remapping its
    mention) and all three NER source types.
    """
    def ent(eid, etype, name, count, aliases=()):
        return Entity(entity_id=eid, type=etype, canonical_name=name,
                      aliases=list(aliases), extraction_method=ExtractionMethod.NER,
                      mention_count=count)

    entities = [
        ent("person:moxi", EntityType.PERSON, "摩西", 5),
        ent("place:aiji", EntityType.PLACE, "埃及", 3),
        ent("person:yalun", EntityType.PERSON, "亞倫", 2),
        ent("person:miliyan", EntityType.PERSON, "米利暗", 2),
        ent("person:yesu", EntityType.PERSON, "耶穌", 4, ["主耶穌"]),
        ent("person:zhuyesu", EntityType.PERSON, "主耶穌", 1),
        ent("group:yiselieren", EntityType.GROUP, "以色列人", 4),
        ent("place:xinaishan", EntityType.PLACE, "西奈山", 1),
        ent("place:xinai", EntityType.PLACE, "西奈", 1),
        ent("group:liweiren", EntityType.GROUP, "利未人", 1),
    ]

    def men(src, n, stype, eid, span, ctx, start):
        return EntityMention(mention_id=f"m:{src}:{n:03d}", entity_id=eid,
                             source_id=src, source_type=stype, text_span=span,
                             context=ctx, start_pos=start, end_pos=start + len(span))

    mentions = [
        men("exo:3:0", 1, "pericope", "person:moxi", "摩西", "摩西牧養他岳父的羊群", 0),
        men("exo:3:0:v:1", 1, "verse", "place:xinaishan", "西奈山", "到了神的山，就是西奈山", 9),
        men("exo:15:0:v:20", 1, "verse", "person:miliyan", "米利暗", "亞倫的姐姐女先知米利暗", 8),
        men("exo:15:0:v:20", 2, "verse", "person:yalun", "亞倫", "亞倫的姐姐女先知米利暗", 0),
        men("mat:4:0", 1, "chunk", "person:zhuyesu", "主耶穌", "主耶穌被聖靈引到曠野", 0),
        men("mat:4:0", 2, "chunk", "person:yesu", "耶穌", "耶穌被聖靈引到曠野", 0),
        men("exo:12:0", 1, "pericope", "group:yiselieren", "以色列人", "以色列人從蘭塞起行", 0),
        men("exo:12:0", 2, "pericope", "place:aiji", "埃及", "出了埃及地", 2),
        men("lev:8:0", 1, "pericope", "group:liweiren", "利未人", "利未人的職分", 0),
        men("exo:19:0:v:1", 1, "verse", "place:xinai", "西奈", "來到西奈的曠野", 2),
    ]
    return {e.entity_id: e for e in entities}, mentions


def _grounded_raw() -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """Fresh grounded output, shaped like _candidates_to_entities().

    The 救贖 description carries a raw U+2028, quotes and a backslash: JSON
    emits U+2028 unescaped with ensure_ascii=False and str.splitlines() would
    split on it, so any re-split or re-serialisation shows up as a byte diff.
    """
    def ent(eid, etype, name, count, method, desc=""):
        return Entity(entity_id=eid, type=etype, canonical_name=name,
                      description=desc, extraction_method=method, mention_count=count)

    entities = [
        ent("event:chuaiji", EntityType.EVENT, "出埃及", 3,
            ExtractionMethod.PERICOPE_TITLE, "以色列人出埃及"),
        ent("object:yuegui", EntityType.OBJECT, "約櫃", 2, ExtractionMethod.RULE),
        ent("event:guohonghai", EntityType.EVENT, "過紅海", 1, ExtractionMethod.RULE),
        ent("theme:jiushu", EntityType.THEME, "救贖", 1, ExtractionMethod.GROUNDED_LLM,
            '他說"救贖"\\ 是 恩典'),
        ent("object:huimu", EntityType.OBJECT, "會幕", 2, ExtractionMethod.POS_TAG),
        ent("event:banbushijie", EntityType.EVENT, "頒布十誡", 1,
            ExtractionMethod.GROUNDED_LLM),
    ]

    def men(src, n, eid, span, ctx):
        return EntityMention(mention_id=f"m:{src}:{n:04d}", entity_id=eid,
                             source_id=src, source_type="pericope", text_span=span,
                             context=ctx)

    mentions = [
        men("exo:12:0", 1, "event:chuaiji", "出埃及", "以色列人出埃及"),
        men("exo:12:0", 2, "event:chuaiji", "出埃及", "以色列人出埃及"),
        men("exo:25:0", 3, "object:yuegui", "約櫃", "要用皂莢木作一櫃"),
        men("exo:14:0", 4, "event:guohonghai", "過紅海", "以色列人過紅海"),
        men("rom:3:0", 5, "theme:jiushu", "救贖", "因基督耶穌的救贖"),
        men("exo:26:0", 6, "object:huimu", "會幕", "你要用十幅幔子作帳幕"),
        men("exo:20:0", 7, "event:banbushijie", "頒布十誡", "神吩咐這一切的話"),
    ]
    return {e.entity_id: e for e in entities}, mentions


# ------------------------------------------------------------------ helpers ---

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_output(tmp_path: Path, source_dir: Path) -> Path:
    """Copy an entities/mentions pair into a scratch output dir (never in place)."""
    out = tmp_path / "output"
    out.mkdir()
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        shutil.copyfile(source_dir / name, out / name)
    return out


def _split(source_dir: Path) -> "stages.Halves":
    return stages.split_halves(
        stages.read_jsonl_lines(source_dir / "entities.jsonl"),
        stages.read_jsonl_lines(source_dir / "entity_mentions.jsonl"),
    )


def _write_ner_files(out: Path, halves: "stages.Halves", *, manifest: bool = True) -> None:
    """Stand in for --stage ner: the NER half of `halves` plus its manifest."""
    (out / "ner_entities.jsonl").write_bytes(b"".join(halves.ner_entities))
    (out / "ner_mentions.jsonl").write_bytes(b"".join(halves.ner_mentions))
    if manifest:
        stand_in_queue = out / "embedding_queue.jsonl"
        stand_in_queue.write_text("{}\n", encoding="utf-8")
        stages.write_ner_manifest(out, stand_in_queue, None)


def _write_ner_half(out: Path, source_dir: Path) -> None:
    """Stand in for --stage ner by writing the NER half of an existing build."""
    _write_ner_files(out, _split(source_dir))


def _assert_roundtrip_via_cli(tmp_path: Path, source_dir: Path) -> None:
    out = _seed_output(tmp_path, source_dir)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _write_ner_half(out, source_dir)
    # Merge must rebuild both files from the halves alone.
    (out / "entities.jsonl").unlink()
    (out / "entity_mentions.jsonl").unlink()
    ee.main(["--stage", "merge", "-o", str(out)])
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        assert (out / name).read_bytes() == (source_dir / name).read_bytes(), name


def _types(path: Path) -> set:
    # Not str.splitlines(): the fixture's U+2028 would split a record in two.
    return {json.loads(line)["type"] for line in stages.read_jsonl_lines(path)}


@pytest.fixture(autouse=True)
def scratch_cwd(tmp_path: Path, monkeypatch) -> None:
    """Run from tmp_path: CLI defaults (-i output/embedding_queue.jsonl,
    --bible-md-dir bible_md) then resolve inside the scratch dir, never to the
    repo's real data. Merge's default queue becomes tmp_path/output/
    embedding_queue.jsonl, where _write_ner_files puts its stand-in."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def queue(tmp_path: Path) -> Path:
    """A stand-in embedding_queue; the patched NER ignores its contents."""
    path = tmp_path / "embedding_queue.jsonl"
    path.write_text(json.dumps({"id": "exo:3:0", "type": "pericope", "text": "摩西"},
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fake_ner(monkeypatch):
    monkeypatch.setattr(ee, "run_ner_extraction", lambda items, ckip_config: _ner_raw())


def _forbid_extraction(monkeypatch) -> None:
    """Fail at once if any extractor (CKIP NER, grounded Phase 1-4, LLM) starts."""
    def boom(*_args, **_kwargs):
        raise AssertionError("no extractor may run")
    for name in ("run_ner_extraction", "run_grounded_extraction", "run_llm_extraction"):
        monkeypatch.setattr(ee, name, boom)


# ------------------------------------------------------------- split / merge ---

def test_fixture_matches_monolithic_writer(tmp_path):
    ner_e, ner_m = _ner_raw()
    grd_e, grd_m = _grounded_raw()
    entities, mentions = normalize_and_merge(ner_e, grd_e, ner_m, grd_m)
    ee.save_entities(entities, tmp_path / "entities.jsonl")
    ee.save_mentions(mentions, tmp_path / "entity_mentions.jsonl")
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        assert (tmp_path / name).read_bytes() == (FIXTURE_DIR / name).read_bytes(), name


def test_split_then_merge_is_byte_identical_on_fixture():
    entity_lines = stages.read_jsonl_lines(FIXTURE_DIR / "entities.jsonl")
    mention_lines = stages.read_jsonl_lines(FIXTURE_DIR / "entity_mentions.jsonl")

    halves = stages.split_halves(entity_lines, mention_lines)
    merged_entities, merged_mentions = stages.merge_halves(halves)

    assert b"".join(merged_entities) == (FIXTURE_DIR / "entities.jsonl").read_bytes()
    assert b"".join(merged_mentions) == (FIXTURE_DIR / "entity_mentions.jsonl").read_bytes()
    assert {json.loads(l)["type"] for l in halves.grounded_entities} == GROUNDED
    assert {json.loads(l)["type"] for l in halves.ner_entities} == {"Person", "Place", "Group"}
    assert len(halves.grounded_entities) == 6 and len(halves.grounded_mentions) == 7
    # The U+2028 line must survive as one record, not be split in two.
    assert len(entity_lines) == len(halves.ner_entities) + len(halves.grounded_entities)


def test_freeze_and_merge_cli_roundtrip_on_fixture(tmp_path):
    _assert_roundtrip_via_cli(tmp_path, FIXTURE_DIR)


@pytest.mark.skipif(
    not ((REAL_OUTPUT / "entities.jsonl").exists()
         and (REAL_OUTPUT / "entity_mentions.jsonl").exists()),
    reason="output/entities.jsonl or entity_mentions.jsonl not present",
)
def test_freeze_and_merge_cli_roundtrip_on_real_output(tmp_path):
    before = {n: _sha(REAL_OUTPUT / n) for n in ("entities.jsonl", "entity_mentions.jsonl")}
    _assert_roundtrip_via_cli(tmp_path, REAL_OUTPUT)
    after = {n: _sha(REAL_OUTPUT / n) for n in before}
    assert after == before


def test_staged_pipeline_equals_monolithic_pipeline(tmp_path, monkeypatch, queue, fake_ner):
    monkeypatch.setattr(ee, "run_grounded_extraction", lambda **_kwargs: _grounded_raw())
    bible_md = tmp_path / "bible_md"
    bible_md.mkdir()
    mono = tmp_path / "mono"
    ee.main(["-i", str(queue), "-o", str(mono), "--bible-md-dir", str(bible_md)])

    staged = _seed_output(tmp_path, mono)
    ee.main(["--stage", "freeze-grounded", "-o", str(staged)])
    entities_before_ner = (staged / "entities.jsonl").read_bytes()
    ee.main(["--stage", "ner", "-i", str(queue), "-o", str(staged)])
    assert (staged / "entities.jsonl").read_bytes() == entities_before_ner

    halves = stages.split_halves(stages.read_jsonl_lines(mono / "entities.jsonl"),
                                 stages.read_jsonl_lines(mono / "entity_mentions.jsonl"))
    assert (staged / "ner_entities.jsonl").read_bytes() == b"".join(halves.ner_entities)
    assert (staged / "ner_mentions.jsonl").read_bytes() == b"".join(halves.ner_mentions)

    ee.main(["--stage", "merge", "-i", str(queue), "-o", str(staged)])
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        assert (staged / name).read_bytes() == (mono / name).read_bytes(), name


# -------------------------------------------------------- malformed sources ---

_E_PERSON = b'{"entity_id": "person:a", "type": "Person", "mention_count": 1}\n'
_E_EVENT = b'{"entity_id": "event:b", "type": "Event", "mention_count": 1}\n'
_M_PERSON = b'{"mention_id": "m:x:001", "entity_id": "person:a"}\n'
_M_EVENT = b'{"mention_id": "m:x:0001", "entity_id": "event:b"}\n'


@pytest.mark.parametrize("entities, mentions, message", [
    ([_E_PERSON, _E_EVENT], [_M_PERSON, b'{"mention_id": "m", "entity_id": "place:zz"}\n'],
     "not in entities"),
    ([_E_PERSON, _E_PERSON], [], "duplicate entity_id"),
    ([b'{"entity_id": "x:y", "type": "Verse", "mention_count": 1}\n'], [], "unknown entity type"),
    ([_E_PERSON, b"not json\n"], [], "not valid JSON"),
])
def test_split_rejects_inputs_the_pipeline_cannot_produce(entities, mentions, message):
    with pytest.raises(stages.StageError, match=message):
        stages.split_halves(entities, mentions)


def test_read_rejects_unterminated_last_line(tmp_path):
    path = tmp_path / "entities.jsonl"
    path.write_bytes(_E_PERSON + _E_EVENT.rstrip(b"\n"))
    with pytest.raises(stages.StageError, match="newline"):
        stages.read_jsonl_lines(path)


def test_freeze_refuses_source_that_would_not_roundtrip(tmp_path):
    # Grounded mention ahead of an NER one: the pipeline writes ner + grounded,
    # so merge could never reproduce this order and freezing would be lossy.
    src = tmp_path / "src"
    src.mkdir()
    (src / "entities.jsonl").write_bytes(_E_EVENT + _E_PERSON)
    (src / "entity_mentions.jsonl").write_bytes(_M_EVENT + _M_PERSON)
    with pytest.raises(stages.StageError, match="round-trip"):
        stages.freeze_grounded(src / "entities.jsonl", src / "entity_mentions.jsonl",
                               tmp_path / "frozen")
    assert not (tmp_path / "frozen").exists()


# ------------------------------------------------------------ freeze stage ---

def test_freeze_writes_grounded_half_and_manifest(tmp_path):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])

    frozen = out / "frozen"
    assert _types(frozen / "grounded_entities.jsonl") == GROUNDED
    manifest = json.loads((frozen / "grounded_manifest.json").read_text(encoding="utf-8"))
    for name, lines in (("grounded_entities.jsonl", 6), ("grounded_mentions.jsonl", 7)):
        assert manifest["files"][name] == {"sha256": _sha(frozen / name), "lines": lines}
    assert manifest["source"]["entities"]["sha256"] == _sha(FIXTURE_DIR / "entities.jsonl")
    assert manifest["source"]["entities"]["lines"] == 15
    assert manifest["source"]["entity_mentions"]["sha256"] == _sha(
        FIXTURE_DIR / "entity_mentions.jsonl")
    assert manifest["ner_half"]["entities"]["lines"] == 9
    assert manifest["ner_half"]["mentions"]["lines"] == 10
    # Per-type counts let merge say *what* changed when NER no longer matches.
    assert manifest["ner_half"]["type_counts"] == {"Group": 2, "Person": 4, "Place": 3}
    assert manifest["grounded_types"] == ["Event", "Object", "Theme"]
    assert "git_commit" in manifest and "git_dirty" in manifest
    datetime.fromisoformat(manifest["created_at"])
    # Freezing reads the source; it must never rewrite it.
    assert (out / "entities.jsonl").read_bytes() == (FIXTURE_DIR / "entities.jsonl").read_bytes()


def test_freeze_refuses_to_overwrite_without_force(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    manifest_path = out / "frozen" / "grounded_manifest.json"
    first = manifest_path.read_bytes()

    with pytest.raises(SystemExit) as exc:
        ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    assert exc.value.code == 1
    assert "--force" in caplog.text
    assert manifest_path.read_bytes() == first

    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--force"])
    assert json.loads(manifest_path.read_bytes())["files"] == json.loads(first)["files"]


def test_freeze_dry_run_writes_nothing(tmp_path):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out), "--dry-run"])
    assert not (out / "frozen").exists()


# ------------------------------------------------------------- merge stage ---

def _frozen_with_ner_half(tmp_path: Path) -> Path:
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "freeze-grounded", "-o", str(out)])
    _write_ner_half(out, FIXTURE_DIR)
    return out


def test_merge_points_to_missing_stages(tmp_path, caplog):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "--stage ner" in caplog.text

    _write_ner_half(out, FIXTURE_DIR)
    caplog.clear()
    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "--stage freeze-grounded" in caplog.text


def test_merge_rejects_tampered_frozen_snapshot(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    grounded = out / "frozen" / "grounded_entities.jsonl"
    grounded.write_bytes(grounded.read_bytes().replace("救贖".encode(), "救恩".encode()))
    before = (out / "entities.jsonl").read_bytes()

    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "sha256" in caplog.text
    assert (out / "entities.jsonl").read_bytes() == before


def test_merge_rejects_full_build_passed_as_ner_output(tmp_path, caplog):
    # The grounded entities would then sit in both halves.
    out = _frozen_with_ner_half(tmp_path)
    shutil.copyfile(out / "entities.jsonl", out / "ner_entities.jsonl")
    before = (out / "entities.jsonl").read_bytes()
    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "duplicate entity_id" in caplog.text
    assert (out / "entities.jsonl").read_bytes() == before


@pytest.mark.parametrize("halves", [
    stages.Halves((_E_EVENT,), (), (), ()),                       # grounded type in NER slot
    stages.Halves((_E_PERSON,), (), (_E_EVENT,), (_M_PERSON,)),   # NER mention in grounded slot
])
def test_merge_rejects_lines_in_the_wrong_half(halves):
    with pytest.raises(stages.StageError, match="wrong file"):
        stages.merge_halves(halves)


def test_merge_refuses_to_drop_an_unfrozen_grounded_half(tmp_path, caplog):
    out = _frozen_with_ner_half(tmp_path)
    # A newer grounded run landed in entities.jsonl after the snapshot was taken.
    entities = out / "entities.jsonl"
    changed = entities.read_bytes().replace("過紅海".encode(), "過約旦河".encode())
    entities.write_bytes(changed)

    with pytest.raises(SystemExit):
        ee.main(["--stage", "merge", "-o", str(out)])
    assert "frozen" in caplog.text
    assert entities.read_bytes() == changed

    ee.main(["--stage", "merge", "-o", str(out), "--force"])
    assert entities.read_bytes() == (FIXTURE_DIR / "entities.jsonl").read_bytes()


def test_merge_dry_run_writes_nothing(tmp_path):
    out = _frozen_with_ner_half(tmp_path)
    (out / "entities.jsonl").unlink()
    ee.main(["--stage", "merge", "-o", str(out), "--dry-run"])
    assert not (out / "entities.jsonl").exists()


# ----------------------------------------------------- ner stage / ner-only ---

def test_ner_only_refused_without_force(tmp_path, monkeypatch, caplog, queue):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    _forbid_extraction(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        ee.main(["--ner-only", "-i", str(queue), "-o", str(out)])
    assert exc.value.code == 1
    assert "--stage ner" in caplog.text
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        assert (out / name).read_bytes() == (FIXTURE_DIR / name).read_bytes()


def test_ner_only_with_force_keeps_legacy_behaviour(tmp_path, queue, fake_ner):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--ner-only", "--force", "-i", str(queue), "-o", str(out)])
    assert _types(out / "entities.jsonl") == {"Person", "Place", "Group"}


def test_ner_stage_leaves_entities_untouched(tmp_path, queue, fake_ner):
    out = _seed_output(tmp_path, FIXTURE_DIR)
    ee.main(["--stage", "ner", "-i", str(queue), "-o", str(out)])
    assert _types(out / "ner_entities.jsonl") == {"Person", "Place", "Group"}
    for name in ("entities.jsonl", "entity_mentions.jsonl"):
        assert (out / name).read_bytes() == (FIXTURE_DIR / name).read_bytes()


@pytest.mark.parametrize("argv", [
    ["--stage", "ner", "--ner-only"],
    ["--stage", "merge", "--legacy-llm"],
    ["--stage", "ner", "--dry-run"],
    ["--stage", "merge", "--accept-grounded-drift"],
    ["--accept-grounded-drift"],
])
def test_conflicting_flags_are_usage_errors(argv, tmp_path, monkeypatch):
    # If a check regressed, main() must fail here at once, not fall through to
    # the default pipeline (CKIP, Phase 4 LLM) on whatever data it can reach.
    _forbid_extraction(monkeypatch)
    missing = ["-i", str(tmp_path / "no_queue.jsonl"),
               "--bible-md-dir", str(tmp_path / "no_bible_md")]
    with pytest.raises(SystemExit) as exc:
        ee.main(argv + ["-o", str(tmp_path)] + missing)
    assert exc.value.code == 2
