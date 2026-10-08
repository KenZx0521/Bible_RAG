"""Point ``rag_meta.serving`` at a loaded build and its backend image, or step back (§7.6).

``promote``, in one transaction: the build must be registered in ``rag_meta.builds``,
the image digest must be ``sha256:`` plus 64 hex digits, the env's row is replaced
(``activated_at`` = the database's now()) and the pair is appended to
``rag_meta.serving_history`` (created here when missing; promote is its only writer).
Promoting the pair already served writes nothing. Returns what the env served before.

``rollback``, in one transaction: the env's newest history entry not yet rolled back
must be the pair serving holds; it is marked rolled back, and serving goes back to the
entry before it, or loses the env's row when there is none (undoing the first promote:
nothing serves the env). A second rollback steps back once more. Run only by an
operator: the loader and ``ragdata load`` never call either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragdata.loader.plan import LoaderError
from ragdata.loader.sql import META

ENVS = ("prod", "staging")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
SERVING = f'"{META}"."serving"'
HISTORY = f'"{META}"."serving_history"'
HISTORY_DDL = (f'CREATE TABLE IF NOT EXISTS {HISTORY} ("seq" bigserial PRIMARY KEY, '
               "\"env\" text NOT NULL CHECK (\"env\" IN ('prod', 'staging')), "
               '"build_id" text NOT NULL, "backend_image_digest" text NOT NULL, '
               '"activated_at" timestamptz NOT NULL, "rolled_back_at" timestamptz)')


class PromoteError(LoaderError):
    """The pair cannot be served, or there is nothing to roll back to."""


@dataclass(frozen=True)
class Serving:
    env: str
    build_id: str
    backend_image_digest: str

    def pair(self) -> dict[str, str]:
        return {"build_id": self.build_id, "backend_image_digest": self.backend_image_digest}


@dataclass(frozen=True)
class Rollback:
    undone: Serving
    restored: Serving | None

    def to_json(self) -> dict[str, Any]:
        return {"env": self.undone.env, "undone": self.undone.pair(),
                "serving": self.restored.pair() if self.restored else None}


def _check_env(env: str) -> None:
    if env not in ENVS:
        raise PromoteError(f"env must be one of {ENVS}, got {env!r}")


def _require_build(cur: Any, build_id: str) -> None:
    cur.execute(f'SELECT 1 FROM "{META}"."builds" WHERE "build_id" = %s', (build_id,))
    if cur.fetchone() is None:
        raise PromoteError(f"{build_id} is not in {META}.builds")


def _served(cur: Any, env: str) -> Serving | None:
    cur.execute(f'SELECT "build_id", "backend_image_digest" FROM {SERVING} '
                'WHERE "env" = %s FOR UPDATE', (env,))
    row = cur.fetchone()
    return Serving(env, *row) if row else None


def promote(db: Any, env: str, build_id: str, image_digest: str) -> Serving | None:
    _check_env(env)
    if not isinstance(image_digest, str) or not DIGEST_RE.fullmatch(image_digest):
        raise PromoteError(f"image digest must be sha256:<64 hex>, got {image_digest!r}")
    with db.transaction() as cur:
        cur.execute(HISTORY_DDL)
        _require_build(cur, build_id)
        before = _served(cur, env)
        if before == Serving(env, build_id, image_digest):
            return before
        cur.execute(f'INSERT INTO {SERVING} ("env", "build_id", "backend_image_digest", '
                    '"activated_at") VALUES (%s, %s, %s, now()) ON CONFLICT ("env") DO UPDATE '
                    'SET "build_id" = EXCLUDED."build_id", "backend_image_digest" = '
                    'EXCLUDED."backend_image_digest", "activated_at" = EXCLUDED."activated_at"',
                    (env, build_id, image_digest))
        cur.execute(f'INSERT INTO {HISTORY} ("env", "build_id", "backend_image_digest", '
                    '"activated_at") VALUES (%s, %s, %s, now())', (env, build_id, image_digest))
    return before


def _active_history(cur: Any, env: str) -> list[tuple[int, Serving]]:
    """The env's two newest entries not rolled back, newest first (rows locked)."""
    cur.execute(f'SELECT "seq", "build_id", "backend_image_digest" FROM {HISTORY} '
                'WHERE "env" = %s AND "rolled_back_at" IS NULL ORDER BY "seq" DESC LIMIT 2 '
                'FOR UPDATE', (env,))
    return [(seq, Serving(env, build, digest)) for seq, build, digest in cur.fetchall()]


def _restore(cur: Any, env: str, previous: Serving | None) -> None:
    if previous is None:
        cur.execute(f'DELETE FROM {SERVING} WHERE "env" = %s', (env,))
        return
    _require_build(cur, previous.build_id)
    cur.execute(f'UPDATE {SERVING} SET "build_id" = %s, "backend_image_digest" = %s, '
                '"activated_at" = now() WHERE "env" = %s',
                (previous.build_id, previous.backend_image_digest, env))


def rollback(db: Any, env: str) -> Rollback:
    _check_env(env)
    with db.transaction() as cur:
        cur.execute(HISTORY_DDL)
        current = _served(cur, env)
        if current is None:
            raise PromoteError(f"nothing serves {env}: there is no promote to roll back")
        entries = _active_history(cur, env)
        if not entries or entries[0][1] != current:
            raise PromoteError(f"{META}.serving_history does not end with what {env} serves "
                               f"({current.build_id}, {current.backend_image_digest}); "
                               "nothing was changed")
        cur.execute(f'UPDATE {HISTORY} SET "rolled_back_at" = now() WHERE "seq" = %s',
                    (entries[0][0],))
        previous = entries[1][1] if len(entries) > 1 else None
        _restore(cur, env, previous)
    return Rollback(current, previous)
