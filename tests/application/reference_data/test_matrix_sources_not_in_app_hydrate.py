from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data import APP_REFERENCE_DATA_SOURCE_IDS, ReferenceDataSourceId
from src.application.reference_data.models import ReferenceDataSnapshot
from src.application.reference_data.provider import ReferenceDataProvider
from src.infrastructure.composition.readiness import ReadinessProbe
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_NOW = datetime(2026, 7, 8, tzinfo=UTC)


def test_matrix_sources_not_in_app_hydrate_scope() -> None:
    assert ReferenceDataSourceId.PRODUCT_MULTIPLIERS not in APP_REFERENCE_DATA_SOURCE_IDS


def test_readiness_reference_data_source_ids_exclude_matrix_sources() -> None:
    probe = ReadinessProbe(
        mongo_client=None,
        redis_client=None,
        reference_data_source_ids=tuple(APP_REFERENCE_DATA_SOURCE_IDS),
    )
    assert ReferenceDataSourceId.PRODUCT_MULTIPLIERS not in probe.reference_data_source_ids


def test_hydrate_from_store_skips_matrix_snapshots_in_store() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_MULTIPLIERS,
            rows=(("product_code", "product_name", "multiplier"),),
            content_hash="sha256:matrix-multipliers",
            last_fetched_at=_NOW,
            content_updated_at=_NOW,
        ),
    )
    provider = ReferenceDataProvider()
    provider.hydrate_from_store(store)
    assert provider.coffee_locations_or_none() is None
    assert provider.product_catalog_or_none() is None
