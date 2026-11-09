from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation import (
    ImportKitVendingSalesResult,
    compute_machines_to_refresh,
)
from src.application.inventory_reconciliation.ports import (
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.domain.ids import MachineId
from src.infrastructure.alerting.sale_resolve_hold_notifier import (
    NoOpSaleResolveHoldAlertNotifier,
    SaleResolveHoldAlertNotifier,
)
from src.infrastructure.integrations.kitvending.api_models.enums import ResultCode
from src.infrastructure.integrations.kitvending.http_client import (
    KitVendingNetworkError,
    KitVendingResponseError,
)
from src.infrastructure.sales_ingest_watermark import (
    clamp_sales_ingest_cursor,
    compute_fetch_since,
)

_LOGGER: Final = logging.getLogger(__name__)
_RECOVERABLE_KIT_RESULT_CODES: Final = frozenset(
    {
        ResultCode.INVALID_REQUEST_ID,
        ResultCode.TOO_MANY_REQUEST,
    }
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@runtime_checkable
class ImportSalesExecutor(Protocol):
    @beartype
    def execute(self, *, since: datetime) -> ImportKitVendingSalesResult: ...


@runtime_checkable
class RefreshPendingExecutor(Protocol):
    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> object: ...


@beartype
@dataclass(slots=True)
class SalesIngestWorker:
    import_sales: ImportSalesExecutor
    refresh_pending: RefreshPendingExecutor
    sales_store: MachineSalesStore
    poll_interval_seconds: float
    initial_lookback: timedelta
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    tolerance_seconds: int
    now: Callable[[], datetime] = _utc_now
    resolve_hold_notifier: SaleResolveHoldAlertNotifier = field(
        default_factory=NoOpSaleResolveHoldAlertNotifier,
    )
    overlap_seconds: int = 0
    _busy: bool = field(default=False, init=False, repr=False)
    _poll_cursor: datetime | None = field(default=None, init=False, repr=False)

    @beartype
    async def poll_once(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            true_cursor = self._poll_cursor
            fetch_since = compute_fetch_since(
                true_cursor=true_cursor,
                overlap_seconds=self.overlap_seconds,
                initial_lookback=self.initial_lookback,
                now=self.now(),
            )
            try:
                result = await asyncio.to_thread(self.import_sales.execute, since=fetch_since)
            except KitVendingNetworkError as exc:
                _LOGGER.warning(
                    "kitvending_import_network_error",
                    extra={"exception_type": type(exc).__name__},
                )
                return
            except KitVendingResponseError as exc:
                if exc.result_code not in _RECOVERABLE_KIT_RESULT_CODES:
                    raise
                _LOGGER.warning(
                    "kitvending_import_api_error",
                    extra={"result_code": exc.result_code},
                )
                return
            self._log_import_result(result)
            previous_cursor = true_cursor
            candidate_cursor = clamp_sales_ingest_cursor(
                previous_cursor=previous_cursor,
                success_occurred_at=result.success_occurred_ats,
                hold_at=result.hold_at,
            )
            new_cursor = (
                max(candidate_cursor, true_cursor)
                if candidate_cursor is not None and true_cursor is not None
                else candidate_cursor
            )
            if new_cursor is not None and (
                result.hold_at is not None or result.success_occurred_ats
            ):
                self.sales_store.save_global_cursor(new_cursor)
                self._poll_cursor = new_cursor
            if result.hold_at is not None:
                _LOGGER.warning(
                    "kitvending_sale_resolve_hold",
                    extra={
                        "hold_at": result.hold_at.isoformat(),
                        "holding_count": result.holding_skip_count,
                        "previous_cursor": (
                            None if previous_cursor is None else previous_cursor.isoformat()
                        ),
                        "new_cursor": None if new_cursor is None else new_cursor.isoformat(),
                    },
                )
            self._log_late_arrivals(result, true_cursor)
            if (
                result.holding_skip_count > 0
                and result.hold_at is not None
                and (true_cursor is None or result.hold_at >= true_cursor)
            ):
                self.resolve_hold_notifier.notify_holding(
                    hold_at=result.hold_at,
                    holding_skip_count=result.holding_skip_count,
                    fingerprint_pairs=result.fingerprint_pairs,
                    samples=result.holding_samples,
                )
            to_refresh = compute_machines_to_refresh(
                affected_machine_ids=result.affected_machine_ids,
                reconciliation_repo=self.reconciliation_repo,
                cursor=self.sales_store.load_global_cursor(),
                tolerance_seconds=self.tolerance_seconds,
            )
            for machine_id in to_refresh:
                await asyncio.to_thread(
                    self.refresh_pending.execute,
                    machine_id=machine_id,
                )
        finally:
            self._busy = False

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        self._poll_cursor = self.sales_store.load_global_cursor()
        while not stop.is_set():
            await self.poll_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_seconds)

    @beartype
    def _log_late_arrivals(
        self,
        result: ImportKitVendingSalesResult,
        true_cursor: datetime | None,
    ) -> None:
        if true_cursor is None:
            return
        late = [ts for ts in result.inserted_occurred_ats if ts < true_cursor]
        if not late:
            return
        _LOGGER.info(
            "kitvending_late_arrival_recovered",
            extra={
                "count": len(late),
                "min_occurred_at": min(late).isoformat(),
                "true_cursor": true_cursor.isoformat(),
            },
        )

    @beartype
    def _log_import_result(self, result: ImportKitVendingSalesResult) -> None:
        if result.skipped_unmapped:
            _LOGGER.warning(
                "kitvending_import_skipped_unmapped",
                extra={"count": result.skipped_unmapped},
            )
        if result.skipped_unresolved_product or result.skipped_no_machine_code:
            _LOGGER.info(
                "kitvending_fetch_stats",
                extra={
                    "skipped_unresolved_product": result.skipped_unresolved_product,
                    "skipped_no_machine_code": result.skipped_no_machine_code,
                },
            )
        if result.inserted:
            _LOGGER.info(
                "kitvending_import_inserted",
                extra={"count": result.inserted},
            )
