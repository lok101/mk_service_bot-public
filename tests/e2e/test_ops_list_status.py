from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker_e2e

_ROOT = Path(__file__).resolve().parents[2]


def test_settlement_admin_list_status_docker_e2e(e2e_stack: dict[str, str]) -> None:
    project = os.environ.get("E2E_COMPOSE_PROJECT", "mk_e2e")
    env_file = _ROOT / ".env.e2e"
    cmd = [
        "docker",
        "compose",
        "-p",
        project,
        "--env-file",
        str(env_file),
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.e2e.yml",
        "exec",
        "-T",
        "app",
        "python",
        "scripts/settlement_admin.py",
        "list-status",
    ]
    completed = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[settlement_status]" in completed.stdout
    assert "[open_warehouses]" not in completed.stdout
