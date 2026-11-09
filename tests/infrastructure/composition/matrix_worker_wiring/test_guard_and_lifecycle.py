from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)

from .fakes import (
    _enabled_settings,
    _FakeBuild,
    _FakeDeployer,
    _FakeJobRepository,
    _FakeSnapshotStore,
    _FakeStatusRepository,
    _FakeSync,
    _mongo_persistence,
    _stub_enabled_worker_dependencies,
    patch_company_store_for_matrix_worker,
)


def test_enabled_worker_without_mongo_raises(tmp_path: Path) -> None:
    from src.infrastructure.composition.wiring.wire_matrix_worker import wire_matrix_worker

    persistence = PersistenceBundle(mongo_client=None, redis_client=None)
    with pytest.raises(ValueError, match="MongoDB"):
        wire_matrix_worker(_enabled_settings(tmp_path), persistence=persistence)


def test_guard_enabled_without_stock_provider_fails_worker_wiring(tmp_path: Path) -> None:
    from src.infrastructure.composition.wiring.wire_matrix_worker import wire_matrix_worker

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    settings.matrix_automation.substitution_guard_enabled = True
    with pytest.raises(ValueError, match="MatrixStockProvider required"):
        wire_matrix_worker(
            settings,
            persistence=_mongo_persistence(),
            stock_provider=None,
        )


def test_guard_disabled_does_not_require_stock_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring.wire_matrix_worker import wire_matrix_worker

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    settings.matrix_automation.substitution_guard_enabled = False
    _stub_enabled_worker_dependencies(monkeypatch)
    container = wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
        stock_provider=None,
    )
    assert container.runtime.enabled is True


def test_wire_matrix_worker_accepts_optional_domain_stock_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.snack_loading import DomainMatrixStockProvider
    from src.infrastructure.composition.wiring.wire_matrix_worker import wire_matrix_worker
    from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    settings.matrix_automation.substitution_guard_enabled = False
    _stub_enabled_worker_dependencies(monkeypatch)
    provider = DomainMatrixStockProvider(InMemorySnackMachineStockStore())
    container = wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
        stock_provider=provider,
    )
    assert container.runtime.enabled is True


def test_enabled_worker_auto_builds_deploy_map_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.testing.snack_loading_fakes import InMemoryKitMatrixDeployMapStore

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    settings.matrix_automation.substitution_guard_enabled = False
    _stub_enabled_worker_dependencies(monkeypatch)
    calls: list[object] = []

    def _fake_from_settings(
        cls: object,
        settings: Settings,
        *,
        client: object = None,
    ) -> InMemoryKitMatrixDeployMapStore:
        calls.append(client)
        return InMemoryKitMatrixDeployMapStore()

    monkeypatch.setattr(
        wire_mod.MongoKitMatrixDeployMapStore,
        "from_settings",
        classmethod(_fake_from_settings),
    )
    container = wire_mod.wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
        stock_provider=None,
        deploy_map_store=None,
    )
    assert container.runtime.enabled is True
    assert len(calls) == 1


def test_wire_matrix_worker_passes_shared_request_id_store_to_deployer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    store = InMemoryKitVendingRequestIdStore()
    captured: dict[str, object] = {}
    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    _stub_enabled_worker_dependencies(monkeypatch)
    monkeypatch.setattr(
        wire_mod,
        "build_kitvending_request_id_store",
        lambda settings, **kwargs: store,
    )

    def fake_deployer(
        settings: Settings,
        *,
        request_id_store: object,
        **kwargs: object,
    ) -> _FakeDeployer:
        del settings, kwargs
        captured["request_id_store"] = request_id_store
        return _FakeDeployer()

    monkeypatch.setattr(wire_mod, "build_matrix_deployer", fake_deployer)

    container = wire_mod.wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
    )

    assert container.runtime.enabled is True
    assert captured["request_id_store"] is store


def test_matrix_worker_container_close_closes_purchase_http_client_via_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pymongo import MongoClient

    from src.infrastructure.composition.wiring import assemble_matrix_worker as assemble_mod
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.moysklad.purchase_prices.models import PurchaseAttributesBatchResult
    from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

    closed = {"purchase": False}

    class _TrackingPurchaseClient:
        def fetch_purchase_attributes(
            self,
            product_codes: frozenset[str],
        ) -> PurchaseAttributesBatchResult:
            return PurchaseAttributesBatchResult(attributes={}, cards_found=0)

        def close(self) -> None:
            closed["purchase"] = True

    mongo_client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )
    persistence = PersistenceBundle(mongo_client=mongo_client, redis_client=None)

    monkeypatch.setattr(assemble_mod, "wire_persistence", lambda settings: persistence)
    monkeypatch.setattr(
        assemble_mod,
        "build_snack_machine_stock_store",
        lambda settings, *, client=None: InMemorySnackMachineStockStore(),
    )
    monkeypatch.setattr(
        wire_mod.MoySkladPurchasePricesHttpClient,
        "from_settings",
        classmethod(lambda cls, settings, **kwargs: _TrackingPurchaseClient()),
    )
    monkeypatch.setattr(wire_mod, "build_matrix_catalog_reader", lambda settings: object())
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
    patch_company_store_for_matrix_worker(monkeypatch, wire_mod)

    container = assemble_mod.assemble_matrix_worker(
        _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1"),
    )
    container.close()
    assert closed["purchase"] is True
