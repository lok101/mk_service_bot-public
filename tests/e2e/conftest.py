from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker_e2e

_ROOT = Path(__file__).resolve().parents[2]
_API = os.environ.get("E2E_API_BASE_URL", "http://127.0.0.1:18000")
_MONGO = os.environ.get(
    "E2E_MONGODB_URI",
    "mongodb://mk_service_bot:e2e-mongo-password@127.0.0.1:27019/"
    "mk_service_bot_e2e?authSource=admin",
)
_PROJECT = os.environ.get("E2E_COMPOSE_PROJECT", "mk_e2e")
_ENV_FILE = _ROOT / ".env.e2e"
_e2e_compose_up = False


def _compose_cmd() -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        _PROJECT,
        "--env-file",
        str(_ENV_FILE),
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.e2e.yml",
    ]


def _compose_down() -> None:
    subprocess.run(
        [*_compose_cmd(), "down", "-v", "--remove-orphans"],
        cwd=_ROOT,
        check=False,
    )


def _dump_app_logs() -> None:
    completed = subprocess.run(
        [*_compose_cmd(), "logs", "app"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _ = exitstatus
    global _e2e_compose_up
    if not _e2e_compose_up:
        return
    if session.testsfailed:
        _dump_app_logs()
    _compose_down()
    _e2e_compose_up = False


@pytest.fixture(scope="session")
def e2e_stack() -> Iterator[dict[str, str]]:
    global _e2e_compose_up
    if shutil.which("docker") is None:
        pytest.skip("Docker required")
    if not _ENV_FILE.is_file():
        shutil.copy(_ROOT / ".env.e2e.example", _ENV_FILE)
    up = subprocess.run(
        [*_compose_cmd(), "up", "-d", "--build", "app", "mongo", "redis"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if up.returncode != 0:
        _compose_down()
        pytest.fail(f"Docker compose up failed: {up.stderr}")
    _e2e_compose_up = True
    deadline = time.time() + 180
    import urllib.request

    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{_API}/health/ready", timeout=2)
            break
        except Exception:
            time.sleep(2)
    else:
        logs = subprocess.run(
            [*_compose_cmd(), "logs", "app"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(f"ready timeout\n{logs.stdout}\n{logs.stderr}")
    yield {"api": _API, "mongo_uri": _MONGO}
