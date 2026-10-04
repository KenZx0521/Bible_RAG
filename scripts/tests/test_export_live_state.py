"""scripts/tools/export_live_state.py — read-only freeze of live-only KG state.

Plan §3.5.1: Step 7 descriptions, aliases and curated MENTIONS exist only in
live Neo4j. The export seeds the description cache (same format as
desc_generator's cache, so `--replay` consumes it directly) and freezes the
identity fields plus curated anchors, with a manifest of counts and sha256.

A fake session answers the module's Cypher constants; it only supports
execute_read, so any write path would fail the tests.

`--promote` makes the seed the official cache (output/frozen/descriptions.jsonl)
that every rebuild replays. The seed's titles_sha is computed on live, i.e.
after 10.2 cleanup and 10.4/10.5 curated edges, so replay must run after the
curated overlay: a MENTIONS-level simulation checks that, and that the
runbook's chain says so.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.relation_extraction import desc_generator as dg
from scripts.tools import export_live_state as els

EXPORTED_AT = "2026-10-04T12:00:00+08:00"

ENTITY_ROWS = [
    # Rows arrive ordered by entity_id, exactly as the shared titles query returns.
    {"entity_id": "event:shijie", "canonical_name": "十誡", "aliases": ["頒布十誡"],
     "type": "Event", "labels": ["Event", "Entity"], "description": "神在西奈山頒布律法",
     "titles": ["十誡"]},
    {"entity_id": "person:moxi", "canonical_name": "摩西", "aliases": [],
     "type": "Person", "labels": ["Person", "Entity"], "description": "以色列的領袖",
     "titles": ["(無標題)", "上帝呼召摩西"]},
    {"entity_id": "place:dan", "canonical_name": "但", "aliases": ["拉億"],
     "type": "Place", "labels": ["Entity", "Place"], "description": "",
     "titles": ["亞伯蘭搶救羅得"]},
    {"entity_id": "group:x", "canonical_name": "某族", "aliases": [],
     "type": "Group", "labels": ["Group", "Entity"], "description": None,
     "titles": []},
]

CURATED_ROWS = [
    {"source_id": "act:9:1", "source_label": "Pericope",
     "entity_id": "event:baoluoxushuguizhudejingguo",
     "props": {"source": "manual_patch", "curated": True}},
    {"source_id": "mat:5:0", "source_label": "Pericope",
     "entity_id": "event:shanshangbaoxun",
     "props": {"source": "head_event_backfill", "curated": True}},
]


class FakeTx:
    def __init__(self, log):
        self.log = log

    def run(self, query, **params):
        self.log.append((query, params))
        if query == els._ENTITY_STATE_CYPHER:
            return [dict(r) for r in ENTITY_ROWS]
        if query == els._CURATED_MENTIONS_CYPHER:
            return [dict(r) for r in CURATED_ROWS]
        raise AssertionError(f"unexpected query: {query[:80]}")


class ReadOnlySession:
    """Only read transactions exist here; auto-commit/write calls fail."""

    def __init__(self):
        self.log = []

    def execute_read(self, fn, *args, **kwargs):
        return fn(FakeTx(self.log), *args, **kwargs)

    def run(self, *a, **k):
        raise AssertionError("export must use read transactions only")

    def execute_write(self, *a, **k):
        raise AssertionError("export must never write")


def _read_jsonl(path):
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _export(tmp_path, neo4j_uri="bolt://localhost:7687", **kw):
    out_dir = tmp_path / "live_state" / "20261004"
    session = ReadOnlySession()
    result = els.export(session, out_dir, exported_at=EXPORTED_AT, neo4j_uri=neo4j_uri, **kw)
    return out_dir, session, result


def test_entity_query_reuses_desc_generator_title_computation():
    assert els._ENTITY_STATE_CYPHER == dg.titles_cypher("true")


def test_curated_mentions_query_selects_flag_or_curated_sources(tmp_path):
    _, session, _ = _export(tmp_path)
    assert "m.curated = true OR m.source IN $curated_sources" in els._CURATED_MENTIONS_CYPHER
    params = [p for q, p in session.log if q == els._CURATED_MENTIONS_CYPHER]
    assert params == [{"curated_sources": ["head_event_backfill", "manual_patch"]}]


def test_description_seed_matches_cache_format(tmp_path):
    out_dir, _, _ = _export(tmp_path)

    seed = _read_jsonl(out_dir / "descriptions.jsonl")

    # Only non-empty descriptions are seeded; empty/None have nothing to replay.
    assert [s["entity_id"] for s in seed] == ["event:shijie", "person:moxi"]
    for s in seed:
        assert list(s) == list(dg.CACHE_FIELDS)
        assert s["model"] == "live_export_unknown"
        assert s["prompt_version"] == "live_export_unknown"
        # How the live text was made is recorded nowhere: no temperature, and
        # the commit is unknown (the export's own HEAD is in the manifest).
        assert s["temperature"] is None
        assert s["git_commit"] == "live_export_unknown"
        assert s["quality_flag"] == "unreviewed"
        assert s["generated_at"] == EXPORTED_AT
    assert seed[1]["description"] == "以色列的領袖"
    assert seed[1]["titles_sha"] == dg.titles_sha(["(無標題)", "上帝呼召摩西"])


def test_entities_and_curated_mentions_files(tmp_path):
    out_dir, _, _ = _export(tmp_path)

    entities = _read_jsonl(out_dir / "entities.jsonl")
    mentions = _read_jsonl(out_dir / "curated_mentions.jsonl")

    assert [e["entity_id"] for e in entities] == [r["entity_id"] for r in ENTITY_ROWS]
    assert entities[2] == {"entity_id": "place:dan", "labels": ["Entity", "Place"],
                           "canonical_name": "但", "aliases": ["拉億"]}
    assert all(e["labels"] == sorted(e["labels"]) for e in entities)
    assert mentions == CURATED_ROWS


def test_manifest_counts_and_sha_match_files(tmp_path):
    out_dir, _, result = _export(tmp_path)

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest == result
    assert manifest["exported_at"] == EXPORTED_AT
    assert manifest["neo4j_uri"] == "bolt://localhost:7687"
    assert set(manifest["files"]) == {
        "descriptions.jsonl", "entities.jsonl", "curated_mentions.jsonl"}
    for name, meta in manifest["files"].items():
        data = (out_dir / name).read_bytes()
        assert meta["count"] == len(data.splitlines())
        assert meta["sha256"] == hashlib.sha256(data).hexdigest()
    assert manifest["counts"]["descriptions_by_type"] == {"Event": 1, "Person": 1}
    assert manifest["counts"]["entities_by_type"] == {
        "Event": 1, "Group": 1, "Person": 1, "Place": 1}
    assert manifest["counts"]["curated_mentions_by_source"] == {
        "head_event_backfill": 1, "manual_patch": 1}


def test_dry_run_reports_counts_and_writes_nothing(tmp_path, capsys):
    out_dir, _, result = _export(tmp_path, dry_run=True)

    assert not out_dir.exists()
    assert result["files"]["descriptions.jsonl"]["count"] == 2
    assert result["files"]["entities.jsonl"]["count"] == 4
    assert result["files"]["curated_mentions.jsonl"]["count"] == 2
    assert "sha256" not in result["files"]["descriptions.jsonl"]
    assert "descriptions.jsonl" in capsys.readouterr().out


def test_refuses_to_overwrite_existing_export_without_force(tmp_path):
    out_dir, _, _ = _export(tmp_path)
    first = (out_dir / "manifest.json").read_bytes()

    with pytest.raises(SystemExit):
        _export(tmp_path)
    assert (out_dir / "manifest.json").read_bytes() == first

    _export(tmp_path, force=True)


def test_default_out_dir_is_dated_under_output_frozen():
    args = els._build_parser().parse_args([])
    assert args.out_dir.parent == els._PROJECT_ROOT / "output" / "frozen" / "live_state"
    assert len(args.out_dir.name) == 8 and args.out_dir.name.isdigit()


# ---------------------------------------------------------------------------
# --promote: the seed becomes the official cache every rebuild replays
# ---------------------------------------------------------------------------

def _official(tmp_path):
    return tmp_path / "frozen" / "descriptions.jsonl"


def test_promote_copies_the_seed_to_the_official_cache(tmp_path):
    out_dir, _, _ = _export(tmp_path)
    cache = _official(tmp_path)

    els.promote(out_dir, cache)

    assert cache.read_bytes() == (out_dir / "descriptions.jsonl").read_bytes()
    assert set(dg.load_cache(cache)) == {"event:shijie", "person:moxi"}


def test_promote_refuses_to_replace_an_existing_cache_without_force(tmp_path):
    out_dir, _, _ = _export(tmp_path)
    cache = _official(tmp_path)
    cache.parent.mkdir(parents=True)
    cache.write_text("generated earlier\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="--force"):
        els.promote(out_dir, cache)
    assert cache.read_text(encoding="utf-8") == "generated earlier\n"

    els.promote(out_dir, cache, force=True)
    assert cache.read_bytes() == (out_dir / "descriptions.jsonl").read_bytes()


def _drop_temperature_and_reseal(out_dir):
    """A seed in the pre-provenance format, with a manifest that still matches."""
    seed = out_dir / "descriptions.jsonl"
    lines = [json.loads(line) for line in seed.read_text(encoding="utf-8").splitlines()]
    data = "".join(json.dumps({k: v for k, v in e.items() if k != "temperature"},
                              ensure_ascii=False) + "\n" for e in lines).encode("utf-8")
    seed.write_bytes(data)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["descriptions.jsonl"]["sha256"] = hashlib.sha256(data).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _append_to_seed(out_dir):
    with (out_dir / "descriptions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{}\n")


@pytest.mark.parametrize("damage, match", [
    (lambda d: (d / "manifest.json").unlink(), "manifest"),
    (_append_to_seed, "sha256"),
    (_drop_temperature_and_reseal, "temperature"),
])
def test_promote_refuses_an_incomplete_altered_or_stale_format_export(tmp_path, damage, match):
    out_dir, _, _ = _export(tmp_path)
    damage(out_dir)
    cache = _official(tmp_path)

    with pytest.raises(SystemExit, match=match):
        els.promote(out_dir, cache)
    assert not cache.exists()


def test_promote_dry_run_writes_nothing(tmp_path, capsys):
    out_dir, _, _ = _export(tmp_path)
    cache = _official(tmp_path)

    els.promote(out_dir, cache, dry_run=True)

    assert not cache.exists()
    assert str(cache) in capsys.readouterr().out


def test_main_promote_never_connects_to_neo4j(tmp_path, monkeypatch):
    monkeypatch.delenv("KG_TARGET", raising=False)
    out_dir, _, _ = _export(tmp_path)
    cache = _official(tmp_path)
    monkeypatch.setattr(els.GraphDatabase, "driver",
                        lambda *a, **k: pytest.fail("--promote connected to Neo4j"))

    assert els.main(["--promote", "--out-dir", str(out_dir), "--cache", str(cache)]) == 0
    assert cache.exists()


@pytest.fixture
def prod_dotenv(monkeypatch, tmp_path):
    """kg_target reads a tmp .env whose production Neo4j is not on port 7687."""
    path = tmp_path / "prod.env"
    path.write_text("NEO4J_URI=bolt://prod-host:17687\n", encoding="utf-8")
    monkeypatch.setattr(els.kg_target, "DOTENV_PATH", path)


@pytest.mark.parametrize("uri", ["bolt://localhost:7687", "neo4j://db-host:7687",
                                 "bolt://localhost", "bolt://prod-host:17687"])
def test_promote_accepts_an_export_of_production(tmp_path, prod_dotenv, uri):
    """Port 7687 (also when left implicit) or .env's NEO4J_URI is production."""
    out_dir, _, _ = _export(tmp_path, neo4j_uri=uri)
    cache = _official(tmp_path)

    els.promote(out_dir, cache)

    assert cache.read_bytes() == (out_dir / "descriptions.jsonl").read_bytes()


@pytest.mark.parametrize("uri", ["bolt://localhost:7688", None])
def test_promote_refuses_an_export_not_taken_from_production_without_force(
        tmp_path, prod_dotenv, uri):
    """A staging export promoted by mistake would be replayed by every rebuild."""
    out_dir, _, _ = _export(tmp_path, neo4j_uri=uri)
    cache = _official(tmp_path)

    for dry_run in (True, False):
        with pytest.raises(SystemExit, match="--force") as exc:
            els.promote(out_dir, cache, dry_run=dry_run)
        assert f"neo4j_uri={uri!r}" in str(exc.value)
    assert not cache.exists()

    els.promote(out_dir, cache, force=True)
    assert cache.read_bytes() == (out_dir / "descriptions.jsonl").read_bytes()


@pytest.mark.parametrize("argv", [["--dry-run"], ["--promote"]])
def test_refuses_to_run_under_a_staging_target(tmp_path, monkeypatch, argv):
    """It freezes production's state; from a staging.env shell it would freeze staging's."""
    out_dir, _, _ = _export(tmp_path)
    cache = _official(tmp_path)
    monkeypatch.setenv("KG_TARGET", "staging")
    monkeypatch.setattr(els.GraphDatabase, "driver",
                        lambda *a, **k: pytest.fail("connected to Neo4j under staging"))

    with pytest.raises(SystemExit, match="KG_TARGET=staging refused") as exc:
        els.main([*argv, "--out-dir", str(out_dir), "--cache", str(cache)])

    assert "production" in str(exc.value)
    assert not cache.exists()


def test_promote_target_is_the_cache_replay_reads_by_default(monkeypatch, tmp_path):
    """Whatever resolves desc_generator's default --cache is where --promote writes."""
    monkeypatch.delenv("DESC_CACHE_PATH", raising=False)
    assert els._build_parser().parse_args([]).cache == dg.DEFAULT_CACHE_PATH
    assert dg._build_parser().parse_args(["--replay"]).cache == dg.DEFAULT_CACHE_PATH

    monkeypatch.setenv("DESC_CACHE_PATH", str(tmp_path / "c.jsonl"))
    assert els._build_parser().parse_args([]).cache == tmp_path / "c.jsonl"
    assert dg._build_parser().parse_args(["--replay"]).cache == tmp_path / "c.jsonl"


# ---------------------------------------------------------------------------
# Where replay sits in the rebuild chain (review finding: Step 7 before 10.x)
# ---------------------------------------------------------------------------

_MANUAL = {"curated": True, "source": "manual_patch"}
_HEAD = {"curated": True, "source": "head_event_backfill"}


def _m(source_id, title, entity_id, props=None):
    return {"source_id": source_id, "title": title, "entity_id": entity_id,
            "props": dict(props or {})}


# Live after 10.1–10.5, the state export_live_state reads.
LIVE_ENTITIES = {
    "place:dan": {"canonical_name": "但", "type": "Place", "aliases": ["拉億"],
                  "description": "以色列最北端的城，原名拉億"},
    "person:yeteluo": {"canonical_name": "葉忒羅", "type": "Person", "aliases": ["流珥"],
                       "description": "米甸祭司，摩西的岳父"},
    "person:moxi": {"canonical_name": "摩西", "type": "Person", "aliases": [],
                    "description": "帶領以色列人出埃及的領袖"},
    "event:shanshangbaoxun": {"canonical_name": "山上寶訓", "type": "Event",
                              "aliases": ["登山寶訓"], "description": "耶穌在山上教導門徒"},
    "event:zuihoudewancan": {"canonical_name": "最後的晚餐", "type": "Event", "aliases": [],
                             "description": "耶穌被賣前與門徒同吃逾越節晚餐"},
}
HEAD_EVENT_IDS = ("event:zuihoudewancan",)   # created by 10.4, in no JSONL
LIVE_MENTIONS = [
    _m("gen:14:1", "(無標題)", "place:dan"),
    _m("gen:14:13", "亞伯蘭搶救羅得", "place:dan"),
    _m("exo:1:8", "以色列人在埃及受虐待", "place:dan"),
    _m("jdg:18:1", "但支派奪取拉億", "place:dan"),
    _m("jos:19:40", "但支派的地業", "place:dan"),
    _m("1ki:12:25", "耶羅波安造金牛犢", "place:dan"),
    _m("exo:2:15", "摩西逃往米甸", "person:yeteluo"),
    _m("exo:3:1", "神在荊棘中呼召摩西", "person:yeteluo"),
    _m("exo:4:18", "摩西回埃及", "person:yeteluo"),
    _m("exo:18:13", "選立百姓的官長", "person:yeteluo", _MANUAL),   # added by 10.5
    _m("exo:2:1", "摩西出生", "person:moxi"),
    _m("exo:3:1", "神在荊棘中呼召摩西", "person:moxi"),
    _m("mat:6:1", "論施捨", "event:shanshangbaoxun"),
    _m("mat:5:1", "八福", "event:shanshangbaoxun", _HEAD),           # added by 10.4
    _m("mat:26:17", "逾越節的晚餐", "event:zuihoudewancan", _HEAD),
    _m("luk:22:14", "設立聖餐", "event:zuihoudewancan", _HEAD),
]
# 「但」 substring mis-hits that Step 5 imports and 10.2 deletes. '*' and '一'
# sort before '亞', so before 10.2 they take five of the six title slots.
DAN_MISHITS = [
    _m("2ki:20:1", "*王下20‧1－3", "place:dan"),
    _m("mrk:7:24", "一個婦人的信心", "place:dan"),
    _m("1co:12:12", "一個身體有許多肢體", "place:dan"),
    _m("rev:20:1", "一千年", "place:dan"),
    _m("ezr:2:1", "七十個人回來", "place:dan"),
]


class MentionGraph:
    """Neo4j stand-in whose title lists are derived from its MENTIONS edges.

    test_desc_replay.FakeGraph stores titles per entity, so a seed exported
    from it replays with 0 stale by construction. Here titles follow the
    edges with titles_cypher's rule (distinct non-empty titles in code-point
    order, first six): deleting or adding an edge moves titles_sha exactly as
    on the real graph, so the chain position of replay is what is tested.
    """

    def __init__(self, entities, mentions, read_only=False):
        self.entities = {eid: dict(e) for eid, e in entities.items()}
        self.mentions = [dict(m) for m in mentions]
        self.read_only = read_only

    def titles(self, eid):
        return sorted({m["title"] for m in self.mentions
                       if m["entity_id"] == eid and m["title"]})[:6]

    def _row(self, eid):
        e = self.entities[eid]
        return {"entity_id": eid, "canonical_name": e["canonical_name"],
                "aliases": list(e["aliases"]), "type": e["type"],
                "labels": ["Entity", e["type"]], "description": e["description"],
                "titles": self.titles(eid)}

    def descriptions(self):
        return {eid: e["description"] for eid, e in self.entities.items()}

    # Driver, session and transaction protocol in one object.
    def session(self):
        return self

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, fn, *args, **kwargs):
        return fn(self, *args, **kwargs)

    def run(self, query, **params):
        if query in (els._ENTITY_STATE_CYPHER, dg._FETCH_BY_IDS_CYPHER):
            wanted = params.get("entity_ids", self.entities)
            return [self._row(eid) for eid in sorted(set(wanted) & set(self.entities))]
        if query == els._CURATED_MENTIONS_CYPHER:
            return [{"source_id": m["source_id"], "source_label": "Pericope",
                     "entity_id": m["entity_id"], "props": dict(m["props"])}
                    for m in sorted(self.mentions, key=lambda m: (m["entity_id"], m["source_id"]))
                    if m["props"].get("curated")
                    or m["props"].get("source") in params["curated_sources"]]
        if query == dg._UPDATE_DESC_CYPHER and not self.read_only:
            for r in params["rows"]:
                self.entities[r["entity_id"]]["description"] = r["description"]
            return []
        raise AssertionError(f"unexpected query (read_only={self.read_only}): {query[:80]}")


def _step5_staging():
    """Staging after Steps 5 and 6.1: entities.jsonl and its MENTIONS only.

    P/P/G descriptions are empty (Step 7 only ever wrote Neo4j), E/O/T keep
    the extraction's; the 10.4 head event and every curated edge are absent,
    and place:dan still carries its mis-hits.
    """
    entities = {eid: {**e, "description": e["description"] if e["type"] == "Event" else ""}
                for eid, e in LIVE_ENTITIES.items() if eid not in HEAD_EVENT_IDS}
    mentions = [m for m in LIVE_MENTIONS if not m["props"].get("curated")] + DAN_MISHITS
    return MentionGraph(entities, mentions)


def _cleanup_noise_10_2(graph):
    graph.mentions = [m for m in graph.mentions if m not in DAN_MISHITS]


def _head_events_10_4(graph):
    for eid in HEAD_EVENT_IDS:
        graph.entities[eid] = dict(LIVE_ENTITIES[eid])   # NEW_EVENTS carry their description
    graph.mentions += [m for m in LIVE_MENTIONS if m["props"].get("source") == "head_event_backfill"]


def _manual_patches_10_5(graph):
    # Edges and aliases only: 10.5 never sets description on an extracted node.
    graph.mentions += [m for m in LIVE_MENTIONS if m["props"].get("source") == "manual_patch"]


CURATED_OVERLAY = (_cleanup_noise_10_2, _head_events_10_4, _manual_patches_10_5)


def _r0_seed(tmp_path):
    """R0: export live (read-only), then promote the seed to the official cache."""
    out_dir = tmp_path / "live_state" / "20261004"
    els.export(MentionGraph(LIVE_ENTITIES, LIVE_MENTIONS, read_only=True), out_dir,
               exported_at=EXPORTED_AT, neo4j_uri="bolt://localhost:7687")
    cache = _official(tmp_path)
    els.promote(out_dir, cache)
    return cache


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(dg, "_generate_description",
                        lambda *a, **k: pytest.fail("LLM called during replay"))


def test_replay_after_curated_overlay_reproduces_every_live_description(tmp_path, no_llm):
    """Chain order 10.1–10.5 → 7: the batch 0 gate "staging descriptions equal live"."""
    cache = _r0_seed(tmp_path)
    staging = _step5_staging()
    for step in CURATED_OVERLAY:
        step(staging)
    assert staging.descriptions()["place:dan"] == staging.descriptions()["person:yeteluo"] == ""

    summary = dg.replay(staging, cache, dry_run=False, write_batch=50)

    assert summary["stale"] == [] and summary["missing"] == []
    assert staging.descriptions() == {eid: e["description"] for eid, e in LIVE_ENTITIES.items()}


def test_replay_before_curated_overlay_loses_descriptions(tmp_path, no_llm):
    """The old order 7 → 10.x: the seed's titles_sha describes post-10.x MENTIONS.

    place:dan still has its mis-hit titles and person:yeteluo lacks the
    manual_patch one, so both are stale; 10.5 writes no description, so they
    stay empty for good. The head event is missing until 10.4 creates it.
    """
    cache = _r0_seed(tmp_path)
    staging = _step5_staging()

    summary = dg.replay(staging, cache, dry_run=False, write_batch=50)
    for step in CURATED_OVERLAY:
        step(staging)

    assert summary["stale"] == ["event:shanshangbaoxun", "person:yeteluo", "place:dan"]
    assert summary["missing"] == ["event:zuihoudewancan"]
    assert staging.descriptions()["place:dan"] == ""
    assert staging.descriptions()["person:yeteluo"] == ""


_DOC = Path(__file__).resolve().parents[2] / "docs" / "build_database.md"
# 8a builds the collection 10.4/10.5 write to; replay needs 10.5's MENTIONS;
# 8b re-embeds with the replayed descriptions; 10.6 checks the final state.
_CHAIN_ORDER = ("5", "6.1", "8a", "10.1", "7", "8b", "10.6")


def _positions(labels, keys):
    return [next(i for i, label in enumerate(labels) if label.startswith(key)) for key in keys]


def test_documented_rebuild_chain_replays_after_curated_overlay():
    text = _DOC.read_text(encoding="utf-8")
    chain = re.search(r"^\s*\*\*(0 → .+?)\*\*\s*$", text, re.M)
    labels = [step.strip() for step in chain.group(1).split("→")]

    rows = []
    for line in text[chain.end():].lstrip("\n").splitlines():
        if not line.strip().startswith("|"):
            break
        rows.append(line.strip().split("|")[1].strip())
    table = [r for r in rows if r and r != "順序" and not set(r) <= {"-", ":"}]

    for sequence in (labels, table):
        positions = _positions(sequence, _CHAIN_ORDER)
        assert positions == sorted(positions), (sequence, _CHAIN_ORDER)
