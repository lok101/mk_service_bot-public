from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle

from .fakes import (
    _enabled_settings,
    _FakeBuild,
    _FakeDeployer,
    _FakeJobRepository,
    _FakePurchaseReader,
    _FakeSnapshotStore,
    _FakeStatusRepository,
    _FakeSync,
)


def test_worker_wiring_reuses_persistence_and_assembles_job_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring import assemble_matrix_worker as assemble_mod
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    calls: dict[str, Any] = {"persistence": 0, "wire": 0}

    def fake_wire_persistence(settings: Settings) -> PersistenceBundle:
        calls["persistence"] += 1
        return persistence

    def fake_wire(
        settings: Settings,
        *,
        persistence: PersistenceBundle,
        stock_provider: Any = None,
        deploy_map_store: Any = None,
    ) -> Any:
        del stock_provider, deploy_map_store
        calls["wire"] += 1
        assert persistence.mongo_client is None
        from src.application.matrix_automation import MatrixDeployJob
        from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer
        from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime

        class _Status:
            def record_heartbeat(self, *, at: str, enabled: bool) -> None:
                return None

            def record_terminal_job(self, job: MatrixDeployJob) -> None:
                return None

        class _Scheduler:
            def start(self) -> None:
                return None

            def stop(self) -> None:
                return None

        class _Clock:
            def now_utc_iso(self) -> str:
                return "2026-07-13T00:00:00Z"

        runtime = MatrixWorkerRuntime(
            enabled=True,
            status_repository=_Status(),
            scheduler=_Scheduler(),
            clock=_Clock(),
        )
        return MatrixWorkerContainer(runtime=runtime, persistence=persistence)

    monkeypatch.setattr(assemble_mod, "wire_persistence", fake_wire_persistence)
    monkeypatch.setattr(assemble_mod, "wire_matrix_worker", fake_wire)
    monkeypatch.setattr(wire_mod, "wire_matrix_worker", fake_wire)

    container = assemble_mod.assemble_matrix_worker(_enabled_settings(tmp_path))
    assert calls["persistence"] == 1
    assert calls["wire"] == 1
    assert container.persistence is persistence
    assert container.runtime.enabled is True


def test_worker_wiring_does_not_call_app_reference_data_or_outbox_factories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pymongo import MongoClient

    from src.infrastructure.composition.wiring import assemble_matrix_worker as assemble_mod
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("app factory must not be called")

    mongo_client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )
    persistence = PersistenceBundle(mongo_client=mongo_client, redis_client=None)

    def fake_wire_persistence(settings: Settings) -> PersistenceBundle:
        return persistence

    monkeypatch.setattr(assemble_mod, "wire_persistence", fake_wire_persistence)
    monkeypatch.setattr(
        assemble_mod,
        "build_snack_machine_stock_store",
        lambda settings, *, client=None: InMemorySnackMachineStockStore(),
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.build_outbox_store",
        boom,
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.build_reference_data_worker",
        boom,
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.wiring.assemble.assemble_app_container",
        boom,
    )

    # Keep enabled path from hitting Google Sheets / Kit / Mongo live I/O.
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_catalog_reader",
        lambda settings: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_reference_sync",
        lambda settings, **kwargs: _FakeSync(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_deployer",
        lambda settings, **kwargs: _FakeDeployer(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_purchase_attributes_reader",
        lambda settings: (_FakePurchaseReader(), lambda: None),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_provider_backed_run_build",
        lambda settings, **kwargs: _FakeBuild(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_reference_data_snapshot_store",
        lambda settings, **kwargs: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_snapshot_store",
        lambda settings, **kwargs: _FakeSnapshotStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_reference_data_provider",
        lambda matrix: object(),
    )
    monkeypatch.setattr(
        wire_mod.MongoMatrixDeployJobRepository,
        "from_settings",
        classmethod(lambda cls, settings, *, client=None: _FakeJobRepository()),
    )
    monkeypatch.setattr(
        wire_mod.MongoMatrixWorkerStatusRepository,
        "from_settings",
        classmethod(lambda cls, settings, *, client=None: _FakeStatusRepository()),
    )
    from .fakes import patch_company_store_for_matrix_worker

    patch_company_store_for_matrix_worker(monkeypatch, wire_mod)

    container = assemble_mod.assemble_matrix_worker(
        _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1"),
    )
    assert container.runtime.enabled is True
    assert not hasattr(container, "outbox")
    assert not hasattr(container, "reference_data")
