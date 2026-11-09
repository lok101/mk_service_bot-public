from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from beartype import beartype

from src.application.reference_data.apply_rows_protocol import ReferenceDataApplyRowsProvider
from src.application.reference_data.empty_drink_source import EmptyProductCatalogDrinkSource
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.application.reference_data.ms_product_catalog import (
    MsEntityKind,
    MsProductEntry,
    build_ms_catalog_snapshot_rows,
)
from src.application.reference_data.ports import (
    ProductCatalogDrinkSource,
    ProductCatalogMsAssortmentReader,
    ReferenceDataSnapshotStore,
)

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(slots=True)
class SyncProductCatalogFromMs:
    reader: ProductCatalogMsAssortmentReader
    store: ReferenceDataSnapshotStore
    provider: ReferenceDataApplyRowsProvider
    product_folder_ids: tuple[UUID, ...]
    drink_source: ProductCatalogDrinkSource = field(
        default_factory=EmptyProductCatalogDrinkSource,
    )
    now: Callable[[], datetime] = _utc_now
    _flight: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _flight_guard: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @beartype
    async def sync_once(self) -> None:
        async with self._flight_guard:
            flight = self._flight
            if flight is None or flight.done():
                flight = asyncio.create_task(self._sync_body())
                self._flight = flight
        await flight

    @beartype
    async def _sync_body(self) -> None:
        moment = self.now()
        _LOGGER.info(
            "product_catalog_ms_sync_started",
            extra={
                "product_folder_count": len(self.product_folder_ids),
            },
        )
        try:
            self._reset_reader_skipped_empty_code()
            entries = await self._collect_entries()
            skipped_empty_code = int(getattr(self.reader, "skipped_empty_code", 0) or 0)
            kept: list[MsProductEntry] = []
            for entry in entries:
                if not entry.code.strip():
                    skipped_empty_code += 1
                    _LOGGER.warning(
                        "product_catalog_ms_skipped_empty_code",
                        extra={"product_name": entry.name},
                    )
                    continue
                kept.append(entry)

            product_entries = [e for e in kept if e.entity_kind is MsEntityKind.PRODUCT]
            if not product_entries:
                raise ValueError(
                    "product_catalog_ms_sync requires at least one MS product",
                )
            drink_entries = list(self.drink_source.list_drink_entries())
            kept = [*product_entries, *drink_entries]

            rows = build_ms_catalog_snapshot_rows(kept)
            # validate + apply atomically: parse inside apply_rows raises before overwrite
            self.provider.apply_rows(ReferenceDataSourceId.PRODUCT_CATALOG, rows)

            content_hash = compute_content_hash(rows)
            existing = self.store.get(ReferenceDataSourceId.PRODUCT_CATALOG)
            if existing is not None and existing.content_hash == content_hash:
                content_updated_at = existing.content_updated_at
            else:
                content_updated_at = moment

            snapshot = ReferenceDataSnapshot(
                source_id=ReferenceDataSourceId.PRODUCT_CATALOG,
                rows=tuple(tuple(row) for row in rows),
                content_hash=content_hash,
                last_fetched_at=moment,
                content_updated_at=content_updated_at,
                last_sync_error=None,
            )
            try:
                self.store.put(snapshot)
            except Exception as exc:  # noqa: BLE001 - durability deferred; provider already updated
                _LOGGER.warning(
                    "product_catalog_ms_durability_failed",
                    extra={"error": str(exc)},
                )

            product_count = sum(1 for e in kept if e.entity_kind is MsEntityKind.PRODUCT)
            bundle_count = sum(1 for e in kept if e.entity_kind is MsEntityKind.BUNDLE)
            _LOGGER.info(
                "product_catalog_ms_sync_completed",
                extra={
                    "product_count": product_count,
                    "bundle_count": bundle_count,
                    "skipped_empty_code": skipped_empty_code,
                    "archived_included": True,
                },
            )
        except Exception as exc:  # noqa: BLE001 - keep last-known-good on any failure
            self.store.record_sync_error(
                ReferenceDataSourceId.PRODUCT_CATALOG,
                str(exc),
                moment,
            )
            _LOGGER.error(
                "product_catalog_ms_sync_failed",
                extra={"error": str(exc)},
            )

    @beartype
    def _reset_reader_skipped_empty_code(self) -> None:
        if hasattr(self.reader, "skipped_empty_code"):
            self.reader.skipped_empty_code = 0

    @beartype
    async def _collect_entries(self) -> list[MsProductEntry]:
        entries: list[MsProductEntry] = []
        if self.product_folder_ids:
            entries.extend(
                await self.reader.list_by_folder_ids(
                    entity_kind=MsEntityKind.PRODUCT.value,
                    folder_ids=self.product_folder_ids,
                ),
            )
        return entries
