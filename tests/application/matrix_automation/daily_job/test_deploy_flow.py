from __future__ import annotations

import pytest

from src.application.matrix_automation.models import MatrixDeployResult

from .fakes import (
    _build,
    _matrix,
    _payload,
    _RecordingBuild,
    _result,
    _runner,
    _state,
)


def test_job_deploys_payloads_and_finalizes_applied_units() -> None:
    runner, jobs, snapshots, notifier, _deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(_payload("Snacks", "512"),)),
        deploy_results=(_result("Snacks", "512", "applied", None),),
    )
    job = runner.run()
    assert [item.status for item in jobs.inserted] == [None]
    assert job.status == "completed"
    assert job.units[0].deploy_status == "applied"
    assert notifier.jobs == [job]
    assert snapshots.documents[0].machine_code == "512"


def test_deploy_result_key_mismatch_finalizes_failed_with_global_abort_notify() -> None:
    runner, jobs, snapshots, notifier, deployer, status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(_payload("Snacks", "512"),)),
        deploy_results=(_result("Other", "999", "applied", None),),
    )

    job = runner.run()

    assert job.status == "failed"
    assert job.finished_at == "2026-07-10T00:01:00+00:00"
    assert job.units == ()
    assert jobs.finalized == [job]
    assert status.terminal_jobs == [job]
    assert notifier.jobs == [job]
    assert notifier.abort_reasons == ["deploy_result_key_mismatch"]
    assert len(deployer.calls) == 1
    assert snapshots.documents == []


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((), "skipped"),
        ((_result("A", "1", "applied", None),), "completed"),
        (
            (
                _result("A", "1", "applied", None),
                _result("B", "2", "failed", "upload_failed"),
            ),
            "partial",
        ),
        ((_result("A", "1", "failed", "upload_failed"),), "failed"),
    ],
)
def test_terminal_status_uses_only_real_deploy_attempts(
    results: tuple[MatrixDeployResult, ...],
    expected: str,
) -> None:
    payloads = tuple(_payload(item.logical_matrix_name, item.machine_code) for item in results)
    runner, _jobs, _snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(),
        build_result=_build(payloads=payloads),
        deploy_results=results,
    )
    job = runner.run()
    assert job.status == expected


def test_daily_job_forwards_persisted_job_id_to_build() -> None:
    sync_state = _state(enabled_matrices=(_matrix("Snacks", "512"),))
    build = _RecordingBuild(_build(payloads=(_payload("Snacks", "512"),)))
    runner, _jobs, _snapshots, _notifier, _deployer, _status = _runner(
        sync_result=sync_state,
        run_build=build,
        deploy_results=(_result("Snacks", "512", "applied", None),),
        id_factory=lambda: "job-42",
    )
    runner.run()
    assert build.calls == [("job-42", sync_state, False)]
