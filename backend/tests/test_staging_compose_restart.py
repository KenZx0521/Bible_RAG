"""The staging backends in docker-compose.staging.yml stay down once they refuse to start.

A strict build handshake that fails ends the process (exit 3). With any restart
policy other than "no", Docker restarts it after every back-off, and each
restart reloads BGE-M3 and the reranker on a host shared with evaluation runs.
YAML 1.1 reads an unquoted ``no`` as false, so the policy must be the string.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGING_COMPOSE = ROOT / "docker-compose.staging.yml"


def _backends() -> dict[str, dict]:
    services = yaml.safe_load(STAGING_COMPOSE.read_text(encoding="utf-8"))["services"]
    return {name: service for name, service in services.items() if name.startswith("backend")}


def test_no_staging_backend_restarts_after_a_refused_handshake():
    policies = {name: s.get("restart") for name, s in _backends().items()}

    assert "backend-r1" in policies
    assert policies == dict.fromkeys(policies, "no")
