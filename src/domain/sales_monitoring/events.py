from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringYesterdayNoSales:
    event_id: EventId
    machine_id: MachineId
    report_day: date
    occurred_at: datetime
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringYesterdayDecline:
    event_id: EventId
    machine_id: MachineId
    report_day: date
    occurred_at: datetime
    report_sum: Decimal
    baseline_avg: Decimal
    drop_percent: int
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringTodayNoSales:
    event_id: EventId
    machine_id: MachineId
    report_day: date
    occurred_at: datetime
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringOfflineOpened:
    event_id: EventId
    machine_id: MachineId
    opened_at: datetime
    occurred_at: datetime
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringOfflineCleared:
    event_id: EventId
    machine_id: MachineId
    opened_event_id: EventId
    opened_at: datetime
    cleared_at: datetime
    occurred_at: datetime
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringNoSalesStaleOpened:
    event_id: EventId
    machine_id: MachineId
    opened_at: datetime
    occurred_at: datetime
    last_sale_at: datetime | None
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SalesMonitoringNoSalesStaleCleared:
    event_id: EventId
    machine_id: MachineId
    opened_event_id: EventId
    opened_at: datetime
    cleared_at: datetime
    occurred_at: datetime
    last_sale_at: datetime | None
    assigned_technician_id: TechnicianId | None
    assigned_technician_display: str | None
    last_serviced_by_technician_id: TechnicianId | None
    last_serviced_by_display: str | None
    last_serviced_at: datetime | None
    clear_trigger: Literal["sale", "exclude"] | None = None
    bypass_active: bool | None = None
