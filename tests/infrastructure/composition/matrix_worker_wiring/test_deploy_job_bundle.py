from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)

from .fakes import (
    _enabled_settings,
    _FakeStatusRepository,
    _persistence_with_mongo,
    _stub_enabled_worker_dependencies,
)


def test_build_matrix_catalog_reader_excludes_product_multipliers_sheet_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: product_multipliers GID в exclude catalog reader; stream GID нет."""
    from src.config.google_sheets import GoogleSheetsSettings
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.matrix_automation.sheets_reader import MatrixCatalogSheetsReader

    creds = tmp_path / "creds.json"
    creds.write_text("{}", encoding="utf-8")
    settings = _enabled_settings(tmp_path)
    settings.google_sheets = GoogleSheetsSettings.model_construct(
        credentials_file=str(creds),
    )

    captured: dict[str, set[int]] = {}

    class _CapturingReader(MatrixCatalogSheetsReader):
        def __init__(self, **kwargs: object) -> None:
            captured["exclude"] = kwargs["exclude_sheet_ids"]  # type: ignore[assignment]
            super().__init__(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(wire_mod, "MatrixCatalogSheetsReader", _CapturingReader)
    reader = wire_mod.build_matrix_catalog_reader(settings)
    assert captured["exclude"] == {3}
    assert reader._exclude_sheet_ids == {3}


def test_build_matrix_deploy_job_bundle_nightly_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: bundle(seed_only=False, trigger=cron) — RunDailyMatrixDeployJob defaults."""
    from src.infrastructure.composition.wiring.wire_matrix_worker import (
        build_matrix_deploy_job_bundle,
    )

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://localhost:27017")
    persistence = _persistence_with_mongo()
    status_repo = _FakeStatusRepository()
    _stub_enabled_worker_dependencies(monkeypatch)

    bundle = build_matrix_deploy_job_bundle(
        settings,
        persistence=persistence,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        stock_provider=None,
        seed_only=False,
        trigger="cron",
        status_repository=status_repo,
    )
    assert bundle.daily_job.seed_only is False
    assert bundle.daily_job.trigger == "cron"
    assert bundle.closers
    assert not hasattr(bundle.daily_job, "price_change_stream")


def test_build_matrix_deploy_job_bundle_seed_flags_and_noop_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """edge: seed_only=True, trigger=seed, status_repository no-op не пишет terminal."""
    from src.infrastructure.composition.wiring.wire_matrix_worker import (
        NoOpMatrixWorkerStatusRepository,
        build_matrix_deploy_job_bundle,
    )

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://localhost:27017")
    settings.matrix_automation.worker_enabled = False
    persistence = _persistence_with_mongo()
    noop = NoOpMatrixWorkerStatusRepository()
    _stub_enabled_worker_dependencies(monkeypatch)

    bundle = build_matrix_deploy_job_bundle(
        settings,
        persistence=persistence,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        stock_provider=None,
        seed_only=True,
        trigger="seed",
        status_repository=noop,
    )
    assert bundle.daily_job.seed_only is True
    assert bundle.daily_job.trigger == "seed"
    assert bundle.daily_job.status_repository is noop


def test_noop_matrix_worker_status_repository_does_not_record() -> None:
    """edge: record_heartbeat / record_terminal_job — no-op без side effects."""
    from src.application.matrix_automation.job_models import MatrixDeployJob
    from src.infrastructure.composition.wiring.wire_matrix_worker import (
        NoOpMatrixWorkerStatusRepository,
    )

    repo = NoOpMatrixWorkerStatusRepository()
    job = MatrixDeployJob.started(
        job_id="j1",
        started_at="2026-07-14T00:00:00Z",
        trigger="seed",
    )
    repo.record_heartbeat(at="2026-07-14T00:00:00Z", enabled=False)
    repo.record_terminal_job(job)
    assert not hasattr(repo, "heartbeats")
    assert not hasattr(repo, "terminal_jobs")
