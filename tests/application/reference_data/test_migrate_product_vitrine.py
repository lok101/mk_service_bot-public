from __future__ import annotations

from datetime import UTC, datetime

from src.application.reference_data.migrate_product_vitrine import (
    looks_like_product_vitrine_rows,
    migrate_sheets_product_catalog_to_vitrine,
)
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.infrastructure.reference_data.memory_store import InMemoryReferenceDataSnapshotStore

_NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _snap(
    source_id: ReferenceDataSourceId,
    rows: tuple[tuple[str, ...], ...],
) -> ReferenceDataSnapshot:
    return ReferenceDataSnapshot(
        source_id=source_id,
        rows=rows,
        content_hash=compute_content_hash(rows),
        last_fetched_at=_NOW,
        content_updated_at=_NOW,
    )


def test_looks_like_product_vitrine_rows_detects_sheets_header() -> None:
    assert looks_like_product_vitrine_rows((("ID", "Имя", "aliases"), ("c1", "Coffee", "")))
    assert not looks_like_product_vitrine_rows(
        (("code", "name", "entity_kind"), ("c1", "Coffee", "product")),
    )


def test_migrate_sheets_product_catalog_to_vitrine() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    sheets_rows = (("id", "имя"), ("sku1", "Сахар"))
    store.put(_snap(ReferenceDataSourceId.PRODUCT_CATALOG, sheets_rows))

    migrate_sheets_product_catalog_to_vitrine(store)

    vitrine = store.get(ReferenceDataSourceId.PRODUCT_VITRINE)
    assert vitrine is not None
    assert vitrine.rows == sheets_rows
    legacy = store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
    assert legacy is not None
    assert legacy.rows == ()  # cleared so hydrate skips MS until first MS sync


def test_migrate_skips_when_vitrine_exists() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    store.put(_snap(ReferenceDataSourceId.PRODUCT_VITRINE, (("id", "имя"), ("a", "A"))))
    store.put(_snap(ReferenceDataSourceId.PRODUCT_CATALOG, (("id", "имя"), ("b", "B"))))

    migrate_sheets_product_catalog_to_vitrine(store)

    assert store.get(ReferenceDataSourceId.PRODUCT_VITRINE).rows[1][0] == "a"
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).rows[1][0] == "b"


def test_migrate_skips_ms_shaped_catalog() -> None:
    store = InMemoryReferenceDataSnapshotStore()
    ms_rows = (("code", "name", "entity_kind"), ("c1", "N", "product"))
    store.put(_snap(ReferenceDataSourceId.PRODUCT_CATALOG, ms_rows))

    migrate_sheets_product_catalog_to_vitrine(store)

    assert store.get(ReferenceDataSourceId.PRODUCT_VITRINE) is None
    assert store.get(ReferenceDataSourceId.PRODUCT_CATALOG).rows == ms_rows
