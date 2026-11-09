from __future__ import annotations


class MachinePnlError(Exception):
    """Base fail-closed error for machine PnL compute."""


class SnapshotNotFoundError(MachinePnlError):
    def __init__(self, period_id: str) -> None:
        self.period_id = period_id
        super().__init__(f"period snapshot not found: {period_id}")


class IncompleteSnapshotError(MachinePnlError):
    def __init__(self, period_id: str, *, status: str) -> None:
        self.period_id = period_id
        self.status = status
        super().__init__(f"period snapshot not complete: {period_id} (status={status})")


class SnackMachineError(MachinePnlError):
    def __init__(self, period_id: str, *, machine_id: str) -> None:
        self.period_id = period_id
        self.machine_id = machine_id
        super().__init__(f"snack machine not supported for PnL: {machine_id} ({period_id})")


class MissingUnitCostError(MachinePnlError):
    def __init__(self, *, product_code: str, as_of: str, period_id: str) -> None:
        self.product_code = product_code
        self.as_of = as_of
        self.period_id = period_id
        super().__init__(
            f"missing effective unit cost for {product_code} as_of={as_of} (period={period_id})"
        )


class AmbiguousResidualSessionError(MachinePnlError):
    def __init__(self, *, period_id: str, technician_id: str, count: int) -> None:
        self.period_id = period_id
        self.technician_id = technician_id
        self.count = count
        super().__init__(
            f"ambiguous residual sessions for period={period_id} "
            f"technician={technician_id}: count={count}"
        )


class UnitCostSheetError(MachinePnlError):
    """Fail-closed error for unit-cost sheet header/row parse."""


class GlobalOpExSheetError(MachinePnlError):
    """Fail-closed error for global OpEx sheet header/row parse."""


class LocationRentSheetError(MachinePnlError):
    """Fail-closed error for location rent sheet header/row parse."""


class RentTermsPending(MachinePnlError):
    """No known rent for intersecting occupancy slice(s); do not persist PeriodPnl."""

    def __init__(
        self,
        *,
        period_id: str | None = None,
        machine_id: str | None = None,
    ) -> None:
        self.period_id = period_id
        self.machine_id = machine_id
        parts: list[str] = ["rent terms pending"]
        if period_id is not None:
            parts.append(f"period={period_id}")
        if machine_id is not None:
            parts.append(f"machine={machine_id}")
        super().__init__(" ".join(parts))
