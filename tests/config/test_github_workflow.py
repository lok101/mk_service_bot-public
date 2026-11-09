from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = Path(".github/workflows/check.yml")
_JOB_RE = re.compile(
    r"(?ms)^  (?P<id>[A-Za-z0-9_-]+):.*?(?=^  [A-Za-z0-9_-]+:|\Z)",
)


def _workflow_text() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def _job_block(workflow: str, job_id: str) -> str:
    for match in _JOB_RE.finditer(workflow):
        if match.group("id") == job_id:
            return match.group(0)
    raise AssertionError(f"missing workflow job {job_id}")


def test_check_workflow_does_not_checkout_moysklad_api() -> None:
    text = Path(".github/workflows/check.yml").read_text(encoding="utf-8")
    assert "moysklad-api" not in text


def test_check_workflow_runs_integration_tests_in_separate_job() -> None:
    workflow = Path(".github/workflows/check.yml").read_text(encoding="utf-8")
    script = Path("scripts/integration-check.sh").read_text(encoding="utf-8")

    assert Path("scripts/integration-check.sh").is_file()
    assert "integration-check.sh" in workflow
    assert "pytest -o addopts= --import-mode=importlib -m integration" in script

    check_block, _, integration_block = workflow.partition("  integration:")
    assert check_block  # job integration присутствует
    assert "integration-check.sh" not in check_block
    assert "integration-check.sh" in integration_block


def test_check_workflow_runs_dependency_audit_in_separate_job() -> None:
    workflow = Path(".github/workflows/check.yml").read_text(encoding="utf-8")
    script = Path("scripts/dependency-audit.sh").read_text(encoding="utf-8")

    assert Path("scripts/dependency-audit.sh").is_file()
    assert "dependency-audit.sh" in workflow
    assert "pip-audit" in script

    check_block, _, dependency_block = workflow.partition("  dependency-audit:")
    assert check_block
    assert "dependency-audit.sh" not in check_block
    assert "dependency-audit.sh" in dependency_block


def test_check_workflow_runs_e2e_boot_in_separate_job() -> None:
    workflow = Path(".github/workflows/check.yml").read_text(encoding="utf-8")
    script = Path("scripts/e2e-boot-check.sh").read_text(encoding="utf-8")
    assert "e2e-boot-check.sh" in workflow
    check_block, _, e2e_block = workflow.partition("  e2e-boot:")
    assert check_block
    assert "e2e-boot-check.sh" not in check_block
    assert "e2e-boot-check.sh" in e2e_block
    assert "180" in script


def test_check_workflow_has_stable_formal_models_job() -> None:
    workflow = _workflow_text()
    block = _job_block(workflow, "formal-models")
    assert block.lstrip().startswith("formal-models:")
    assert "runs-on: ubuntu-latest" in block


def test_formal_models_job_installs_java_and_runs_pinned_wrapper() -> None:
    workflow = _workflow_text()
    formal_block = _job_block(workflow, "formal-models")
    check_block = _job_block(workflow, "check")

    assert "actions/setup-java@v4" in formal_block
    assert "distribution: temurin" in formal_block
    assert 'java-version: "17"' in formal_block
    assert "astral-sh/setup-uv@v5" in formal_block
    assert "uv sync" in formal_block
    assert "sh scripts/formal-check.sh" in formal_block
    assert "scripts/formal-check.sh" not in check_block
    assert "actions/setup-java" not in check_block


def test_formal_models_job_uploads_trace_artifact_on_failure() -> None:
    formal_block = _job_block(_workflow_text(), "formal-models")
    assert "if: failure()" in formal_block
    assert "actions/upload-artifact@v4" in formal_block
    assert "name: tlc-counterexample-traces" in formal_block
    assert "path: .cache/verification/traces/" in formal_block
    assert "if-no-files-found: ignore" in formal_block


def test_normal_check_job_does_not_install_java() -> None:
    check_block = _job_block(_workflow_text(), "check")
    assert "setup-java" not in check_block
    assert "java-version" not in check_block
