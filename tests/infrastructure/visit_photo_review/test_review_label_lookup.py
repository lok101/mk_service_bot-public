from __future__ import annotations

from src.application.visit_photo_review.ports import ReviewLabels
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.infrastructure.composition.adapters.visit_photo_review_labels import (
    VendingMachineReviewLabelLookup,
)


class _FixedMachines:
    def __init__(self) -> None:
        self._machines = {
            MachineId("m-1"): VendingMachine(id=MachineId("m-1"), name="Школа"),
        }
        self._tech_names = {TechnicianId("t-1"): "Иван"}

    def get(self, machine_id: MachineId) -> VendingMachine | None:
        return self._machines.get(machine_id)

    def find_technician_display_name(self, technician_id: TechnicianId) -> str | None:
        return self._tech_names.get(technician_id)

    def list_available_for_technician(self, technician_id: TechnicianId) -> list[VendingMachine]:
        return []

    def list_all(self) -> list[VendingMachine]:
        return list(self._machines.values())

    def find_technician_id_for_machine(self, machine_id: MachineId) -> TechnicianId | None:
        return None

    def find_technician_display_name_for_machine(self, machine_id: MachineId) -> str | None:
        return None


def test_vending_machine_review_label_lookup_resolves_names() -> None:
    # happy: list/carousel read machine_name; history also uses location_name
    lookup = VendingMachineReviewLabelLookup(machines=_FixedMachines())  # type: ignore[arg-type]
    labels = lookup.labels_for("m-1", "t-1")
    assert isinstance(labels, ReviewLabels)
    assert labels.machine_name == "Школа"
    assert labels.location_name == "Школа"
    assert labels.technician_name == "Иван"


def test_vending_machine_review_label_lookup_missing_ids() -> None:
    # edge
    lookup = VendingMachineReviewLabelLookup(machines=_FixedMachines())  # type: ignore[arg-type]
    labels = lookup.labels_for("unknown", "unknown")
    assert labels.machine_name is None
    assert labels.location_name is None
    assert labels.technician_name is None
