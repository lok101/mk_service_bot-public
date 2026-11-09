from __future__ import annotations

import pytest

from src.application.reference_data.locations_merge import (
    assert_locations_kind_for_source,
    assert_locations_merge_compatible,
    filter_coffee_locations,
    merge_locations_catalog,
)
from src.application.reference_data.models import ReferenceDataSourceId
from src.application.sheets import (
    TechnicianLocationsSnapshot,
    list_all_machines_from_snapshot,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine


def _snap(
    machine_id: str,
    *,
    name: str = "Loc",
    tech_id: str = "T1",
    tech_name: str = "Tech",
) -> TechnicianLocationsSnapshot:
    technician_id = TechnicianId(tech_id)
    return TechnicianLocationsSnapshot(
        machines_by_technician_id={
            technician_id: (VendingMachine(id=MachineId(machine_id), name=name),),
        },
        technician_names_by_id={technician_id: tech_name},
    )


def test_merge_compatible_rejects_duplicate_machine_id() -> None:
    coffee = _snap("129", name="Cafe")
    other = _snap("129", name="Dup", tech_id="T2", tech_name="Other")
    with pytest.raises(ValueError, match="(?i)duplicate|collision"):
        assert_locations_merge_compatible(coffee, other)


def test_kind_rejects_snack_on_coffee() -> None:
    with pytest.raises(ValueError, match="(?i)snack"):
        assert_locations_kind_for_source(
            _snap("501"),
            ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        )


def test_kind_rejects_coffee_on_snack() -> None:
    with pytest.raises(ValueError, match="(?i)snack"):
        assert_locations_kind_for_source(
            _snap("129"),
            ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        )


def test_merge_locations_catalog_includes_micromarket() -> None:
    coffee = _snap("129", name="Cafe")
    snack = _snap("501", name="Snack", tech_id="T2", tech_name="SnackTech")
    micromarket = _snap("701", name="Fridge", tech_id="T3", tech_name="FridgeTech")
    merged = merge_locations_catalog(coffee, snack, micromarket)
    assert merged is not None
    ids = {m.id.value for m in list_all_machines_from_snapshot(merged)}
    assert ids == {"129", "501", "701"}


def test_merge_locations_catalog_none_micromarket_keeps_coffee_snack() -> None:
    coffee = _snap("129", name="Cafe")
    snack = _snap("501", name="Snack", tech_id="T2", tech_name="SnackTech")
    merged = merge_locations_catalog(coffee, snack, None)
    assert merged is not None
    ids = {m.id.value for m in list_all_machines_from_snapshot(merged)}
    assert ids == {"129", "501"}


def test_filter_locations_by_machine_ids_prunes_names() -> None:
    from src.application.reference_data.locations_merge import filter_locations_by_machine_ids

    catalog = TechnicianLocationsSnapshot(
        machines_by_technician_id={
            TechnicianId("T1"): (
                VendingMachine(id=MachineId("129"), name="Cafe"),
                VendingMachine(id=MachineId("701"), name="Fridge"),
            ),
            TechnicianId("T2"): (VendingMachine(id=MachineId("501"), name="Snack"),),
        },
        technician_names_by_id={
            TechnicianId("T1"): "CoffeeTech",
            TechnicianId("T2"): "SnackTech",
        },
        unassigned_machines=(),
    )
    filtered = filter_locations_by_machine_ids(catalog, frozenset({"129", "701"}))
    ids = {m.id.value for m in list_all_machines_from_snapshot(filtered)}
    assert ids == {"129", "701"}
    assert set(filtered.technician_names_by_id) == {TechnicianId("T1")}
    assert "501" not in ids


def test_filter_coffee_keeps_unassigned_coffee_drops_snack() -> None:
    coffee = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=(
            VendingMachine(id=MachineId("129"), name="Cafe"),
            VendingMachine(id=MachineId("501"), name="Snack"),
        ),
    )
    filtered = filter_coffee_locations(coffee)
    ids = {m.id.value for m in list_all_machines_from_snapshot(filtered)}
    assert ids == {"129"}
    assert [m.id.value for m in filtered.unassigned_machines] == ["129"]
