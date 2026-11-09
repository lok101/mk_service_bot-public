from __future__ import annotations

import pytest

from .fakes import (
    _build,
    _CrashingSync,
    _matrix,
    _runner,
    _state,
)


def test_global_sync_abort_finalizes_failed_without_deploy_or_snapshots() -> None:
    from src.application.matrix_automation.sync import SyncGlobalAbort

    runner, jobs, snapshots, notifier, deployer, status = _runner(
        sync_result=SyncGlobalAbort(reason="sheets_unavailable"),
        build_result=_build(),
    )
    job = runner.run()
    assert job.status == "failed"
    assert job.finished_at == "2026-07-10T00:01:00+00:00"
    assert job.units == ()
    assert deployer.calls == []
    assert snapshots.documents == []
    assert jobs.finalized == [job]
    assert status.terminal_jobs == [job]
    assert notifier.jobs == [job]
    assert notifier.abort_reasons == ["sheets_unavailable"]


def test_purchase_batch_global_abort_finalizes_failed_without_deploy_or_snapshots() -> None:
    from src.application.matrix_automation.run_matrix_deploy_build import PurchaseFetchGlobalAbort

    runner, jobs, snapshots, notifier, deployer, status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=PurchaseFetchGlobalAbort(reason="moysklad_batch_empty_response"),
    )
    job = runner.run()
    assert job.status == "failed"
    assert job.finished_at is not None
    assert deployer.calls == []
    assert snapshots.documents == []
    assert jobs.finalized == [job]
    assert status.terminal_jobs == [job]
    assert notifier.abort_reasons == ["moysklad_batch_empty_response"]


def test_unhandled_crash_leaves_inserted_job_orphan_and_does_not_notify() -> None:
    runner, jobs, snapshots, notifier, deployer, status = _runner(
        matrix_sync=_CrashingSync(),
        build_result=_build(),
    )
    with pytest.raises(RuntimeError, match="boom after insert"):
        runner.run()
    assert len(jobs.inserted) == 1
    orphan = jobs.inserted[0]
    assert orphan.finished_at is None
    assert orphan.status is None
    assert jobs.finalized == []
    assert status.terminal_jobs == []
    assert notifier.jobs == []
    assert deployer.calls == []
    assert snapshots.documents == []
