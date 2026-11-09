from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.ms_product_catalog import MsEntityKind, MsProductEntry
from src.application.reference_data.ports import ProductCatalogMsAssortmentReader
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.sync_product_catalog_ms import SyncProductCatalogFromMs
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


class _FakeReader:
    def __init__(self, *, products: list[MsProductEntry] | None = None, fail: bool = False) -> None:
        self.products = products or []
        self.bundles: list[MsProductEntry] = []
        self.fail = fail
        self.calls: list[tuple[str, tuple[UUID, ...]]] = []

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        self.calls.append((entity_kind, tuple(folder_ids)))
        if self.fail:
            raise RuntimeError("ms down")
        if entity_kind == "product":
            return list(self.products)
        return list(self.bundles)


class _FakeDrinkSource:
    def __init__(self, entries: list[MsProductEntry] | None = None, *, fail: bool = False) -> None:
        self.entries = entries or []
        self.fail = fail

    def list_drink_entries(self) -> list[MsProductEntry]:
        if self.fail:
            raise RuntimeError("drink source down")
        return list(self.entries)


def test_sync_merges_bom_drinks_into_catalog() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    reader = _FakeReader(
        products=[MsProductEntry("p1", "Product One", MsEntityKind.PRODUCT)],
    )
    drinks = _FakeDrinkSource(
        [
            MsProductEntry("d1", "Drink One", MsEntityKind.BUNDLE),
            MsProductEntry("d2", "Drink Two", MsEntityKind.BUNDLE),
        ],
    )
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=reader,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=drinks,
            now=lambda: _NOW,
        ).sync_once()
    )
    catalog = provider.product_catalog()
    assert catalog.by_code["p1"].entity_kind is MsEntityKind.PRODUCT
    assert catalog.by_code["d1"].entity_kind is MsEntityKind.BUNDLE
    assert catalog.by_code["d2"].name == "Drink Two"
    assert all(c[0] == "product" for c in reader.calls)
    assert not any(c[0] == "bundle" for c in reader.calls)


def test_sync_empty_drinks_keeps_products_only() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    reader = _FakeReader(
        products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)],
    )
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=reader,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(),
            now=lambda: _NOW,
        ).sync_once()
    )
    catalog = provider.product_catalog()
    assert set(catalog.by_code) == {"p1"}
    snap = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert snap is not None
    assert snap.last_sync_error is None


def test_sync_empty_product_paths_requires_ms_product() -> None:
    reader = _FakeReader(products=[MsProductEntry("p", "P", MsEntityKind.PRODUCT)])
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    sync = SyncProductCatalogFromMs(
        reader=reader,
        store=store,
        provider=provider,
        product_folder_ids=(),
        now=lambda: _NOW,
    )
    asyncio.run(sync.sync_once())
    assert reader.calls == []
    assert provider.product_catalog_or_none() is None
    snap = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert snap is not None
    assert snap.last_sync_error is not None
    assert "at least one MS product" in snap.last_sync_error.message


def test_sync_full_replace_overwrites_previous_codes() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    first = _FakeReader(products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)])
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=first,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            now=lambda: _NOW,
        ).sync_once()
    )
    assert "p1" in provider.product_catalog().by_code

    second = _FakeReader(products=[MsProductEntry("p2", "Two", MsEntityKind.PRODUCT)])
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=second,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            now=lambda: _NOW,
        ).sync_once()
    )
    catalog = provider.product_catalog()
    assert "p2" in catalog.by_code
    assert "p1" not in catalog.by_code
    snap = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert snap is not None
    assert snap.last_sync_error is None
    assert any(row[0] == "p2" for row in snap.rows[1:])
    assert all(row[0] != "p1" for row in snap.rows[1:])


def test_sync_api_fail_keeps_last_known_good() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    good = _FakeReader(
        products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)],
    )
    sync_ok = SyncProductCatalogFromMs(
        reader=good,
        store=store,
        provider=provider,
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: _NOW,
    )
    asyncio.run(sync_ok.sync_once())
    assert provider.product_catalog_or_none() is not None
    failing = _FakeReader(fail=True)
    sync_fail = SyncProductCatalogFromMs(
        reader=failing,
        store=store,
        provider=provider,
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: _NOW,
    )
    asyncio.run(sync_fail.sync_once())
    snap = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert snap is not None
    assert snap.last_sync_error is not None
    assert provider.product_catalog_or_none() is not None
    assert "p1" in provider.product_catalog().by_code


def test_sync_duplicate_keeps_last_known_good(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    first = _FakeReader(products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)])
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=first,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            now=lambda: _NOW,
        ).sync_once()
    )

    class _DupReader(_FakeReader):
        async def list_by_folder_ids(self, *, entity_kind: str, folder_ids: Sequence[UUID]):
            return [
                MsProductEntry("a", "Same", MsEntityKind.PRODUCT),
                MsProductEntry("b", "Same", MsEntityKind.PRODUCT),
            ]

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            SyncProductCatalogFromMs(
                reader=_DupReader(),
                store=store,
                provider=provider,
                product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
                now=lambda: _NOW,
            ).sync_once()
        )
    assert "p1" in provider.product_catalog().by_code
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).last_sync_error is not None
    assert any(
        r.levelno >= logging.ERROR and "product_catalog_ms_sync_failed" in r.message
        for r in caplog.records
    )


def test_sync_completed_logs_reader_skipped_empty_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _ReaderWithSkip(_FakeReader):
        def __init__(self) -> None:
            super().__init__(
                products=[
                    MsProductEntry("p1", "One", MsEntityKind.PRODUCT),
                ],
            )
            self.skipped_empty_code = 2

        async def list_by_folder_ids(
            self,
            *,
            entity_kind: str,
            folder_ids: Sequence[UUID],
        ) -> list[MsProductEntry]:
            result = await super().list_by_folder_ids(
                entity_kind=entity_kind,
                folder_ids=folder_ids,
            )
            # simulate skips accumulated during list (after sync resets to 0)
            self.skipped_empty_code = 2
            return result

    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    with caplog.at_level(logging.INFO):
        asyncio.run(
            SyncProductCatalogFromMs(
                reader=_ReaderWithSkip(),
                store=store,
                provider=provider,
                product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
                now=lambda: _NOW,
            ).sync_once()
        )
    completed = [r for r in caplog.records if "product_catalog_ms_sync_completed" in r.message]
    assert completed
    assert completed[-1].__dict__.get("skipped_empty_code") == 2


def test_sync_zero_ms_products_keeps_last_known_good() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    good = _FakeReader(products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)])
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=good,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(),
            now=lambda: _NOW,
        ).sync_once()
    )
    empty = _FakeReader(products=[])
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=empty,
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(
                [MsProductEntry("d1", "Drink", MsEntityKind.BUNDLE)],
            ),
            now=lambda: _NOW,
        ).sync_once()
    )
    assert "p1" in provider.product_catalog().by_code
    assert "d1" not in provider.product_catalog().by_code
    snap = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert snap is not None
    assert snap.last_sync_error is not None
    assert "at least one MS product" in snap.last_sync_error.message


def test_sync_drink_code_collision_keeps_lkg() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(),
            now=lambda: _NOW,
        ).sync_once()
    )
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("shared", "Product", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(
                [MsProductEntry("shared", "Drink", MsEntityKind.BUNDLE)],
            ),
            now=lambda: _NOW,
        ).sync_once()
    )
    assert "p1" in provider.product_catalog().by_code
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).last_sync_error is not None


def test_sync_drink_name_collision_keeps_lkg() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(),
            now=lambda: _NOW,
        ).sync_once()
    )
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("p2", "Same Name", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(
                [MsProductEntry("d1", "Same Name", MsEntityKind.BUNDLE)],
            ),
            now=lambda: _NOW,
        ).sync_once()
    )
    assert "p1" in provider.product_catalog().by_code
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).last_sync_error is not None


def test_sync_drink_source_fail_keeps_lkg() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    provider = ReferenceDataProvider()
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("p1", "One", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(),
            now=lambda: _NOW,
        ).sync_once()
    )
    asyncio.run(
        SyncProductCatalogFromMs(
            reader=_FakeReader(
                products=[MsProductEntry("p2", "Two", MsEntityKind.PRODUCT)],
            ),
            store=store,
            provider=provider,
            product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
            drink_source=_FakeDrinkSource(fail=True),
            now=lambda: _NOW,
        ).sync_once()
    )
    assert "p1" in provider.product_catalog().by_code
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).last_sync_error is not None


class _GatedAssortment:
    def __init__(self) -> None:
        self.entered = 0
        self.release = asyncio.Event()

    async def list_by_folder_ids(
        self,
        *,
        entity_kind: str,
        folder_ids: Sequence[UUID],
    ) -> list[MsProductEntry]:
        _ = entity_kind, folder_ids
        self.entered += 1
        await self.release.wait()
        return [MsProductEntry("p1", "Product One", MsEntityKind.PRODUCT)]


def _sync(reader: ProductCatalogMsAssortmentReader) -> SyncProductCatalogFromMs:
    return SyncProductCatalogFromMs(
        reader=reader,
        store=InMemoryReferenceDataSnapshotStore(),
        provider=ReferenceDataProvider(),
        product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        now=lambda: datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )


def test_sync_once_second_caller_does_not_start_second_walk() -> None:
    reader = _GatedAssortment()
    sync = _sync(reader)

    async def scenario() -> None:
        first = asyncio.create_task(sync.sync_once())
        while reader.entered == 0:
            await asyncio.sleep(0)
        second = asyncio.create_task(sync.sync_once())
        await asyncio.sleep(0)
        assert reader.entered == 1
        reader.release.set()
        await first
        await second

    asyncio.run(scenario())
    assert reader.entered == 1


def test_sync_once_after_finish_starts_another_walk() -> None:
    reader = _FakeReader(
        products=[MsProductEntry("p1", "Product One", MsEntityKind.PRODUCT)],
    )
    sync = _sync(reader)

    async def scenario() -> None:
        await sync.sync_once()
        await sync.sync_once()

    asyncio.run(scenario())
    assert len(reader.calls) == 2
