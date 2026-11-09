from __future__ import annotations

from beartype import beartype

from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.application.reference_data.ports import ReferenceDataSnapshotStore


@beartype
def looks_like_product_vitrine_rows(rows: tuple[tuple[str, ...], ...]) -> bool:
    if not rows:
        return False
    header = {cell.strip().casefold() for cell in rows[0]}
    return "id" in header and "имя" in header


@beartype
def migrate_sheets_product_catalog_to_vitrine(store: ReferenceDataSnapshotStore) -> None:
    if store.get(ReferenceDataSourceId.PRODUCT_VITRINE) is not None:
        return
    legacy = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    if legacy is None or not legacy.rows:
        return
    if not looks_like_product_vitrine_rows(legacy.rows):
        return
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_VITRINE,
            rows=legacy.rows,
            content_hash=legacy.content_hash,
            last_fetched_at=legacy.last_fetched_at,
            content_updated_at=legacy.content_updated_at,
            last_sync_error=legacy.last_sync_error,
        ),
    )
    empty: tuple[tuple[str, ...], ...] = ()
    store.put(
        ReferenceDataSnapshot(
            source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
            rows=empty,
            content_hash=compute_content_hash(empty),
            last_fetched_at=legacy.last_fetched_at,
            content_updated_at=legacy.content_updated_at,
            last_sync_error=None,
        ),
    )
