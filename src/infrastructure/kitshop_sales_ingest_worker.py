from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation import compute_machines_to_refresh
from src.application.inventory_reconciliation.discover_kitshop_sales import (
    DiscoverKitShopSalesResult,
)
from src.application.inventory_reconciliation.drain_kitshop_sales import (
    DrainKitShopSalesBacklogResult,
    KitShopSaleAlertNotifier,
    NoOpKitShopSaleAlertNotifier,
)
from src.application.inventory_reconciliation.ports import (
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.domain.ids import MachineId
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopNetworkError,
    KitShopResponseError,
)

_LOGGER: Final = logging.getLogger(__name__)


@runtime_checkable
class DiscoverKitShopSalesExecutor(Protocol):
    @beartype
    def execute(self) -> DiscoverKitShopSalesResult: ...


@runtime_checkable
class DrainKitShopSalesExecutor(Protocol):
    @beartype
    def execute(self, *, limit: int = 1) -> DrainKitShopSalesBacklogResult: ...


@runtime_checkable
class RefreshPendingExecutor(Protocol):
    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> object: ...


@beartype
@dataclass(slots=True)
class KitShopSalesIngestWorker:
    discover: DiscoverKitShopSalesExecutor
    drain: DrainKitShopSalesExecutor
    refresh_pending: RefreshPendingExecutor
    discovery_interval_seconds: float
    drain_interval_seconds: float
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository | None = None
    sales_store: MachineSalesStore | None = None
    tolerance_seconds: int = 0
    alert_notifier: KitShopSaleAlertNotifier = field(
        default_factory=NoOpKitShopSaleAlertNotifier,
    )
    _discovery_busy: bool = field(default=False, init=False, repr=False)
    _drain_busy: bool = field(default=False, init=False, repr=False)

    @beartype
    async def discovery_once(self) -> None:
        if self._discovery_busy:
            return
        self._discovery_busy = True
        try:
            try:
                result = await asyncio.to_thread(self.discover.execute)
            except (KitShopNetworkError, KitShopResponseError) as exc:
                _LOGGER.warning(
                    "kitshop_sales_discovery_http_error",
                    extra={"exception_type": type(exc).__name__},
                )
                self.alert_notifier.notify_phase_failed(
                    phase="discovery",
                    exception_type=type(exc).__name__,
                )
                return
            except Exception as exc:
                _LOGGER.exception("kitshop_sales_discovery_unexpected_error")
                self.alert_notifier.notify_phase_failed(
                    phase="discovery",
                    exception_type=type(exc).__name__,
                )
                return
            self._log_discovery_result(result)
        finally:
            self._discovery_busy = False

    @beartype
    async def drain_once(self) -> None:
        if self._drain_busy:
            return
        self._drain_busy = True
        try:
            try:
                result = await asyncio.to_thread(self.drain.execute)
            except (KitShopNetworkError, KitShopResponseError) as exc:
                _LOGGER.warning(
                    "kitshop_sales_drain_http_error",
                    extra={"exception_type": type(exc).__name__},
                )
                self.alert_notifier.notify_phase_failed(
                    phase="drain",
                    exception_type=type(exc).__name__,
                )
                return
            except Exception as exc:
                _LOGGER.exception("kitshop_sales_drain_unexpected_error")
                self.alert_notifier.notify_phase_failed(
                    phase="drain",
                    exception_type=type(exc).__name__,
                )
                return
            try:
                await self._refresh_after_drain(result)
            except Exception as exc:
                _LOGGER.exception("kitshop_sales_drain_refresh_unexpected_error")
                self.alert_notifier.notify_phase_failed(
                    phase="drain",
                    exception_type=type(exc).__name__,
                )
        finally:
            self._drain_busy = False

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        discovery_task = asyncio.create_task(self._loop_discovery(stop))
        drain_task = asyncio.create_task(self._loop_drain(stop))
        try:
            await stop.wait()
        finally:
            discovery_task.cancel()
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await discovery_task
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task

    @beartype
    async def run_forever(self) -> None:
        await self.run(asyncio.Event())

    @beartype
    async def _loop_discovery(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.discovery_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.discovery_interval_seconds)

    @beartype
    async def _loop_drain(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.drain_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.drain_interval_seconds)

    @beartype
    async def _refresh_after_drain(self, result: DrainKitShopSalesBacklogResult) -> None:
        if not result.affected_machine_ids:
            return
        if self.reconciliation_repo is None or self.sales_store is None:
            to_refresh = result.affected_machine_ids
        else:
            to_refresh = compute_machines_to_refresh(
                affected_machine_ids=result.affected_machine_ids,
                reconciliation_repo=self.reconciliation_repo,
                cursor=self.sales_store.load_global_cursor(),
                tolerance_seconds=self.tolerance_seconds,
            )
        for machine_id in to_refresh:
            await asyncio.to_thread(self.refresh_pending.execute, machine_id=machine_id)

    @staticmethod
    @beartype
    def _log_discovery_result(result: DiscoverKitShopSalesResult) -> None:
        if result.upserted:
            _LOGGER.info(
                "kitshop_sales_discovery_upserted",
                extra={"upserted": result.upserted, "listed": result.listed},
            )


__all__ = ["KitShopSalesIngestWorker"]
