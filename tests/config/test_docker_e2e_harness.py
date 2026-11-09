from __future__ import annotations

import json
import tomllib
from pathlib import Path


def test_pytest_addopts_excludes_docker_e2e() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    assert any(str(m).startswith("docker_e2e:") for m in markers)
    joined = " ".join(addopts) if isinstance(addopts, list) else str(addopts)
    assert "docker_e2e" in joined
    assert "not docker_e2e" in joined or "and not docker_e2e" in joined


def test_e2e_dummy_credentials_json_exists() -> None:
    path = Path("docker/e2e/credentials.json")
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("type") == "service_account"
    assert "private_key" in data


def test_e2e_compose_publishes_api_and_mongo_ports() -> None:
    text = Path("docker-compose.e2e.yml").read_text(encoding="utf-8")
    assert "18000:8000" in text
    assert "27019:27017" in text


def test_e2e_boot_check_script_contract() -> None:
    sh = Path("scripts/e2e-boot-check.sh").read_text(encoding="utf-8")
    assert "Docker required" in sh or "docker required" in sh.lower()
    assert "180" in sh
    assert "docker-compose.e2e.yml" in sh or "compose.e2e.yml" in sh
    assert "/health/ready" in sh
    assert Path("scripts/e2e-boot-check.ps1").is_file()


def test_e2e_flows_workflow_exists() -> None:
    path = Path(".github/workflows/e2e-flows.yml")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "schedule:" in text
    assert "e2e-flow-check.sh" in text
    on_block = text.split("on:", 1)[1].split("jobs:", 1)[0]
    assert "push:" not in on_block
    assert "pull_request:" not in on_block
    assert Path("scripts/e2e-flow-check.sh").is_file()


def test_e2e_conftest_fails_hard_on_compose_up_error() -> None:
    text = Path("tests/e2e/conftest.py").read_text(encoding="utf-8")
    assert 'pytest.skip("Docker required")' in text
    assert 'pytest.skip(f"Docker compose up failed' not in text
    assert "compose up failed" in text
    assert "pytest.fail" in text
    fail_idx = text.find('pytest.fail(f"Docker compose up failed')
    assert fail_idx != -1
    down_before_fail = text.rfind("_compose_down()", 0, fail_idx)
    assert down_before_fail != -1


def test_e2e_conftest_logs_app_on_session_failure_path() -> None:
    text = Path("tests/e2e/conftest.py").read_text(encoding="utf-8")
    assert "pytest_sessionfinish" in text
    assert '["logs", "app"]' in text or '"logs", "app"' in text
    assert "testsfailed" in text
