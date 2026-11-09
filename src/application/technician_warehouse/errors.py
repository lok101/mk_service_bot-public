from __future__ import annotations

from src.domain.technician_warehouse.errors import (
    FinalizedTransferChangedError,
    MoySkladUnavailable,
    TechnicianWarehouseConcurrencyError,
    WarehouseAlreadyClosed,
)

__all__ = [
    "CloseTechnicianWarehouseError",
    "FinalizedTransferChangedError",
    "MoySkladUnavailable",
    "SeedWarehouseBaselineError",
    "SeedWarehouseBaselinePartialWriteError",
    "TechnicianWarehouseConcurrencyError",
    "TechnicianWarehouseImportBlocked",
    "WarehouseAlreadyClosed",
]


class TechnicianWarehouseImportBlocked(Exception):
    """Raised when MS import cannot run due to missing configuration or data."""

    def __init__(
        self,
        message: str,
        *,
        technician_id: str | None = None,
        unregistered_products: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.technician_id = technician_id
        self.unregistered_products = unregistered_products
        super().__init__(message)


class CloseTechnicianWarehouseError(Exception):
    """Close warehouse gates failed; CLI maps to exit 1. message — human-readable."""


class SeedWarehouseBaselineError(Exception):
    """Seed validation failed; CLI maps to SystemExit. message — human-readable."""


class SeedWarehouseBaselinePartialWriteError(Exception):
    """Infra failed mid-write after validate-all succeeded."""

    def __init__(self, *, written_technician_ids: tuple[str, ...], cause: BaseException) -> None:
        self.written_technician_ids = written_technician_ids
        self.cause = cause
        super().__init__(
            f"seed partially written for technicians={written_technician_ids!r}: {cause}"
        )
