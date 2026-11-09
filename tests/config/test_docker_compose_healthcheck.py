from __future__ import annotations

from pathlib import Path


def test_app_healthcheck_uses_readiness_endpoint() -> None:
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "/health/ready" in compose_text
    assert "urllib.request.urlopen('http://127.0.0.1:8000/health/ready')" in compose_text
