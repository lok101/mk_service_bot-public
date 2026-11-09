from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

import pytest

from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync_product_catalog_ms import SyncProductCatalogFromMs
from src.config.product_catalog_ms import ProductCatalogMsSettings
from src.infrastructure.composition.factories.reference_data import (
    build_product_catalog_ms_worker,
)
from src.infrastructure.reference_data.coffee_recipe_drink_source import (
    CoffeeRecipeProductCatalogDrinkSource,
)
from src.infrastructure.reference_data.memory_store import (
    InMemoryReferenceDataSnapshotStore,
)
from src.infrastructure.reference_data.product_catalog_ms_worker import (
    ProductCatalogMsSyncWorker,
)
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository


def _drink_source() -> CoffeeRecipeProductCatalogDrinkSource:
    from tests.application.product_identity.fakes import FakeDomainProductStore

    return CoffeeRecipeProductCatalogDrinkSource(
        InMemoryCoffeeRecipeRepository(),
        FakeDomainProductStore(),
    )


class _FakeSync:
    def __init__(self) -> None:
        self.calls = 0

    async def sync_once(self) -> None:
        self.calls += 1


def test_disabled_skips_worker_registration() -> None:
    worker = build_product_catalog_ms_worker(
        product_catalog_ms=ProductCatalogMsSettings(),
        moysklad_client=None,
        store=InMemoryReferenceDataSnapshotStore(),
        provider=ReferenceDataProvider(),
        drink_source=_drink_source(),
    )
    assert worker is None


def test_worker_run_once_calls_sync() -> None:
    sync = _FakeSync()
    worker = ProductCatalogMsSyncWorker(sync=sync, interval_seconds=60)
    asyncio.run(worker.run_once())
    assert sync.calls == 1


def test_run_continues_after_tick_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sync = _FakeSync()
    worker = ProductCatalogMsSyncWorker(sync=sync, interval_seconds=0)
    stop = asyncio.Event()
    ticks = {"n": 0}

    async def flaky_run_once(self: ProductCatalogMsSyncWorker) -> None:
        ticks["n"] += 1
        if ticks["n"] == 1:
            raise ConnectionError("mongo blip")
        await self.sync.sync_once()
        stop.set()

    monkeypatch.setattr(ProductCatalogMsSyncWorker, "run_once", flaky_run_once)

    async def _scenario() -> None:
        await asyncio.wait_for(worker.run(stop), timeout=2.0)

    with caplog.at_level(logging.ERROR):
        asyncio.run(_scenario())

    assert ticks["n"] >= 2
    assert sync.calls == 1
    assert any(record.message == "product_catalog_ms_sync_tick_failed" for record in caplog.records)


def test_enabled_without_client_returns_none() -> None:
    worker = build_product_catalog_ms_worker(
        product_catalog_ms=ProductCatalogMsSettings.model_construct(
            sync_enabled=True,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            sync_interval_seconds=3600,
            staleness_alert_seconds=7200,
        ),
        moysklad_client=None,
        store=InMemoryReferenceDataSnapshotStore(),
        provider=ReferenceDataProvider(),
        drink_source=_drink_source(),
    )
    assert worker is None


def test_enabled_builds_worker_with_drink_source() -> None:
    class _Client:
        async def get_entity_list(
            self,
            *,
            entity_path: str,
            filter_expr: str,
            limit: int,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            _ = entity_path, filter_expr, limit, offset
            return []

    drink_source = _drink_source()
    worker = build_product_catalog_ms_worker(
        product_catalog_ms=ProductCatalogMsSettings.model_construct(
            sync_enabled=True,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            sync_interval_seconds=3600,
            staleness_alert_seconds=7200,
        ),
        moysklad_client=_Client(),
        store=InMemoryReferenceDataSnapshotStore(),
        provider=ReferenceDataProvider(),
        drink_source=drink_source,
    )
    assert isinstance(worker, ProductCatalogMsSyncWorker)
    assert isinstance(worker.sync, SyncProductCatalogFromMs)
    assert worker.sync.drink_source is drink_source
