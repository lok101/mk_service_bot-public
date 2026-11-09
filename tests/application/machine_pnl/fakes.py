from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from beartype import beartype

from src.application.machine_pnl.models import PeriodPnl
from src.application.machine_pnl.opex_params import EffectiveOpExParams
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.domain.ids import MachineId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale

_ZERO = Decimal("0")


class _ZeroMaintenanceCall(NamedTuple):
    period_id: str
    machine_id: MachineId
    opened_at: datetime
    closed_at: datetime
    maintenance_count: int


@beartype
@dataclass(slots=True)
class InMemoryUnitCostCatalog:
    _costs: dict[tuple[str, date], Decimal | None] = field(default_factory=dict)
    _default: Decimal | None = None

    def set(self, product_code: str, *, as_of: date, cost: Decimal | None) -> None:
        self._costs[(product_code, as_of)] = cost

    def get(self, product_code: str, *, as_of: date) -> Decimal | None:
        if (product_code, as_of) in self._costs:
            return self._costs[(product_code, as_of)]
        return self._default


@beartype
@dataclass(slots=True)
class InMemoryPeriodPnlStore:
    _by_pnl_id: dict[str, PeriodPnl] = field(default_factory=dict)
    source_session_ids: dict[str, str | None] = field(default_factory=dict)

    def save(self, pnl: PeriodPnl, *, source_session_id: str | None) -> None:
        self._by_pnl_id[pnl.pnl_id] = pnl
        self.source_session_ids[pnl.pnl_id] = source_session_id

    def get(self, pnl_id: str) -> PeriodPnl | None:
        return self._by_pnl_id.get(pnl_id)

    def list_by_period_id(self, period_id: str) -> tuple[PeriodPnl, ...]:
        return tuple(pnl for pnl in self._by_pnl_id.values() if pnl.period_id == period_id)

    def list_overlapping(
        self,
        machine_id: MachineId,
        *,
        range_start: datetime,
        range_end: datetime,
    ) -> tuple[PeriodPnl, ...]:
        return tuple(
            pnl
            for pnl in self._by_pnl_id.values()
            if pnl.machine_id == machine_id
            and pnl.opened_at < range_end
            and pnl.closed_at > range_start
        )

    def list_for_machine(self, machine_id: MachineId) -> tuple[PeriodPnl, ...]:
        return tuple(pnl for pnl in self._by_pnl_id.values() if pnl.machine_id == machine_id)


@beartype
@dataclass(slots=True)
class InMemoryPeriodSnapshotReader:
    _by_period_id: dict[str, ResponsibilityPeriodReconciliation] = field(default_factory=dict)

    def save(self, snapshot: ResponsibilityPeriodReconciliation) -> None:
        self._by_period_id[snapshot.period_id] = snapshot

    def get_by_period_id(self, period_id: str) -> ResponsibilityPeriodReconciliation | None:
        return self._by_period_id.get(period_id)


@beartype
@dataclass(slots=True)
class InMemoryMachineSalesWindowReader:
    _sales: list[MachineSale] = field(default_factory=list)

    def add(self, sale: MachineSale) -> None:
        self._sales.append(sale)

    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        return tuple(
            sale
            for sale in self._sales
            if sale.machine_id == machine_id and opened_at < sale.occurred_at <= closed_at
        )


@beartype
@dataclass(slots=True)
class InMemoryResidualSessionReader:
    _views: list[ResidualSessionView] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def add(self, view: ResidualSessionView) -> None:
        self._views.append(view)

    def find_completed_containing(
        self,
        period_id: str,
        *,
        technician_id: TechnicianId,
    ) -> tuple[ResidualSessionView, ...]:
        self.calls.append((period_id, technician_id.value))
        return tuple(
            view
            for view in self._views
            if view.technician_id == technician_id.value and period_id in view.period_ids
        )


@beartype
@dataclass(slots=True)
class InMemoryServiceFactCounter:
    _counts: dict[tuple[MachineId, datetime, datetime], int] = field(default_factory=dict)
    _default: int = 0

    def set_count(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
        count: int,
    ) -> None:
        self._counts[(machine_id, opened_at, closed_at)] = count

    def set_default(self, count: int) -> None:
        self._default = count

    def count_completed(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> int:
        return self._counts.get((machine_id, opened_at, closed_at), self._default)


@beartype
@dataclass(slots=True)
class RecordingZeroMaintenanceAlerter:
    calls: list[_ZeroMaintenanceCall] = field(default_factory=list)

    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        maintenance_count: int,
    ) -> None:
        self.calls.append(
            _ZeroMaintenanceCall(
                period_id=period_id,
                machine_id=machine_id,
                opened_at=opened_at,
                closed_at=closed_at,
                maintenance_count=maintenance_count,
            )
        )


@beartype
@dataclass(slots=True)
class NoOpZeroMaintenanceAlerter:
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        maintenance_count: int,
    ) -> None:
        return None


@beartype
@dataclass(slots=True)
class InMemoryOpExParamsPort:
    _by_machine: dict[MachineId, EffectiveOpExParams] = field(default_factory=dict)
    _default: EffectiveOpExParams | None = None

    @classmethod
    def zeros(cls) -> InMemoryOpExParamsPort:
        return cls(
            _default=EffectiveOpExParams(
                rent_monthly=_ZERO,
                rent_percent=_ZERO,
                duty_mode="patent",
                patent_monthly=_ZERO,
                tax_percent=_ZERO,
                acquiring_percent=_ZERO,
                acquiring_fee_per_sale=_ZERO,
                terminal_monthly=_ZERO,
                labor_rate=Decimal("0"),
                params_incomplete=False,
                missing_labor_rate=False,
            )
        )

    def set(self, machine_id: MachineId, params: EffectiveOpExParams) -> None:
        self._by_machine[machine_id] = params

    def resolve(self, machine_id: MachineId, *, as_of: date) -> EffectiveOpExParams:
        del as_of
        if machine_id in self._by_machine:
            return self._by_machine[machine_id]
        if self._default is not None:
            return self._default
        raise KeyError(f"No OpEx params for machine {machine_id.value}")


@beartype
@dataclass(slots=True)
class InMemoryLocationRentOccupancyPort:
    _by_machine: dict[MachineId, tuple[LocationRentOccupancy, ...]] = field(default_factory=dict)

    def set(self, machine_id: MachineId, occupancies: tuple[LocationRentOccupancy, ...]) -> None:
        self._by_machine[machine_id] = occupancies

    def list_for_machine(self, machine_id: MachineId) -> tuple[LocationRentOccupancy, ...]:
        return self._by_machine.get(machine_id, ())


class _RentAccountantCall(NamedTuple):
    period_id: str
    machine_id: MachineId
    opened_at: datetime
    closed_at: datetime
    next_retry_hours: int


@beartype
@dataclass(slots=True)
class RecordingRentAccountantAlerter:
    calls: list[_RentAccountantCall] = field(default_factory=list)

    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        next_retry_hours: int,
    ) -> None:
        self.calls.append(
            _RentAccountantCall(
                period_id=period_id,
                machine_id=machine_id,
                opened_at=opened_at,
                closed_at=closed_at,
                next_retry_hours=next_retry_hours,
            )
        )


@beartype
@dataclass(slots=True)
class NoOpRentAccountantAlerter:
    def notify(
        self,
        *,
        period_id: str,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
        next_retry_hours: int,
    ) -> None:
        return None
