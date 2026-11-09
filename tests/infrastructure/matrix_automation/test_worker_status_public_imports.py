from __future__ import annotations

from src.application.matrix_automation import MatrixDeployJob


def test_matrix_deploy_job_importable_from_matrix_automation_barrel() -> None:
    assert MatrixDeployJob.__name__ == "MatrixDeployJob"
