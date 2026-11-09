from __future__ import annotations

from datetime import UTC, datetime

from tests.application.matrix_automation.fixtures.matrix_provider import (
    CatalogReader,
    make_provider,
)

from src.application.matrix_automation.provider import MatrixReferenceDataProvider
from src.application.matrix_automation.sync import MatrixReferenceSync, SyncGlobalAbort
from src.application.reference_data import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.domain.matrix_pricing.product_lookup import resolve_product_code
from src.infrastructure.composition.matrix_automation_factory import (
    MsCatalogHydratingMatrixSync,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_NOW = datetime(2026, 7, 30, tzinfo=UTC)


class _NoOpUtilitySync:
    def __init__(self, store: InMemoryReferenceDataSnapshotStore) -> None:
        self.store = store

    def sync_source(self, source_id: ReferenceDataSourceId) -> None:
        return None


def _hydrating_sync(
    store: InMemoryReferenceDataSnapshotStore,
) -> tuple[MsCatalogHydratingMatrixSync, MatrixReferenceDataProvider]:
    provider = make_provider()
    inner = MatrixReferenceSync(
        utility_sync=_NoOpUtilitySync(store),
        provider=provider,
        catalog_reader=CatalogReader([]),
        utility_source_ids=(),
    )
    return MsCatalogHydratingMatrixSync(inner=inner, store=store), provider


def test_ms_catalog_hydrating_sync_sets_name_to_code_from_store() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    rows = [
        ["code", "name", "entity_kind"],
        ["c1", "Exact Name", "product"],
    ]
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
            rows=tuple(tuple(row) for row in rows),
            content_hash=compute_content_hash(rows),
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    sync, provider = _hydrating_sync(store)
    result = sync.sync()
    assert not isinstance(result, SyncGlobalAbort)
    assert resolve_product_code("Exact Name", provider.name_to_code).is_ok()
    assert resolve_product_code("exact name", provider.name_to_code).is_err()


def test_ms_catalog_hydrating_sync_missing_catalog_empty_name_to_code() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    sync, provider = _hydrating_sync(store)
    result = sync.sync()
    assert not isinstance(result, SyncGlobalAbort)
    assert provider.name_to_code == {}
