from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.reference_data.apply_rows_protocol import ReferenceDataApplyRowsProvider
from src.application.reference_data.models import (
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    compute_content_hash,
)
from src.application.reference_data.ports import (
    ReferenceDataSnapshotStore,
    ReferenceDataSourceReader,
)

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(slots=True)
class SyncReferenceData:
    reader: ReferenceDataSourceReader
    store: ReferenceDataSnapshotStore
    provider: ReferenceDataApplyRowsProvider
    source_ids: tuple[ReferenceDataSourceId, ...]
    now: Callable[[], datetime] = _utc_now

    @beartype
    def sync_all(self) -> None:
        for source_id in self.source_ids:
            self.sync_source(source_id)

    @beartype
    def sync_source(self, source_id: ReferenceDataSourceId) -> None:
        moment = self.now()
        existing = self.store.get(source_id)
        try:
            rows = self.reader.read_rows(source_id)
            self.provider.apply_rows(source_id, rows)
        except Exception as exc:  # noqa: BLE001 - keep last-known-good on any read/parse failure
            self.store.record_sync_error(source_id, str(exc), moment)
            _LOGGER.warning(
                "reference_data_sync_failed",
                extra={"source_id": source_id.value, "error": str(exc)},
            )
            return

        content_hash = compute_content_hash(rows)
        if existing is not None and existing.content_hash == content_hash:
            content_updated_at = existing.content_updated_at
        else:
            content_updated_at = moment

        snapshot = ReferenceDataSnapshot(
            source_id=source_id,
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
                "reference_data_durability_failed",
                extra={"source_id": source_id.value, "error": str(exc)},
            )
