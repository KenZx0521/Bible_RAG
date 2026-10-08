"""``python -m ragdata load|verify`` (S13, S14).

    load RELEASE_JSON --slot inactive [--store DIR] [--contracts DIR] [--env-file F]
                      [--tokenizer F]
    verify RELEASE_JSON [--store DIR] [--contracts DIR] [--env-file F] [--tokenizer F]
                        [--gt F] [--freeze F] [--device DEV] [--sample N] [--report F]

Both read the release through the store (``read_release``: every layer verified and
gated again, the file assembled again byte for byte; ``--tokenizer`` is BGE-M3's
tokenizer.json, default the HF cache). Connections come from POSTGRES_* and
QDRANT_* in the environment, or else from ``--env-file`` (the repository's
``.env``). ``load`` writes only a new schema, ``rag_meta.builds``, a new collection
and a new contract directory; ``--slot inactive`` is the only slot it accepts.
``promote`` is a function (``ragdata.loader.promote``), not a command here.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping

from ragdata import paths
from ragdata.loader import config
from ragdata.loader.load import load
from ragdata.loader.verify import ProjectionReport, VerifyInputs, verify
from ragdata.release import gating
from ragdata.release.assemble import Release, read_release
from ragdata.store import DEFAULT_ROOT


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("release", type=Path, help="releases/{build_id}.json")
    parser.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--contracts", type=Path, default=paths.CONTRACTS)
    parser.add_argument("--env-file", type=Path, default=paths.REPO / ".env")
    parser.add_argument("--tokenizer", type=Path, help="BGE-M3 tokenizer.json (default HF cache)")


def add_parsers(sub: argparse._SubParsersAction) -> None:
    loader = sub.add_parser("load", help="S13: load a release into a slot nothing serves")
    _common(loader)
    loader.add_argument("--slot", choices=("inactive",), required=True)
    check = sub.add_parser("verify", help="S14: G-PROJ over a loaded build")
    _common(check)
    check.add_argument("--gt", type=Path, default=paths.GT_V2)
    check.add_argument("--freeze", type=Path, default=paths.GT_V2_FREEZE)
    check.add_argument("--device", help="where BGE-M3 re-encodes (default cuda if available)")
    check.add_argument("--sample", type=int, default=200)
    check.add_argument("--report", type=Path)


def environment(env_file: Path) -> dict[str, str]:
    """POSTGRES_*/QDRANT_* settings: the process environment over the env file."""
    found = config.read_env_file(env_file) if env_file.is_file() else {}
    keys = (*config.PG_KEYS, *config.QDRANT_KEYS)
    return {**found, **{k: os.environ[k] for k in keys if os.environ.get(k)}}


def connect(env: Mapping[str, str]) -> tuple[Any, Any]:
    """The PG and Qdrant adapters (their drivers load only here)."""
    from ragdata.loader.pg import PgDb
    from ragdata.loader.qdrant import QdrantDb
    pg = PgDb.connect(config.pg_settings(env))
    try:
        return pg, QdrantDb.connect(config.qdrant_settings(env))
    except BaseException:
        pg.close()
        raise


def release_of(args: argparse.Namespace) -> Release:
    """The release file, verified against the store and its layers gated again."""
    return read_release(args.release, args.store, gating.default_checks(args.tokenizer))


def run_load(args: argparse.Namespace) -> dict[str, Any]:
    release = release_of(args)
    pg, qdrant = connect(environment(args.env_file))
    try:
        return load(release, pg, qdrant, args.contracts)
    finally:
        pg.close()
        qdrant.close()


def run_verify(args: argparse.Namespace) -> ProjectionReport:
    release = release_of(args)
    inputs = VerifyInputs(gt=args.gt, freeze=args.freeze, sample=args.sample,
                          device=args.device, tokenizer=args.tokenizer)
    pg, qdrant = connect(environment(args.env_file))
    try:
        return verify(release, pg, qdrant, args.contracts, inputs)
    finally:
        pg.close()
        qdrant.close()
