from __future__ import annotations

import logging
from datetime import datetime

from beartype import beartype

from src.application.inventory_reconciliation import (
    KitVendingFetchStats,
    KitVendingSaleRow,
)

_LOGGER = logging.getLogger(__name__)
_WARNED = False
_EMPTY_FETCH_STATS = KitVendingFetchStats()


@beartype
class NotConfiguredKitVendingClient:
    """Prod-заглушка до kitvending-sales-ingest.

    См. docs/specs/2026-06-13-kitvending-sales-ingest-design.md.
    """

    @property
    def last_fetch_stats(self) -> KitVendingFetchStats:
        return _EMPTY_FETCH_STATS

    @beartype
    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]:
        del until
        global _WARNED  # noqa: PLW0603
        if not _WARNED:
            _LOGGER.warning("kitvending_client_not_implemented")
            _WARNED = True
        return []
