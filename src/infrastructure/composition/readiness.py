from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis as redis_lib
from beartype import beartype
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from src.application.outbox.handler_ids import NO_SALES_INCIDENT_CONTROL_HANDLER_ID
from src.application.outbox.ports import OutboxAdminStore
from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.ports import ReferenceDataSnapshotStore
from src.application.reference_data.staleness import evaluate_staleness


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
def resolve_reference_data_readiness(
    sheets_source_ids: Sequence[ReferenceDataSourceId],
    *,
    product_catalog_ms_sync_enabled: bool,
    sheets_staleness_seconds: int,
    ms_staleness_seconds: int,
) -> tuple[tuple[ReferenceDataSourceId, ...], int]:
    """Source ids + unified staleness threshold for /health/ready reference_data."""
    source_ids = list(sheets_source_ids)
    staleness = sheets_staleness_seconds
    if product_catalog_ms_sync_enabled:
        source_ids.append(ReferenceDataSourceId.PRODUCT_CATALOG)
        staleness = max(staleness, ms_staleness_seconds)
    return tuple(source_ids), staleness


@beartype
@dataclass(frozen=True, slots=True)
class ReadinessProbe:
    mongo_client: MongoClient[dict[str, Any]] | None
    redis_client: redis_lib.Redis | None
    outbox_admin: OutboxAdminStore | None = None
    reference_data_store: ReferenceDataSnapshotStore | None = None
    reference_data_source_ids: tuple[ReferenceDataSourceId, ...] = ()
    reference_data_staleness_seconds: int = 0
    reference_data_now: Callable[[], datetime] = _utc_now

    @beartype
    def mongo_ok(self) -> bool:
        if self.mongo_client is None:
            return True
        try:
            self.mongo_client.admin.command("ping")
            return True
        except PyMongoError:
            return False

    @beartype
    def redis_ok(self) -> bool:
        if self.redis_client is None:
            return True
        try:
            return bool(self.redis_client.ping())
        except redis_lib.RedisError:
            return False

    @beartype
    def outbox_failed_count(self) -> int:
        if self.outbox_admin is None:
            return 0
        return self.outbox_admin.count_failed(
            handler_id=NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
        )

    @beartype
    def reference_data_freshness(self) -> dict[str, dict[str, object]]:
        if self.reference_data_store is None:
            return {}
        moment = self.reference_data_now()
        result: dict[str, dict[str, object]] = {}
        for source_id in self.reference_data_source_ids:
            snapshot = self.reference_data_store.get(source_id)
            stale = evaluate_staleness(
                snapshot,
                now=moment,
                threshold_seconds=self.reference_data_staleness_seconds,
            )
            result[source_id.value] = {
                "last_fetched_at": (
                    snapshot.last_fetched_at.isoformat() if snapshot is not None else None
                ),
                "stale": stale,
            }
        return result
