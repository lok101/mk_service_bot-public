from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId

DutyMode = Literal["patent", "tax"]


@beartype
@dataclass(frozen=True, slots=True)
class EffectiveOpExParams:
    rent_monthly: Decimal | None
    rent_percent: Decimal | None
    duty_mode: DutyMode
    patent_monthly: Decimal | None
    tax_percent: Decimal | None
    acquiring_percent: Decimal | None
    acquiring_fee_per_sale: Decimal | None
    terminal_monthly: Decimal | None
    labor_rate: Decimal | None
    params_incomplete: bool
    missing_labor_rate: bool


@runtime_checkable
class OpExParamsPort(Protocol):
    @beartype
    def resolve(self, machine_id: MachineId, *, as_of: date) -> EffectiveOpExParams: ...


@beartype
@dataclass(frozen=True, slots=True)
class FixtureMachineOpExRow:
    machine_id: MachineId
    valid_from: date
    rent_monthly: Decimal | None
    rent_percent: Decimal | None
    duty_mode: DutyMode
    patent_monthly: Decimal | None
    tax_percent: Decimal | None
    acquiring_percent: Decimal | None
    acquiring_fee_per_sale: Decimal | None
    terminal_monthly: Decimal | None


@beartype
@dataclass(frozen=True, slots=True)
class FixtureRateRow:
    valid_from: date
    amount: Decimal


def _latest_rate(rows: tuple[FixtureRateRow, ...], *, as_of: date) -> FixtureRateRow | None:
    eligible = [row for row in rows if row.valid_from <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row.valid_from)


def _latest_machine(
    rows: tuple[FixtureMachineOpExRow, ...],
    *,
    as_of: date,
) -> FixtureMachineOpExRow | None:
    eligible = [row for row in rows if row.valid_from <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row.valid_from)


@beartype
@dataclass(frozen=True, slots=True)
class FixtureOpExParamsCatalog:
    machine_rows: tuple[FixtureMachineOpExRow, ...] = ()
    labor_global_rows: tuple[FixtureRateRow, ...] = ()
    terminal_global_rows: tuple[FixtureRateRow, ...] = ()

    @classmethod
    def default(cls) -> FixtureOpExParamsCatalog:
        return cls()

    @beartype
    def resolve(self, machine_id: MachineId, *, as_of: date) -> EffectiveOpExParams:
        machine_candidates = tuple(row for row in self.machine_rows if row.machine_id == machine_id)
        machine = _latest_machine(machine_candidates, as_of=as_of)

        labor_global = _latest_rate(self.labor_global_rows, as_of=as_of)
        if labor_global is not None:
            labor_rate: Decimal | None = labor_global.amount
            missing_labor_rate = False
        else:
            labor_rate = None
            missing_labor_rate = True

        terminal_global = _latest_rate(self.terminal_global_rows, as_of=as_of)

        if machine is None:
            return EffectiveOpExParams(
                rent_monthly=None,
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=None,
                tax_percent=None,
                acquiring_percent=None,
                acquiring_fee_per_sale=None,
                terminal_monthly=terminal_global.amount if terminal_global is not None else None,
                labor_rate=labor_rate,
                params_incomplete=False,
                missing_labor_rate=missing_labor_rate,
            )

        terminal_monthly = machine.terminal_monthly
        if terminal_monthly is None and terminal_global is not None:
            terminal_monthly = terminal_global.amount

        rent_missing = machine.rent_monthly is None
        return EffectiveOpExParams(
            rent_monthly=machine.rent_monthly,
            rent_percent=machine.rent_percent,
            duty_mode=machine.duty_mode,
            patent_monthly=machine.patent_monthly,
            tax_percent=machine.tax_percent,
            acquiring_percent=machine.acquiring_percent,
            acquiring_fee_per_sale=machine.acquiring_fee_per_sale,
            terminal_monthly=terminal_monthly,
            labor_rate=labor_rate,
            params_incomplete=rent_missing,
            missing_labor_rate=missing_labor_rate,
        )
