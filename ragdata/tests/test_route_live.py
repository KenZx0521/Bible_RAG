"""The backend-side freezer and live probe (ragdata.legacy.route_live) on a fake backend."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import fake_backend
import ragcommon
import ragdata
from ragcommon import routing
from ragdata.legacy import route_live


@pytest.fixture()
def backend(tmp_path):
    return fake_backend.write(tmp_path)


def test_freeze_serializes_the_live_vocabulary_with_provenance(backend):
    doc = route_live.freeze(backend)
    lexicon = routing.parse_lexicon(doc)
    assert [t.canonical for t in lexicon.persons] == ["保羅", "掃羅", "哥尼流"]
    assert lexicon.persons[0].aliases == ("保羅", "掃羅")
    assert lexicon.events == ("保羅歸主", "天國", "渴慕")
    assert [b.name for b in lexicon.books] == ["使徒行傳", "以弗所書", "詩篇", "使徒"]
    assert all(e["provenance_class"] == "external_legacy" and e["retire_by"] == "R2"
               for category in routing.CATEGORIES for e in doc[category])
    assert set(doc["header"]["frozen_from"]) == set(fake_backend.SOURCES)
    assert "GROUP_DICT" in doc["header"]["not_frozen"]


def test_the_frozen_matcher_reproduces_the_live_one(backend):
    lexicon = routing.parse_lexicon(route_live.freeze(backend))
    texts = ["掃羅往大馬士革", "使徒行傳和以弗所書", "死海邊渴慕天國", "徒", "保羅歸主"]
    live = route_live.probe(backend, texts)
    assert live == [route_live.match_all(lexicon, t) for t in texts]


def _env():
    """Only ragdata and ragcommon on the path, as ``ragdata freeze`` runs it: the fake's own
    root, not whatever this process has on sys.path, provides scripts and bible_chunking."""
    roots = (Path(ragdata.__file__).resolve().parents[1],
             Path(ragcommon.__file__).resolve().parents[1])
    return {**os.environ, "PYTHONPATH": os.pathsep.join(str(r) for r in roots)}


def test_the_command_line_writes_files(backend, tmp_path):
    out = tmp_path / "lex.json"
    done = subprocess.run([sys.executable, "-m", "ragdata.legacy.route_live", "freeze",
                           "--backend-dir", str(backend), "--out", str(out)],
                          env=_env(), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert out.read_bytes() == routing.render_lexicon(route_live.freeze(backend))
    texts, result = tmp_path / "texts.json", tmp_path / "live.json"
    texts.write_text(json.dumps(["掃羅"], ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "ragdata.legacy.route_live", "probe",
                           "--backend-dir", str(backend), "--texts", str(texts),
                           "--out", str(result)], env=_env(), capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "sources": route_live.freeze(backend)["header"]["frozen_from"],
        "results": [{"persons": ["保羅", "掃羅"], "places": [], "events": [], "books": []}]}


def test_a_backend_without_entity_dicts_is_an_error(tmp_path):
    with pytest.raises(route_live.LiveError, match="entity_dicts"):
        route_live.freeze(tmp_path)


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sources_are_the_files_imported_not_the_backend_siblings(backend, tmp_path):
    """A backend dir not named ``backend`` runs its own utils/ next to an unchanged backend/."""
    changed = tmp_path / "backend_mod"
    shutil.copytree(backend, changed)
    dicts = changed / "utils" / "entity_dicts.py"
    dicts.write_text(dicts.read_text(encoding="utf-8").replace('"天國"', '"天國", "耶穌"'),
                     encoding="utf-8")
    sources = route_live.freeze(changed)["header"]["frozen_from"]
    assert sources["backend/utils/entity_dicts.py"] == _sha(dicts)
    assert sources["backend/utils/entity_dicts.py"] != _sha(backend / "utils" / "entity_dicts.py")
    assert sources["bible_chunking/config.py"] == _sha(tmp_path / "bible_chunking" / "config.py")
    probed = route_live.sourced_probe(changed, ["耶穌"])
    assert probed == {"sources": sources, "results": [
        {"persons": [], "places": [], "events": ["耶穌"], "books": []}]}


def test_a_source_not_imported_from_a_file_is_an_error(backend):
    dicts = backend / "utils" / "entity_dicts.py"
    dicts.write_text(dicts.read_text(encoding="utf-8").replace(
        "from scripts.entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT",
        fake_backend.ENTITY_DICT), encoding="utf-8")
    with pytest.raises(route_live.LiveError, match="scripts.entity_extraction.entity_dict"):
        route_live.freeze(backend)
    with pytest.raises(route_live.LiveError, match="scripts.entity_extraction.entity_dict"):
        route_live.probe(backend, ["掃羅"])
