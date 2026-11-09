from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.inventory_reconciliation.discover_kitshop_sales import (
    DiscoverKitShopSalesResult,
)
from src.application.inventory_reconciliation.drain_kitshop_sales import (
    DrainKitShopSalesBacklogResult,
)
from src.domain.ids import MachineId
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopNetworkError,
    KitShopResponseError,
)
from src.infrastructure.kitshop_sales_ingest_worker import KitShopSalesIngestWorker


@dataclass(slots=True)
class RecordingDiscover:
    result: DiscoverKitShopSalesResult
    calls: int = 0

    def execute(self) -> DiscoverKitShopSalesResult:
        self.calls += 1
        return self.result


@dataclass(slots=True)
class RecordingDrain:
    result: DrainKitShopSalesBacklogResult
    calls: int = 0

    def execute(self, *, limit: int = 1) -> DrainKitShopSalesBacklogResult:
        del limit
        self.calls += 1
        return self.result


@dataclass(slots=True)
class RecordingRefresh:
    called_with_machine_ids: list[MachineId] = field(default_factory=list)

    def execute(self, *, machine_id: MachineId | None = None) -> int:
        if machine_id is not None:
            self.called_with_machine_ids.append(machine_id)
        return 0


@dataclass(slots=True)
class RaisingDrain:
    exc: BaseException

    def execute(self, *, limit: int = 1) -> DrainKitShopSalesBacklogResult:
        del limit
        raise self.exc


@dataclass(slots=True)
class RaisingRefresh:
    def execute(self, *, machine_id: MachineId | None = None) -> int:
        del machine_id
        raise RuntimeError("refresh down")


@dataclass(slots=True)
class RaisingDiscover:
    exc: BaseException

    def execute(self) -> DiscoverKitShopSalesResult:
        raise self.exc


def test_kitshop_worker_runs_discovery_and_drain_once() -> None:
    discover = RecordingDiscover(
        result=DiscoverKitShopSalesResult(
            upserted=1,
            listed=1,
            since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
            until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
            cursor=None,
        ),
    )
    drain = RecordingDrain(
        result=DrainKitShopSalesBacklogResult(
            deducted=1,
            held=0,
            done=1,
            claimed=1,
            affected_machine_ids=(),
        ),
    )
    refresh = RecordingRefresh()

    worker = KitShopSalesIngestWorker(
        discover=discover,
        drain=drain,
        refresh_pending=refresh,
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
    )

    async def _run() -> None:
        await worker.discovery_once()
        await worker.drain_once()

    asyncio.run(_run())
    assert discover.calls == 1
    assert drain.calls == 1


def test_drain_once_survives_unexpected_exception(caplog: pytest.LogCaptureFixture) -> None:
    # error → continue
    worker = KitShopSalesIngestWorker(
        discover=RecordingDiscover(
            result=DiscoverKitShopSalesResult(
                upserted=0,
                listed=0,
                since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
                cursor=None,
            ),
        ),
        drain=RaisingDrain(exc=RuntimeError("boom")),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
    )
    caplog.set_level(logging.ERROR)
    asyncio.run(worker.drain_once())
    assert "kitshop_sales_drain_unexpected_error" in caplog.text
    asyncio.run(worker.drain_once())


def test_drain_once_survives_refresh_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # error → следующий drain_once всё ещё вызывается
    drain = RecordingDrain(
        result=DrainKitShopSalesBacklogResult(
            deducted=0,
            held=0,
            done=0,
            claimed=1,
            affected_machine_ids=(MachineId("m1"),),
        ),
    )
    worker = KitShopSalesIngestWorker(
        discover=RecordingDiscover(
            result=DiscoverKitShopSalesResult(
                upserted=0,
                listed=0,
                since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
                cursor=None,
            ),
        ),
        drain=drain,
        refresh_pending=RaisingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
    )
    caplog.set_level(logging.ERROR)
    asyncio.run(worker.drain_once())
    assert "kitshop_sales_drain_refresh_unexpected_error" in caplog.text
    asyncio.run(worker.drain_once())
    assert drain.calls == 2


def test_discovery_once_survives_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # error → continue
    worker = KitShopSalesIngestWorker(
        discover=RaisingDiscover(exc=RuntimeError("boom")),
        drain=RecordingDrain(
            result=DrainKitShopSalesBacklogResult(
                deducted=0,
                held=0,
                done=0,
                claimed=0,
                affected_machine_ids=(),
            ),
        ),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
    )
    caplog.set_level(logging.ERROR)
    asyncio.run(worker.discovery_once())
    assert "kitshop_sales_discovery_unexpected_error" in caplog.text


def test_drain_once_http_error_still_warning(caplog: pytest.LogCaptureFixture) -> None:
    # HTTP → WARNING, not unexpected ERROR
    worker = KitShopSalesIngestWorker(
        discover=RecordingDiscover(
            result=DiscoverKitShopSalesResult(
                upserted=0,
                listed=0,
                since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
                cursor=None,
            ),
        ),
        drain=RaisingDrain(exc=KitShopNetworkError("503")),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
    )
    caplog.set_level(logging.WARNING)
    asyncio.run(worker.drain_once())
    assert "kitshop_sales_drain_http_error" in caplog.text
    assert "kitshop_sales_drain_unexpected_error" not in caplog.text


class _RecordingAlert:
    def __init__(self) -> None:
        self.held: list[tuple[int, tuple[str, ...]]] = []
        self.failed: list[tuple[str, str]] = []

    def notify_held(self, *, count: int, reasons: tuple[str, ...]) -> None:
        self.held.append((count, reasons))

    def notify_phase_failed(self, *, phase: str, exception_type: str) -> None:
        self.failed.append((phase, exception_type))


def test_kitshop_worker_discovery_network_error_notifies_and_continues() -> None:
    # error
    alerts = _RecordingAlert()
    worker = KitShopSalesIngestWorker(
        discover=RaisingDiscover(exc=KitShopNetworkError("down")),
        drain=RecordingDrain(
            result=DrainKitShopSalesBacklogResult(
                deducted=0,
                held=0,
                done=0,
                claimed=0,
            ),
        ),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
        alert_notifier=alerts,
    )
    asyncio.run(worker.discovery_once())
    asyncio.run(worker.discovery_once())
    assert alerts.failed == [
        ("discovery", "KitShopNetworkError"),
        ("discovery", "KitShopNetworkError"),
    ]


def test_kitshop_worker_drain_network_error_notifies_and_continues() -> None:
    # error
    alerts = _RecordingAlert()
    worker = KitShopSalesIngestWorker(
        discover=RecordingDiscover(
            result=DiscoverKitShopSalesResult(
                upserted=0,
                listed=0,
                since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
                cursor=None,
            ),
        ),
        drain=RaisingDrain(exc=KitShopResponseError("bad", 1)),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
        alert_notifier=alerts,
    )
    asyncio.run(worker.drain_once())
    asyncio.run(worker.drain_once())
    assert alerts.failed == [
        ("drain", "KitShopResponseError"),
        ("drain", "KitShopResponseError"),
    ]


def test_kitshop_worker_drain_unexpected_error_notifies() -> None:
    # error: прочий Exception тоже алертит
    alerts = _RecordingAlert()
    worker = KitShopSalesIngestWorker(
        discover=RecordingDiscover(
            result=DiscoverKitShopSalesResult(
                upserted=0,
                listed=0,
                since=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                until=datetime(2026, 9, 4, 12, 15, tzinfo=UTC),
                cursor=None,
            ),
        ),
        drain=RaisingDrain(exc=RuntimeError("boom")),
        refresh_pending=RecordingRefresh(),
        discovery_interval_seconds=900.0,
        drain_interval_seconds=6.0,
        alert_notifier=alerts,
    )
    asyncio.run(worker.drain_once())
    assert alerts.failed == [("drain", "RuntimeError")]
