"""Point ``rag_meta.serving`` at a loaded build and its backend image (design §7.6).

One transaction: the build must be registered in ``rag_meta.builds``, the image
digest must be ``sha256:`` plus 64 hex digits, and the env's row is replaced
(``activated_at`` = the database's now()). Returns what the env served before,
so a rollback is ``promote`` with that pair. Run only by an operator: the loader
and ``ragdata load`` never call it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragdata.loader.sql import META

ENVS = ("prod", "staging")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


class PromoteError(ValueError):
    """The pair cannot be served."""


@dataclass(frozen=True)
class Serving:
    env: str
    build_id: str
    backend_image_digest: str


def promote(db: Any, env: str, build_id: str, image_digest: str) -> Serving | None:
    if env not in ENVS:
        raise PromoteError(f"env must be one of {ENVS}, got {env!r}")
    if not isinstance(image_digest, str) or not DIGEST_RE.fullmatch(image_digest):
        raise PromoteError(f"image digest must be sha256:<64 hex>, got {image_digest!r}")
    with db.transaction() as cur:
        cur.execute(f'SELECT 1 FROM "{META}"."builds" WHERE "build_id" = %s', (build_id,))
        if cur.fetchone() is None:
            raise PromoteError(f"{build_id} is not in {META}.builds")
        cur.execute(f'SELECT "build_id", "backend_image_digest" FROM "{META}"."serving" '
                    'WHERE "env" = %s FOR UPDATE', (env,))
        before = cur.fetchone()
        cur.execute(f'INSERT INTO "{META}"."serving" ("env", "build_id", "backend_image_digest", '
                    '"activated_at") VALUES (%s, %s, %s, now()) ON CONFLICT ("env") DO UPDATE '
                    'SET "build_id" = EXCLUDED."build_id", "backend_image_digest" = '
                    'EXCLUDED."backend_image_digest", "activated_at" = EXCLUDED."activated_at"',
                    (env, build_id, image_digest))
    return Serving(env, *before) if before else None
