from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from beartype import beartype

from src.application.inventory_reconciliation.kitshop_backlog_ports import (
    KitShopSalesBacklogStore,
    KitShopSalesGateway,
    KitShopSalesIngestCursorStore,
)

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(frozen=True, slots=True)
class DiscoverKitShopSalesResult:
    upserted: int
    listed: int
    since: datetime
    until: datetime
    cursor: datetime | None


@beartype
@dataclass(slots=True)
class DiscoverKitShopSales:
    gateway: KitShopSalesGateway
    backlog: KitShopSalesBacklogStore
    cursor_store: KitShopSalesIngestCursorStore
    overlap_seconds: int
    initial_lookback: timedelta
    now: Callable[[], datetime] = _utc_now

    @beartype
    def execute(self) -> DiscoverKitShopSalesResult:
        until = self.now()
        watermark = self.cursor_store.load()
        if watermark is None:
            since = until - self.initial_lookback
        else:
            since = watermark - timedelta(seconds=self.overlap_seconds)

        _LOGGER.info(
            "kitshop_sales_discovery_start",
            extra={"since": since.isoformat(), "until": until.isoformat()},
        )
        rows = self.gateway.list_sales_since(since=since, until=until)
        upserted = 0
        max_seen: datetime | None = None
        for row in rows:
            sale_id = int(row.sale_id)  # type: ignore[attr-defined]
            sale_datetime = row.sale_datetime  # type: ignore[attr-defined]
            assert isinstance(sale_datetime, datetime)
            if self.backlog.upsert_pending(sale_id=sale_id):
                upserted += 1
            if max_seen is None or sale_datetime > max_seen:
                max_seen = sale_datetime

        cursor: datetime | None
        if max_seen is not None:
            self.cursor_store.save(max_seen)
            cursor = max_seen
        else:
            cursor = watermark

        _LOGGER.info(
            "kitshop_sales_discovery_done",
            extra={
                "listed": len(rows),
                "upserted": upserted,
                "cursor": None if cursor is None else cursor.isoformat(),
            },
        )
        return DiscoverKitShopSalesResult(
            upserted=upserted,
            listed=len(rows),
            since=since,
            until=until,
            cursor=cursor,
        )
