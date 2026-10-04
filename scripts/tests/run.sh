#!/usr/bin/env bash
# Run the scripts/ test suite with the scripts venv.
#
# The scripts venv has no pytest, and adding it would mean re-locking
# scripts/uv.lock (torch/ckip resolution) over a ~50 KB/s link. Instead this
# borrows pytest from the evaluation venv through a throwaway shim directory
# that holds only pytest's own packages.
#
#   scripts/tests/run.sh [pytest args]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SITE="$ROOT/evaluation/.venv/lib/python3.12/site-packages"
SHIM="$(mktemp -d)"
trap 'rm -rf "$SHIM"' EXIT
for pkg in pytest _pytest pluggy iniconfig pygments py.py; do
    [ -e "$SITE/$pkg" ] && ln -s "$SITE/$pkg" "$SHIM/$pkg"
done
cd "$ROOT"
PYTHONPATH="$SHIM" exec scripts/.venv/bin/python -m pytest scripts/tests "$@"
