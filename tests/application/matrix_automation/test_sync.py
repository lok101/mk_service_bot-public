from __future__ import annotations

from datetime import UTC, datetime

from tests.application.matrix_automation.fixtures.matrix_provider import (
    CatalogReader,
    UtilitySync,
    catalog_tab,
    make_provider,
    seed_ms_name_to_code,
)

from src.application.matrix_automation import SyncGlobalAbort
from src.application.matrix_automation.sync import MatrixReferenceSync
from src.application.reference_data import ReferenceDataSourceId
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSyncError,
    compute_content_hash,
)
from src.application.reference_data.sync import SyncReferenceData
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore


class _StoreWithLastSyncError:
    def __init__(self, snapshot: ReferenceDataSnapshot) -> None:
        self._snapshot = snapshot

    def get(self, source_id: ReferenceDataSourceId) -> ReferenceDataSnapshot | None:
        if source_id is ReferenceDataSourceId.PRODUCT_MULTIPLIERS:
            return self._snapshot
        return None


class _UtilitySyncWithStore:
    def __init__(self, store: _StoreWithLastSyncError) -> None:
        self.store = store

    def sync_source(self, source_id: ReferenceDataSourceId) -> None:
        return None


def test_utility_store_last_sync_error_returns_global_abort() -> None:
    provider = make_provider()
    now = datetime(2026, 7, 16, tzinfo=UTC)
    snapshot = ReferenceDataSnapshot(
        source_id=ReferenceDataSourceId.PRODUCT_MULTIPLIERS,
        rows=(("a",),),
        content_hash=compute_content_hash([["a"]]),
        last_fetched_at=now,
        content_updated_at=now,
        last_sync_error=ReferenceDataSyncError(message="soft fail multipliers", at=now),
    )
    sync = MatrixReferenceSync(
        utility_sync=_UtilitySyncWithStore(_StoreWithLastSyncError(snapshot)),
        provider=provider,
        catalog_reader=CatalogReader([("Snacks", catalog_tab())]),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert isinstance(result, SyncGlobalAbort)
    assert result.reason == "soft fail multipliers"
    assert provider.build_parse_state().enabled_matrices == ()


def test_happy_sync_returns_parse_state() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    sync = MatrixReferenceSync(
        utility_sync=UtilitySync(provider),
        provider=provider,
        catalog_reader=CatalogReader([("Snacks", catalog_tab())]),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert not isinstance(result, SyncGlobalAbort)
    assert len(result.enabled_matrices) == 1


def test_multipliers_structural_fail_returns_global_abort() -> None:
    provider = make_provider()

    class _FailingUtilitySync(UtilitySync):
        def sync_source(self, source_id: ReferenceDataSourceId) -> None:
            if source_id is ReferenceDataSourceId.PRODUCT_MULTIPLIERS:
                raise ValueError("bad multipliers")
            super().sync_source(source_id)

    sync = MatrixReferenceSync(
        utility_sync=_FailingUtilitySync(provider),
        provider=provider,
        catalog_reader=CatalogReader([]),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert isinstance(result, SyncGlobalAbort)
    assert "bad multipliers" in result.reason


class _BadMultipliersReader:
    def read_rows(self, source_id: ReferenceDataSourceId) -> list[list[str]]:
        if source_id is ReferenceDataSourceId.PRODUCT_MULTIPLIERS:
            return [["not", "a", "valid", "header"]]
        return []


def test_multipliers_parse_fail_via_sync_reference_data_returns_global_abort() -> None:
    provider = make_provider()
    store = InMemoryReferenceDataSnapshotStore()
    utility_sync = SyncReferenceData(
        reader=_BadMultipliersReader(),
        store=store,
        provider=provider,
        source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    catalog_reader = CatalogReader([("Snacks", catalog_tab())])
    sync = MatrixReferenceSync(
        utility_sync=utility_sync,
        provider=provider,
        catalog_reader=catalog_reader,
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert isinstance(result, SyncGlobalAbort)
    assert provider.build_parse_state().enabled_matrices == ()


def test_utility_store_get_none_does_not_abort() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    sync = MatrixReferenceSync(
        utility_sync=UtilitySync(provider),
        provider=provider,
        catalog_reader=CatalogReader([("Snacks", catalog_tab())]),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert not isinstance(result, SyncGlobalAbort)
    assert len(result.enabled_matrices) == 1


def test_duplicate_catalog_name_global_abort_resets_provider_catalog_state() -> None:
    provider = make_provider()
    seed_ms_name_to_code(provider)
    sync = MatrixReferenceSync(
        utility_sync=UtilitySync(provider),
        provider=provider,
        catalog_reader=CatalogReader(
            [
                ("Snacks", catalog_tab()),
                ("Snacks", catalog_tab(machines="777")),
            ],
        ),
        utility_source_ids=(ReferenceDataSourceId.PRODUCT_MULTIPLIERS,),
    )
    result = sync.sync()
    assert isinstance(result, SyncGlobalAbort)
    assert "duplicate logical_matrix_name" in result.reason
    assert provider.build_parse_state().enabled_matrices == ()
