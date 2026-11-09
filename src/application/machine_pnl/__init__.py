from __future__ import annotations

from src.application.inventory_reconciliation import PeriodReconciliationNotFound
from src.application.machine_pnl.compute_month_pnl_snapshot import ComputeMonthPnlSnapshot
from src.application.machine_pnl.compute_period_pnl import ComputePeriodPnl
from src.application.machine_pnl.enqueue import enqueue_machine_period_pnl_jobs
from src.application.machine_pnl.errors import (
    AmbiguousResidualSessionError,
    IncompleteSnapshotError,
    MissingUnitCostError,
    RentTermsPending,
    SnackMachineError,
    SnapshotNotFoundError,
)
from src.application.machine_pnl.models import PeriodPnl, PnlWarning, make_pnl_id
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.opex import OpExComputation, compute_opex, period_days
from src.application.machine_pnl.opex_params import (
    EffectiveOpExParams,
    FixtureOpExParamsCatalog,
    OpExParamsPort,
)
from src.application.machine_pnl.opex_ports import ServiceFactCounter, ZeroMaintenanceAlerter
from src.application.machine_pnl.ports import as_period_snapshot_reader
from src.application.machine_pnl.rent_ports import (
    FixtureLocationRentCatalog,
    LocationRentOccupancyPort,
    RentAccountantAlerter,
)
from src.application.machine_pnl.residual_ports import ResidualSessionReader, ResidualSessionView

__all__ = [
    "AmbiguousResidualSessionError",
    "ComputeMonthPnlSnapshot",
    "ComputePeriodPnl",
    "EffectiveOpExParams",
    "FixtureLocationRentCatalog",
    "FixtureOpExParamsCatalog",
    "IncompleteSnapshotError",
    "LocationRentOccupancyPort",
    "MissingUnitCostError",
    "MonthPnlSnapshot",
    "OpExComputation",
    "OpExParamsPort",
    "PeriodPnl",
    "PeriodReconciliationNotFound",
    "PnlWarning",
    "RentAccountantAlerter",
    "RentTermsPending",
    "ResidualSessionReader",
    "ResidualSessionView",
    "ServiceFactCounter",
    "SnackMachineError",
    "SnapshotNotFoundError",
    "ZeroMaintenanceAlerter",
    "as_period_snapshot_reader",
    "compute_opex",
    "enqueue_machine_period_pnl_jobs",
    "make_pnl_id",
    "period_days",
]
