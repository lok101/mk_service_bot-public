from __future__ import annotations

from beartype import beartype

from src.application.inventory_reconciliation.period_errors import PeriodSnapshotNotReadyError
from src.application.inventory_reconciliation.ports import PeriodPartyNamesLookup
from src.domain.ids import MachineId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


@beartype
def resolve_frozen_party_names(
    lookup: PeriodPartyNamesLookup,
    *,
    machine_id: MachineId,
    technician_id: TechnicianId,
    period_id: str,
    existing: ResponsibilityPeriodReconciliation | None,
) -> tuple[str, str]:
    if existing is not None:
        preserved_loc = existing.location_name.strip()
        preserved_tech = existing.technician_name.strip()
        if preserved_loc and preserved_tech:
            return preserved_loc, preserved_tech

    location_name = (lookup.location_name(machine_id) or "").strip()
    technician_name = (lookup.technician_name(technician_id) or "").strip()
    missing: list[str] = []
    if not location_name:
        missing.append("location_name")
    if not technician_name:
        missing.append("technician_name")
    if missing:
        which = "+".join(missing)
        raise PeriodSnapshotNotReadyError(
            "party names not ready: "
            f"which={which}; period_id={period_id}; "
            f"machine_id={machine_id.value}; technician_id={technician_id.value}",
        )
    return location_name, technician_name
