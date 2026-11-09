from __future__ import annotations

from src.application import inventory_reconciliation as ir
from src.application.inventory_reconciliation import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
    rebuild_company_occupancy,
)


def test_ir_public_surface_exports_company_occupancy() -> None:
    assert callable(rebuild_company_occupancy)
    assert MachineCompanyOccupancy.__name__ == "MachineCompanyOccupancy"
    assert MachineCompanyOccupancyStore.__name__ == "MachineCompanyOccupancyStore"


def test_current_company_helpers_exported() -> None:
    assert hasattr(ir, "open_company_id")
    assert hasattr(ir, "resolve_current_company_name")
    assert "open_company_id" in ir.__all__
    assert "resolve_current_company_name" in ir.__all__
