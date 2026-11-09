from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.machine_operations.ports import VendingMachineRepository
from src.application.visit_photo_review.ports import ReviewLabels
from src.domain.ids import MachineId, TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class VendingMachineReviewLabelLookup:
    """Resolve visit-photo admin labels from the live vending-machine repository."""

    machines: VendingMachineRepository

    @beartype
    def labels_for(self, machine_id: str, technician_id: str) -> ReviewLabels:
        machine = self.machines.get(MachineId(machine_id))
        # Fleet machine.name is the display label; list/carousel read machine_name,
        # history also shows location_name — same source fills both.
        display: str | None = None
        if machine is not None:
            stripped = machine.name.strip()
            display = stripped or None
        tech_raw = self.machines.find_technician_display_name(TechnicianId(technician_id))
        technician_name: str | None = None
        if tech_raw is not None:
            stripped_tech = tech_raw.strip()
            technician_name = stripped_tech or None
        return ReviewLabels(
            machine_name=display,
            location_name=display,
            technician_name=technician_name,
        )
