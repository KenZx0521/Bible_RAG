"""``python -m ragdata load|verify|kg-project`` (S13, S14 and the graph's projection).

    load RELEASE_JSON --slot inactive [--store DIR] [--contracts DIR] [--env-file F]
                      [--tokenizer F]
    verify RELEASE_JSON [--store DIR] [--contracts DIR] [--env-file F] [--tokenizer F]
                        [--gt F] [--freeze F] [--device DEV] [--sample N] [--report F]
    kg-project --build BUILD_ID [--store DIR] [--releases DIR] [--env-file F]
    unload BUILD_ID [--contracts DIR] [--env-file F]
    promote --env staging|prod --build BUILD_ID --image IMAGE_REF [--yes-prod] [--env-file F]
    promote --env staging|prod --rollback [--yes-prod] [--env-file F]

Both read the release through the store (``read_release``: every layer verified and
gated again, the file assembled again byte for byte; ``--tokenizer`` is BGE-M3's
tokenizer.json, default the HF cache). Connections come from POSTGRES_*, QDRANT_* and
NEO4J_* in the environment, or else from ``--env-file`` (the repository's
``.env``). ``load`` writes only a new schema, ``rag_meta.builds``, a new collection
and a new contract directory; ``--slot inactive`` is the only slot it accepts.
``kg-project`` projects a loaded build's graph layer into Neo4j (``ragdata.loader.graph_load``);
``verify`` compares it (G-PROJ.C8) when the build has one.
``unload`` deletes one build's schema, builds row, collection, contract directory and graph nodes
(``ragdata.loader.unload``); it refuses a serving build. ``promote`` writes
``rag_meta.serving`` (``ragdata.loader.promote``): IMAGE_REF is the backend image's
digest (``docker image inspect --format '{{.Id}}' IMAGE``), ``--rollback`` steps the env
back one promote, and prod is refused without ``--yes-prod``. It connects to PG only.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping

from ragdata import paths
from ragdata.loader import config, graph_load
from ragdata.loader import promote as promoter
from ragdata.loader.load import load
from ragdata.loader.unload import unload
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
    project = sub.add_parser("kg-project", help="project a build's graph layer into Neo4j")
    project.add_argument("--build", metavar="BUILD_ID", required=True)
    project.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    project.add_argument("--releases", type=Path, default=paths.RELEASES)
    project.add_argument("--env-file", type=Path, default=paths.REPO / ".env")
    drop = sub.add_parser("unload", help="delete a loaded build that nothing serves")
    drop.add_argument("build_id")
    drop.add_argument("--contracts", type=Path, default=paths.CONTRACTS)
    drop.add_argument("--env-file", type=Path, default=paths.REPO / ".env")
    serve = sub.add_parser("promote", help="point rag_meta.serving at a build and image, "
                                           "or roll the env back one promote")
    serve.add_argument("--env", choices=promoter.ENVS, required=True)
    serve.add_argument("--build", metavar="BUILD_ID")
    serve.add_argument("--image", metavar="IMAGE_REF",
                       help="the backend image digest, sha256:<64 hex>")
    serve.add_argument("--rollback", action="store_true",
                       help="go back to the pair before the newest promote")
    serve.add_argument("--yes-prod", action="store_true", help="required for --env prod")
    serve.add_argument("--env-file", type=Path, default=paths.REPO / ".env")


def environment(env_file: Path) -> dict[str, str]:
    """POSTGRES_*/QDRANT_*/NEO4J_* settings: the process environment over the env file."""
    found = config.read_env_file(env_file) if env_file.is_file() else {}
    keys = (*config.PG_KEYS, *config.QDRANT_KEYS, *config.NEO4J_KEYS)
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


def connect_pg(env: Mapping[str, str]) -> Any:
    """The PG adapter alone (promote never touches Qdrant)."""
    from ragdata.loader.pg import PgDb
    return PgDb.connect(config.pg_settings(env))


def connect_neo4j(env: Mapping[str, str]) -> Any:
    """The Neo4j adapter (its driver loads only here)."""
    from ragdata.loader.neo4j_db import Neo4jDb
    return Neo4jDb.connect(config.neo4j_settings(env))


def neo4j_if_configured(env: Mapping[str, str]) -> Any | None:
    """The Neo4j adapter when NEO4J_* are all set; what needs it fails closed on None."""
    return connect_neo4j(env) if all(env.get(k) for k in config.NEO4J_KEYS) else None


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


def project_source(source: graph_load.GraphSource, env: Mapping[str, str]) -> dict[str, Any]:
    neo4j = connect_neo4j(env)
    try:
        return graph_load.project(source, neo4j)
    finally:
        neo4j.close()


def run_project(args: argparse.Namespace) -> dict[str, Any]:
    source = graph_load.source_of_build(args.build, args.releases, args.store)
    return project_source(source, environment(args.env_file))


def verify_release(release: Release, pg: Any, qdrant: Any, contracts: Path, inputs: VerifyInputs,
                   env: Mapping[str, str]) -> ProjectionReport:
    """G-PROJ; Neo4j is reached only for a build with a graph."""
    neo4j = neo4j_if_configured(env) if release.doc["kg_enabled"] else None
    try:
        return verify(release, pg, qdrant, contracts, inputs, neo4j)
    finally:
        if neo4j is not None:
            neo4j.close()


def run_verify(args: argparse.Namespace) -> ProjectionReport:
    release = release_of(args)
    inputs = VerifyInputs(gt=args.gt, freeze=args.freeze, sample=args.sample,
                          device=args.device, tokenizer=args.tokenizer)
    env = environment(args.env_file)
    pg, qdrant = connect(env)
    try:
        return verify_release(release, pg, qdrant, args.contracts, inputs, env)
    finally:
        pg.close()
        qdrant.close()


def run_unload(args: argparse.Namespace) -> dict[str, Any]:
    env = environment(args.env_file)
    pg, qdrant = connect(env)
    neo4j = neo4j_if_configured(env)
    try:
        return unload(args.build_id, pg, qdrant, args.contracts, neo4j)
    finally:
        pg.close()
        qdrant.close()
        if neo4j is not None:
            neo4j.close()


def _check_promote(args: argparse.Namespace) -> None:
    if args.env == "prod" and not args.yes_prod:
        raise promoter.PromoteError("--env prod changes what production serves: add --yes-prod")
    if args.rollback and (args.build or args.image):
        raise promoter.PromoteError("--rollback takes neither --build nor --image")
    missing = [flag for flag, value in (("--build", args.build), ("--image", args.image))
               if not args.rollback and not value]
    if missing:
        raise promoter.PromoteError(f"promote needs {' and '.join(missing)}")


def run_promote(args: argparse.Namespace) -> dict[str, Any]:
    """Promote or roll back; every argument is checked before connecting."""
    _check_promote(args)
    pg = connect_pg(environment(args.env_file))
    try:
        if args.rollback:
            return promoter.rollback(pg, args.env).to_json()
        before = promoter.promote(pg, args.env, args.build, args.image)
    finally:
        pg.close()
    serving = promoter.Serving(args.env, args.build, args.image)
    return {"env": args.env, "serving": serving.pair(),
            "before": before.pair() if before else None}
