"""loader.promote over a scripted connection: the history promote appends to, and rollback."""

from __future__ import annotations

import pytest

from fake_dbapi import FakeConn
from ragdata.loader import promote as promoter
from ragdata.loader.pg import PgDb

D0, D1, D2 = ("sha256:" + c * 64 for c in "abc")


def _db(serving=None, history=(), builds=("b0", "b1", "b2")):
    """A connection whose rag_meta holds ``serving`` (build, digest) for the env, the env's
    active ``history`` rows (seq, build, digest; newest first) and ``builds``."""
    def answer(statement, params):
        if 'FROM "rag_meta"."builds"' in statement:
            return [(1,)] if params[0] in builds else []
        if 'FROM "rag_meta"."serving_history"' in statement:
            return list(history)
        if 'FROM "rag_meta"."serving"' in statement:
            return [serving] if serving else []
        return []
    conn = FakeConn(answer)
    return PgDb(conn), conn


def _writes(conn):
    return [s for s in conn.statements() if s.split()[0] in ("INSERT", "UPDATE", "DELETE")]


def _kinds(conn):
    return [entry[0] for entry in conn.log]


# ------------------------------------------------------------------ promote

def test_promote_records_the_pair_in_the_history_in_the_same_transaction():
    db, conn = _db(serving=("b0", D0))

    before = promoter.promote(db, "staging", "b1", D1)

    assert before == promoter.Serving("staging", "b0", D0)
    ddl = conn.statements()[0]
    assert ddl.startswith('CREATE TABLE IF NOT EXISTS "rag_meta"."serving_history"')
    serving, history = _writes(conn)
    assert serving.startswith('INSERT INTO "rag_meta"."serving"') and "ON CONFLICT" in serving
    assert history.startswith('INSERT INTO "rag_meta"."serving_history"')
    assert conn.log[-2][2] == ("staging", "b1", D1)
    assert _kinds(conn)[-1] == "commit" and _kinds(conn).count("commit") == 1


def test_promoting_the_pair_already_served_writes_nothing():
    db, conn = _db(serving=("b1", D1))

    assert promoter.promote(db, "staging", "b1", D1) == promoter.Serving("staging", "b1", D1)
    assert _writes(conn) == []


def test_promote_rejects_an_image_tag_instead_of_a_digest():
    db, conn = _db()

    with pytest.raises(promoter.PromoteError, match="digest"):
        promoter.promote(db, "staging", "b1", "bible_rag-backend:r1")
    assert conn.log == []


# ------------------------------------------------------------------ rollback

def test_rollback_restores_the_pair_before_the_newest_and_marks_the_newest_rolled_back():
    db, conn = _db(serving=("b1", D1), history=[(2, "b1", D1), (1, "b0", D0)])

    done = promoter.rollback(db, "staging")

    assert done == promoter.Rollback(promoter.Serving("staging", "b1", D1),
                                     promoter.Serving("staging", "b0", D0))
    mark, restore = _writes(conn)
    assert mark.startswith('UPDATE "rag_meta"."serving_history"') and "rolled_back_at" in mark
    assert restore.startswith('UPDATE "rag_meta"."serving"')
    params = [entry[2] for entry in conn.log if entry[0] == "execute"]
    assert (2,) in params and ("b0", D0, "staging") in params
    assert _kinds(conn)[-1] == "commit" and "rollback" not in _kinds(conn)


def test_rolling_back_the_first_promote_leaves_the_env_without_a_row():
    db, conn = _db(serving=("b1", D1), history=[(1, "b1", D1)])

    done = promoter.rollback(db, "prod")

    assert done == promoter.Rollback(promoter.Serving("prod", "b1", D1), None)
    assert _writes(conn)[-1] == 'DELETE FROM "rag_meta"."serving" WHERE "env" = %s'
    assert done.to_json() == {"env": "prod", "serving": None,
                              "undone": {"build_id": "b1", "backend_image_digest": D1}}


@pytest.mark.parametrize("serving, history, match", [
    (None, [], "nothing serves"),
    (("b1", D1), [], "history"),
    (("b1", D1), [(3, "b2", D2), (2, "b1", D1)], "history"),
])
def test_rollback_refuses_when_serving_and_history_disagree(serving, history, match):
    db, conn = _db(serving=serving, history=history)

    with pytest.raises(promoter.PromoteError, match=match):
        promoter.rollback(db, "staging")
    assert _writes(conn) == [] and _kinds(conn)[-1] == "rollback"


def test_rollback_refuses_a_previous_build_that_was_unloaded():
    db, conn = _db(serving=("b1", D1), history=[(2, "b1", D1), (1, "b0", D0)], builds=("b1",))

    with pytest.raises(promoter.PromoteError, match="b0 is not in rag_meta.builds"):
        promoter.rollback(db, "staging")
    assert _kinds(conn)[-1] == "rollback"


def test_rollback_rejects_an_unknown_env():
    db, conn = _db()

    with pytest.raises(promoter.PromoteError, match="env"):
        promoter.rollback(db, "dev")
    assert conn.log == []
