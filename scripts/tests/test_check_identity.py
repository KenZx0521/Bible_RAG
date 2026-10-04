"""check_identity: three-store identity comparison (plan §3.6 H5) and target resolution.

compare() is pure, so every diff kind gets a clean and a broken example
without any database. The live test only reads, and skips when a store is
not reachable.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

import check_identity as ci
import validate_kg as vk


def rec(type_="Person", name="馬可", aliases=None, description=""):
    return {"type": type_, "canonical_name": name,
            "aliases": [] if aliases is None else aliases, "description": description}


def test_identical_stores_have_no_differences():
    ref = {"person:make": rec()}
    out = ci.compare(ref, {"person:make": rec()})
    assert all(out["counts"][k] == 0 for k in ci.DIFF_KINDS)


def test_id_set_differences_both_ways():
    out = ci.compare({"a": rec(), "b": rec()}, {"b": rec(), "c": rec()})
    assert out["counts"]["only_in_reference"] == 1
    assert out["counts"]["only_in_store"] == 1
    assert out["samples"]["only_in_reference"] == ["a"]


@pytest.mark.parametrize("field,value,kind", [
    ("type_", "Place", "type"),
    ("name", "馬可 ", "canonical_name"),
    ("description", "約翰馬可", "description"),
])
def test_field_differences(field, value, kind):
    out = ci.compare({"x": rec()}, {"x": rec(**{field: value})})
    assert out["counts"][kind] == 1
    assert out["samples"][kind][0]["entity_id"] == "x"


def test_aliases_must_be_a_list():
    out = ci.compare({"x": rec()}, {"x": rec(aliases="[]")})
    assert out["counts"]["aliases_not_list"] == 1
    assert out["counts"]["aliases"] == 0  # a string is not compared element-wise


def test_alias_sets_compare_without_order():
    same = ci.compare({"x": rec(aliases=["甲", "乙"])}, {"x": rec(aliases=["乙", "甲"])})
    assert same["counts"]["aliases"] == 0
    diff = ci.compare({"x": rec(aliases=["甲", "乙"])}, {"x": rec(aliases=["甲"])})
    assert diff["counts"]["aliases"] == 1


def test_missing_description_equals_empty():
    out = ci.compare({"x": rec(description=None)}, {"x": rec(description="")})
    assert out["counts"]["description"] == 0


def test_samples_are_capped():
    ref = {f"e{i}": rec() for i in range(10)}
    other = {f"e{i}": rec(type_="Place") for i in range(10)}
    out = ci.compare(ref, other, sample_size=3)
    assert out["counts"]["type"] == 10
    assert len(out["samples"]["type"]) == 3


def test_qdrant_payload_keeps_string_aliases_visible():
    records = ci.records_from_payloads([
        {"entity_id": "person:make", "type": "Person", "canonical_name": "馬可",
         "aliases": "[]", "description": "d"},
    ])
    assert records["person:make"]["aliases"] == "[]"


def test_has_differences():
    clean = {"stores": {"pg": {"counts": dict.fromkeys(ci.DIFF_KINDS, 0)}}, "reference_aliases_not_list": 0}
    assert not ci.has_differences(clean)
    dirty = {"stores": {"pg": {"counts": {**dict.fromkeys(ci.DIFF_KINDS, 0), "description": 3}}},
             "reference_aliases_not_list": 0}
    assert ci.has_differences(dirty)


# ---------------------------------------------------------------------------
# target resolution: .env points at prod and must never leak into staging
# ---------------------------------------------------------------------------

DOTENV = {"NEO4J_URI": "bolt://localhost:7687", "POSTGRES_DB": "bible_rag",
          "QDRANT_ENTITY_COLLECTION": "bible_entities", "NEO4J_PASSWORD": "pw"}


def test_prod_reads_dotenv():
    t = ci.resolve_target("prod", environ={}, dotenv=DOTENV)
    assert (t.neo4j_uri, t.pg_db, t.qdrant_collection) == ("bolt://localhost:7687", "bible_rag", "bible_entities")
    assert t.neo4j_password == "pw"


def test_staging_ignores_dotenv_store_names():
    t = ci.resolve_target("staging", environ={}, dotenv=DOTENV)
    assert t.neo4j_uri == "bolt://localhost:7688"
    assert t.pg_db == "bible_rag_staging"
    assert t.qdrant_collection is None  # bible_entities_vN has no safe default
    assert t.neo4j_password == "pw"     # credentials still come from .env


def test_staging_honours_shell_environment():
    env = {"NEO4J_URI": "bolt://localhost:7699", "QDRANT_ENTITY_COLLECTION": "bible_entities_v2"}
    t = ci.resolve_target("staging", environ=env, dotenv=DOTENV)
    assert (t.neo4j_uri, t.qdrant_collection) == ("bolt://localhost:7699", "bible_entities_v2")


@pytest.mark.parametrize("key,value", [("NEO4J_URI", "bolt://localhost:7687"),
                                       ("POSTGRES_DB", "bible_rag"),
                                       ("QDRANT_ENTITY_COLLECTION", "bible_entities")])
def test_staging_refuses_to_resolve_to_prod(key, value):
    with pytest.raises(ValueError, match="prod"):
        ci.resolve_target("staging", environ={key: value}, dotenv=DOTENV)


def test_unknown_target_is_rejected():
    with pytest.raises(ValueError):
        ci.resolve_target("qa", environ={}, dotenv={})


def test_cli_refuses_staging_aimed_at_prod(monkeypatch, capsys):
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    assert ci.main(["--target", "staging"]) == 1
    assert "prod endpoint" in capsys.readouterr().err


@pytest.mark.parametrize("uri", ["bolt://localhost", "neo4j://localhost", "bolt://elsewhere:7687"])
def test_staging_refuses_a_uri_that_lands_on_the_prod_port(uri):
    # no port = the driver default 7687, which is production (kg_target's rule)
    with pytest.raises(ValueError, match="prod"):
        ci.resolve_target("staging", environ={"NEO4J_URI": uri}, dotenv=DOTENV)


# The R4 post-promotion check runs `--target prod`, often in the shell that
# still exports the staging settings (docs/build_database.md R1). prod must not
# quietly read staging there, nor a mix of staging and prod stores.
STAGING_SHELL = {"NEO4J_URI": "bolt://localhost:7688", "POSTGRES_DB": "bible_rag_staging",
                 "QDRANT_ENTITY_COLLECTION": "bible_entities_v2"}


@pytest.mark.parametrize("key", sorted(STAGING_SHELL))
def test_prod_refuses_a_shell_that_exports_a_staging_store(key):
    with pytest.raises(ValueError, match=key):
        ci.resolve_target("prod", environ={key: STAGING_SHELL[key]}, dotenv=DOTENV)


def test_prod_refuses_a_shell_marked_kg_target_staging():
    with pytest.raises(ValueError, match="KG_TARGET"):
        ci.resolve_target("prod", environ={"KG_TARGET": "staging"}, dotenv=DOTENV)


def test_prod_accepts_shell_values_that_equal_the_dotenv_ones():
    env = {"NEO4J_URI": "bolt://127.0.0.1:7687", "POSTGRES_DB": "bible_rag", "KG_TARGET": "prod"}
    assert ci.resolve_target("prod", environ=env, dotenv=DOTENV).pg_db == "bible_rag"


@pytest.mark.parametrize("key,value", [("NEO4J_URI", "bolt://localhost:7688"),
                                       ("POSTGRES_DB", "bible_rag_staging")])
def test_prod_refuses_staging_markers_even_from_dotenv(key, value):
    with pytest.raises(ValueError, match=key):
        ci.resolve_target("prod", environ={}, dotenv={**DOTENV, key: value})


def test_prod_collection_is_whatever_dotenv_promoted():
    # R3 promotes Qdrant by pointing .env at bible_entities_vN: that IS prod then
    dotenv = {**DOTENV, "QDRANT_ENTITY_COLLECTION": "bible_entities_v2"}
    assert ci.resolve_target("prod", environ={}, dotenv=dotenv).qdrant_collection == "bible_entities_v2"
    with pytest.raises(ValueError, match="QDRANT_ENTITY_COLLECTION"):
        ci.resolve_target("prod", environ={"QDRANT_ENTITY_COLLECTION": "bible_entities"}, dotenv=dotenv)


@pytest.mark.parametrize("environ,dotenv,port", [
    ({"QDRANT_PORT": "7333", "QDRANT_HTTP_PORT": "6334"}, {}, 7333),
    ({}, {"QDRANT_PORT": "7333", "QDRANT_HTTP_PORT": "6334"}, 7333),
    ({"QDRANT_HTTP_PORT": "6334"}, {}, 6334),
    ({}, {}, 6333),
])
def test_qdrant_port_wins_over_qdrant_http_port(environ, dotenv, port):
    # same precedence as the F env-var convention: QDRANT_PORT, then QDRANT_HTTP_PORT, then 6333
    assert ci.resolve_target("prod", environ=environ, dotenv={**DOTENV, **dotenv}).qdrant_port == port


# ---------------------------------------------------------------------------
# --fail-on: batch 0 gates on the id sets while 1D-scoped drift is known
# ---------------------------------------------------------------------------

def report_with(qdrant=None, reference_aliases_not_list=0, **pg_counts):
    return {"target": "staging", "neo4j_uri": "bolt://localhost:7688", "reference_count": 1,
            "reference_aliases_not_list": reference_aliases_not_list,
            "stores": {"pg": {"store": "postgres:x.entities", "count": 1,
                              "samples": {k: [] for k in ci.DIFF_KINDS},
                              "counts": {**dict.fromkeys(ci.DIFF_KINDS, 0), **pg_counts}},
                       "qdrant": qdrant or {"store": "qdrant:x", "count": 1,
                                            "samples": {k: [] for k in ci.DIFF_KINDS},
                                            "counts": dict.fromkeys(ci.DIFF_KINDS, 0)}}}


@pytest.mark.parametrize("fail_on,report,expected", [
    (("id",), report_with(description=3045, aliases_not_list=9093), False),
    (("id",), report_with(only_in_store=1), True),
    (("description",), report_with(description=3045), True),
    (("aliases",), report_with(aliases_not_list=9093), True),
    (("aliases",), report_with(reference_aliases_not_list=2), True),
    (("type", "canonical"), report_with(aliases=14, description=3045), False),
    (("canonical",), report_with(canonical_name=1), True),
])
def test_fail_on_selects_the_difference_kinds_that_count(fail_on, report, expected):
    assert ci.has_differences(report, fail_on) is expected


def _fake_run(monkeypatch, report):
    monkeypatch.setattr(ci, "resolve_target", lambda name: name)
    monkeypatch.setattr(ci, "run", lambda target, sample_size: report)


def test_cli_fail_on_id_passes_with_known_field_drift(monkeypatch, capsys):
    _fake_run(monkeypatch, report_with(description=3045))
    assert ci.main(["--target", "staging", "--fail-on", "id"]) == 0
    assert ci.main(["--target", "staging"]) == 1  # default: every kind counts


def test_cli_rejects_an_unknown_fail_on_kind(capsys):
    with pytest.raises(SystemExit):
        ci.main(["--fail-on", "ids"])


def test_cli_skipped_store_is_never_a_pass(monkeypatch, capsys):
    # staging without QDRANT_ENTITY_COLLECTION: the Qdrant id set was not compared
    _fake_run(monkeypatch, report_with(qdrant={"skipped": "no entity collection for this target"}))
    assert ci.main(["--target", "staging", "--fail-on", "id"]) == 1
    assert "qdrant" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# run() through fake connections, and validate_kg's H5 on top of it
# ---------------------------------------------------------------------------

def fake_stores(monkeypatch, rows: list[dict]) -> list[tuple]:
    """psycopg2.connect / QdrantClient serving `rows` as PG entities and the
    entity collection; returns the log of the stores opened."""
    import psycopg2
    import qdrant_client
    opened: list[tuple] = []
    cursor = SimpleNamespace(execute=lambda sql: None, fetchall=lambda: rows)
    conn = SimpleNamespace(set_session=lambda readonly: opened.append(("pg_readonly", readonly)),
                           cursor=lambda cursor_factory=None: contextlib.nullcontext(cursor), close=lambda: None)
    client = SimpleNamespace(scroll=lambda name, **kw: opened.append(("scroll", name)) or (
        [SimpleNamespace(payload=r) for r in rows], None))
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: opened.append(("pg", kw["dbname"])) or conn)
    monkeypatch.setattr(qdrant_client, "QdrantClient", lambda **kw: opened.append(("qdrant", kw["port"])) or client)
    return opened


@pytest.mark.parametrize("collection", [None, "bible_entities_v2"])
def test_h5_live_staging_without_a_collection_is_unmeasured(monkeypatch, collection):
    # E-2: validate_kg's H5 on staging without QDRANT_ENTITY_COLLECTION must not
    # read the skipped Qdrant half as n/a: it is unmeasured, so the gate exits 1
    node = {"entity_id": "person:make", "labels": ["Person"], "is_entity": True,
            "canonical_name": "馬可", "aliases": ["約翰"], "description": "約翰馬可"}
    opened = fake_stores(monkeypatch, [{**rec(aliases=["約翰"], description="約翰馬可"), "entity_id": "person:make"}])
    environ = {"QDRANT_ENTITY_COLLECTION": collection} if collection else {}
    ctx = vk.Context(baseline=vk.load_baseline(vk.DEFAULT_BASELINE), probes={},
                     target=ci.resolve_target("staging", environ=environ, dotenv={}))
    report = vk.evaluate(vk.run_checks(vk.KG(mode="live", entity_rows=[node]), ctx, only={"H5"}), ctx.baseline)
    h5 = report["checks"]["H5"]["metrics"]
    assert h5["pg_only_in_reference"]["status"] == "ok"
    assert opened[:2] == [("pg", "bible_rag_staging"), ("pg_readonly", True)]
    if collection is None:
        assert {n: m["status"] for n, m in h5.items() if n.startswith("qdrant_")} == \
            dict.fromkeys((f"qdrant_{k}" for k in ci.DIFF_KINDS), "unmeasured")
        assert report["exit_code"] == 1 and len(opened) == 2  # Qdrant never opened
    else:
        assert {m["status"] for m in h5.values()} == {"ok"} and report["exit_code"] == 0
        assert opened[2:] == [("qdrant", 6333), ("scroll", collection)]


# ---------------------------------------------------------------------------
# live (read-only)
# ---------------------------------------------------------------------------

def test_live_prod_id_sets_agree():
    try:  # resolving is inside: a shell that sourced staging.env refuses prod, which is a skip
        report = ci.run(ci.resolve_target("prod"), sample_size=3)
    except Exception as e:  # noqa: BLE001  (a store being down or refused means "skip", not "fail")
        pytest.skip(f"prod stores not readable from this shell: {e}")
    assert report["reference_count"] > 0
    for store in ("pg", "qdrant"):
        counts = report["stores"][store]["counts"]
        assert counts["only_in_reference"] == 0 and counts["only_in_store"] == 0, store


def test_live_prod_test_skips_in_a_staging_shell(monkeypatch):
    # run.sh from a shell that sourced scripts/tools/staging.env
    for key, value in {**STAGING_SHELL, "KG_TARGET": "staging"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci, "run", lambda *a, **k: pytest.fail("prod must be refused before any read"))
    with pytest.raises(pytest.skip.Exception, match="refused"):
        test_live_prod_id_sets_agree()
