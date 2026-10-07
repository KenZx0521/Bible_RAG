"""``python -m ragdata release VERSION... [--store DIR] [--releases DIR] [--date YYYYMMDD]``.

Assembles the release of the named layer versions (their dependencies follow from
``depends_on``), writes ``releases/{build_id}.json`` once and reports the build id.
Without ``--date`` the build date is the commit date of the repository's HEAD.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ragdata import paths
from ragdata.release import assemble as rel
from ragdata.store import DEFAULT_ROOT


def add_parser(sub: argparse._SubParsersAction) -> None:
    release = sub.add_parser("release", help="S12: assemble a release of layer versions")
    release.add_argument("versions", nargs="+", help="layer versions, e.g. emb@846de4f285eb")
    release.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    release.add_argument("--releases", type=Path, default=paths.RELEASES)
    release.add_argument("--date", help="YYYYMMDD (default: the commit date of HEAD)")


def run(args: argparse.Namespace) -> dict[str, Any]:
    date = args.date or rel.git_date(paths.REPO)
    release = rel.assemble(args.store, args.versions, date)
    existed = (args.releases / f"{release.build_id}.json").exists()
    path = rel.write_release(release, args.releases)
    return {"build_id": release.build_id, "release_sha": release.release_sha,
            "path": str(path), "existed": existed,
            "layers": {k: v for k, v in release.doc["layers"].items() if v}}
