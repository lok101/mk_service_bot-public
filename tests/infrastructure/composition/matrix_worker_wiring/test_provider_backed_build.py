from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.base_margin_store_memory import InMemoryMatrixBaseMarginStore
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixParseState,
)
from src.application.matrix_automation.run_matrix_deploy_build import PurchaseFetchGlobalAbort
from src.infrastructure.composition.wiring.provider_backed_run_build import (
    ProviderBackedRunMatrixDeployBuild,
)

from .fakes import (
    _enabled_settings,
    _FakeBuild,
    _FakePurchaseReader,
    _FakeReferenceProvider,
    _FakeSnapshotStore,
    _mongo_persistence,
    _StockProvider,
    _stub_enabled_worker_dependencies,
)


def _empty_state() -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=(),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )


def _adapter(store: InMemoryMatrixBaseMarginStore) -> ProviderBackedRunMatrixDeployBuild:
    return ProviderBackedRunMatrixDeployBuild(
        snapshot_store=_FakeSnapshotStore(),
        purchase_reader=_FakePurchaseReader(),
        provider=_FakeReferenceProvider(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        substitution_guard_enabled=False,
        stock_provider=None,
        base_margin_store=store,
    )


def test_provider_backed_build_aborts_without_base_margin_store() -> None:
    result = _adapter(InMemoryMatrixBaseMarginStore())(_empty_state())
    assert isinstance(result, PurchaseFetchGlobalAbort)
    assert result.reason == "base_margin_not_loaded"


def test_provider_backed_build_uses_store_base_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _TrackingRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __call__(self, state: object, **kwargs: object) -> BuildMatrixDeployResult:
            del state, kwargs
            return BuildMatrixDeployResult(payloads=(), skipped_units=())

    monkeypatch.setattr(
        "src.infrastructure.composition.wiring.provider_backed_run_build.RunMatrixDeployBuild",
        _TrackingRunner,
    )
    store = InMemoryMatrixBaseMarginStore()
    params = curved_margin_params()
    store.save(params)
    result = _adapter(store)(_empty_state())
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert captured["base_margin"] == params


def test_provider_backed_build_forwards_guard_settings_and_provider(tmp_path: Path) -> None:
    from src.infrastructure.composition.wiring.wire_matrix_worker import (
        build_provider_backed_run_build,
    )

    provider = _StockProvider()
    settings = _enabled_settings(tmp_path)
    settings.matrix_automation.substitution_guard_enabled = True
    adapter = build_provider_backed_run_build(
        settings,
        snapshot_store=_FakeSnapshotStore(),
        purchase_reader=_FakePurchaseReader(),
        provider=_FakeReferenceProvider(),
        stock_provider=provider,
    )
    assert adapter.substitution_guard_enabled is True
    assert adapter.stock_provider is provider


def test_wire_matrix_worker_forwards_stock_provider_to_run_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    provider = _StockProvider()
    captured: dict[str, object] = {}

    def fake_build(settings: object, **kwargs: object) -> _FakeBuild:
        captured["stock_provider"] = kwargs.get("stock_provider")
        return _FakeBuild()

    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    settings.matrix_automation.substitution_guard_enabled = True
    _stub_enabled_worker_dependencies(monkeypatch)
    monkeypatch.setattr(wire_mod, "build_provider_backed_run_build", fake_build)

    wire_mod.wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
        stock_provider=provider,
    )
    assert captured["stock_provider"] is provider


def test_provider_backed_build_forwards_job_id_to_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.composition.wiring import provider_backed_run_build as build_mod
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    captured: dict[str, str] = {}

    class _TrackingRunner:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def __call__(
            self,
            state: object,
            *,
            job_id: str = "test",
        ) -> PurchaseFetchGlobalAbort:
            captured["job_id"] = job_id
            return PurchaseFetchGlobalAbort(reason="probe")

    monkeypatch.setattr(build_mod, "RunMatrixDeployBuild", _TrackingRunner)

    store = InMemoryMatrixBaseMarginStore()
    store.save(curved_margin_params())
    settings = _enabled_settings(tmp_path)
    settings.matrix_automation.substitution_guard_enabled = True
    adapter = wire_mod.ProviderBackedRunMatrixDeployBuild(
        snapshot_store=_FakeSnapshotStore(),
        purchase_reader=_FakePurchaseReader(),
        provider=_FakeReferenceProvider(),
        blocking_cell_price=settings.matrix_automation.blocking_cell_price,
        max_price_delta_pct=settings.matrix_automation.max_price_delta_pct,
        substitution_guard_enabled=True,
        stock_provider=_StockProvider(),
        base_margin_store=store,
    )
    adapter(_empty_state(), job_id="job-42")
    assert captured["job_id"] == "job-42"


def test_provider_backed_run_build_honors_adapter_seed_only_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """edge: ProviderBacked.seed_only=True → effective seed path без kwarg."""
    from src.infrastructure.composition.wiring import provider_backed_run_build as build_mod
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    captured: dict[str, bool] = {}

    class _TrackingRunner:
        def __init__(self, *, seed_only: bool = False, **_kwargs: object) -> None:
            captured["seed_only"] = seed_only

        def __call__(
            self,
            state: object,
            *,
            job_id: str = "test",
        ) -> PurchaseFetchGlobalAbort:
            return PurchaseFetchGlobalAbort(reason="probe")

    monkeypatch.setattr(build_mod, "RunMatrixDeployBuild", _TrackingRunner)

    store = InMemoryMatrixBaseMarginStore()
    store.save(curved_margin_params())
    settings = _enabled_settings(tmp_path)
    matrix = settings.matrix_automation
    adapter = wire_mod.ProviderBackedRunMatrixDeployBuild(
        snapshot_store=_FakeSnapshotStore(),
        purchase_reader=_FakePurchaseReader(),
        provider=_FakeReferenceProvider(),
        blocking_cell_price=matrix.blocking_cell_price,
        max_price_delta_pct=matrix.max_price_delta_pct,
        substitution_guard_enabled=False,
        stock_provider=None,
        base_margin_store=store,
        seed_only=True,
    )
    adapter(_empty_state(), job_id="seed", seed_only=False)
    assert captured["seed_only"] is True
