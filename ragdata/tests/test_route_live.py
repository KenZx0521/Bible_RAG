"""The backend-side freezer and live probe (ragdata.legacy.route_live) on a fake backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import fake_backend
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
    paths = [p for p in sys.path if p]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}


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
    assert json.loads(result.read_text(encoding="utf-8")) == [
        {"persons": ["保羅", "掃羅"], "places": [], "events": [], "books": []}]


def test_a_backend_without_entity_dicts_is_an_error(tmp_path):
    with pytest.raises(route_live.LiveError, match="entity_dicts"):
        route_live.freeze(tmp_path)
