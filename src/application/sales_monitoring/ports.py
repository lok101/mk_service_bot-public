from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.machine_operations.ports import DomainEventPublisher
from src.application.sales_monitoring.last_maintenance import LastMaintenanceSnapshot
from src.application.sales_monitoring.status_board_pointer import StatusBoardPointer
from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_sales import MachineSale

__all__ = [
    "DomainEventPublisher",
    "KitMachineOfflineStatus",
    "KitVmStatesReader",
    "LastMaintenanceByMachine",
    "LastMaintenanceSnapshot",
    "MachineDisplayLookup",
    "MachineSalesFreshnessLookup",
    "OfflinePollRunner",
    "OutboxHandlerDrainer",
    "ProductDisplayLookup",
    "SalesForReportLoader",
    "SalesForSheetExportLoader",
    "SalesMonitoringAlertNotifier",
    "SalesMonitoringAuditStore",
    "SalesMonitoringDeclineReportNotifier",
    "SalesMonitoringReportNotifier",
    "SalesSheetExportCursor",
    "SalesSheetExportPort",
    "SalesSheetExportRow",
    "StatusBoardPointerStore",
    "StatusBoardTelegram",
    "TechnicianDisplayLookup",
]


@runtime_checkable
class LastMaintenanceByMachine(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> LastMaintenanceSnapshot | None: ...


@runtime_checkable
class SalesMonitoringAuditStore(Protocol):
    @beartype
    def upsert_from_event(self, event: DomainEvent) -> None: ...

    @beartype
    def list_open_offline(self) -> list[dict[str, object]]: ...

    @beartype
    def list_open_no_sales(self) -> list[dict[str, object]]: ...

    @beartype
    def list_cleared_no_sales_since(
        self, *, cleared_at_gte: datetime
    ) -> list[dict[str, object]]: ...

    @beartype
    def list_no_sales_episodes_overlapping(
        self, *, start: datetime, end: datetime
    ) -> list[dict[str, object]]: ...

    @beartype
    def list_no_sales_controls(self, machine_id: MachineId) -> list[dict[str, object]]: ...


@runtime_checkable
class MachineSalesFreshnessLookup(Protocol):
    @beartype
    def last_sale_at(self, machine_id: MachineId) -> datetime | None: ...

    @beartype
    def global_sales_cursor(self) -> datetime | None: ...


@beartype
@dataclass(frozen=True, slots=True)
class KitMachineOfflineStatus:
    machine_code: str
    kit_id: int | None
    is_offline: bool
    last_ping_at: datetime | None = None


@runtime_checkable
class KitVmStatesReader(Protocol):
    @beartype
    def statuses_for(
        self,
        *,
        machine_codes: Sequence[str],
        now: datetime,
        threshold_minutes: int,
    ) -> Sequence[KitMachineOfflineStatus]: ...


@runtime_checkable
class SalesMonitoringAlertNotifier(Protocol):
    @beartype
    def notify_unresolved_kit_ids(self, codes: Sequence[str]) -> None: ...


@runtime_checkable
class SalesMonitoringReportNotifier(Protocol):
    @beartype
    def send_report(self, text: str) -> None: ...


@runtime_checkable
class SalesMonitoringDeclineReportNotifier(Protocol):
    @beartype
    def send_decline_report(self, text: str) -> None: ...


@runtime_checkable
class OutboxHandlerDrainer(Protocol):
    @beartype
    def drain_handler(self, handler_id: str) -> int: ...


@runtime_checkable
class OfflinePollRunner(Protocol):
    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: Sequence[MachineId],
        excluded_codes: frozenset[str],
        now: datetime,
        threshold_minutes: int,
        assigned_by_machine: (
            Mapping[MachineId, tuple[TechnicianId | None, str | None]] | None
        ) = None,
        last_maintenance: LastMaintenanceByMachine | None = None,
        technician_display: TechnicianDisplayLookup | None = None,
    ) -> tuple[MachineId, ...]: ...


@runtime_checkable
class SalesForReportLoader(Protocol):
    @beartype
    def load_for_report(
        self,
        *,
        machine_ids: Sequence[MachineId],
        opened_at: datetime,
        closed_at: datetime,
    ) -> Sequence[MachineSale]: ...


@runtime_checkable
class TechnicianDisplayLookup(Protocol):
    @beartype
    def display_name(self, technician_id: TechnicianId) -> str | None: ...


@runtime_checkable
class SalesSheetExportCursor(Protocol):
    @beartype
    def load(self) -> tuple[datetime, str] | None: ...

    @beartype
    def save(self, *, occurred_at: datetime, source_id: str) -> None: ...


@runtime_checkable
class SalesForSheetExportLoader(Protocol):
    @beartype
    def list_latest(self, *, limit: int) -> Sequence[MachineSale]: ...

    @beartype
    def list_after(
        self,
        *,
        occurred_at: datetime,
        source_id: str,
        limit: int,
    ) -> Sequence[MachineSale]: ...


@beartype
@dataclass(frozen=True, slots=True)
class SalesSheetExportRow:
    values: tuple[str, str, str, str, str, str, str]


@runtime_checkable
class SalesSheetExportPort(Protocol):
    @beartype
    def ensure_header(self, headers: Sequence[str]) -> None: ...

    @beartype
    def append_rows(self, rows: Sequence[SalesSheetExportRow]) -> None: ...

    @beartype
    def trim_to_max_data_rows(self, max_rows: int) -> int: ...


@runtime_checkable
class MachineDisplayLookup(Protocol):
    @beartype
    def name_for(self, machine_id: MachineId) -> str | None: ...


@runtime_checkable
class ProductDisplayLookup(Protocol):
    @beartype
    def name_for(self, product_code: str) -> str | None: ...


@runtime_checkable
class StatusBoardPointerStore(Protocol):
    @beartype
    def load(self) -> StatusBoardPointer | None: ...

    @beartype
    def save(self, pointer: StatusBoardPointer) -> None: ...


@runtime_checkable
class StatusBoardTelegram(Protocol):
    @beartype
    def send_board(self, text: str) -> int: ...

    @beartype
    def edit_board(self, *, message_id: int, text: str) -> None: ...
