from __future__ import annotations

from src.application.reference_data import ReferenceDataProvider
from src.application.sheets.technician_locations import TechnicianLocationsSnapshot
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.infrastructure.service_visits_worker.cron_tick import (
    catalog_from_locations_snapshot,
    tick_inputs_from_provider,
)


def _machine_snap(
    machine_id: str,
    *,
    name: str,
    tech_id: str | None = None,
    tech_name: str | None = None,
    weekdays: frozenset[int] = frozenset(),
) -> TechnicianLocationsSnapshot:
    machine = VendingMachine(
        id=MachineId(machine_id),
        name=name,
        service_weekdays=weekdays,
    )
    if tech_id is None:
        return TechnicianLocationsSnapshot(
            machines_by_technician_id={},
            technician_names_by_id={},
            unassigned_machines=(machine,),
        )
    technician_id = TechnicianId(tech_id)
    return TechnicianLocationsSnapshot(
        machines_by_technician_id={technician_id: (machine,)},
        technician_names_by_id={technician_id: tech_name or tech_id},
        unassigned_machines=(),
    )


def test_tick_inputs_unavailable_returns_empty_catalog() -> None:
    # edge: no snapshots yet → empty inputs, do not raise (worker stays up)
    catalog, unassigned = tick_inputs_from_provider(ReferenceDataProvider())
    assert catalog == ()
    assert unassigned == ()


def test_tick_inputs_from_provider_includes_assigned_micromarket() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap(
            "129", name="Cafe", tech_id="T1", tech_name="Tech", weekdays=frozenset({2})
        ),
        snack=None,
        micromarket=_machine_snap(
            "701", name="Fridge", tech_id="T1", tech_name="Tech", weekdays=frozenset({1})
        ),
        locations_directory=None,
    )
    catalog, unassigned = tick_inputs_from_provider(provider)
    by_id = {item.machine_id: item.service_weekdays for item in catalog}
    assert by_id[MachineId("701")] == frozenset({1})
    assert by_id[MachineId("129")] == frozenset({2})
    assert MachineId("701") not in unassigned


def test_tick_inputs_from_provider_unassigned_micromarket_for_cancel() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap(
            "129", name="Cafe", tech_id="T1", tech_name="Tech", weekdays=frozenset({2})
        ),
        snack=_machine_snap(
            "501", name="Snack", tech_id="T1", tech_name="Tech", weekdays=frozenset({3})
        ),
        micromarket=_machine_snap("701", name="Fridge", weekdays=frozenset({1})),
        locations_directory=None,
    )
    catalog, unassigned = tick_inputs_from_provider(provider)
    catalog_ids = {item.machine_id for item in catalog}
    assert MachineId("701") not in catalog_ids
    assert MachineId("701") in unassigned
    assert MachineId("501") not in catalog_ids
    assert MachineId("501") not in unassigned


def test_tick_inputs_from_provider_excludes_snack() -> None:
    provider = ReferenceDataProvider()
    provider.apply_master_snapshots(
        coffee=_machine_snap(
            "129", name="Cafe", tech_id="T1", tech_name="Tech", weekdays=frozenset({2})
        ),
        snack=_machine_snap(
            "501", name="Snack", tech_id="T1", tech_name="Tech", weekdays=frozenset({1})
        ),
        micromarket=_machine_snap(
            "701", name="Fridge", tech_id="T1", tech_name="Tech", weekdays=frozenset({1})
        ),
        locations_directory=None,
    )
    catalog, unassigned = tick_inputs_from_provider(provider)
    catalog_ids = {item.machine_id for item in catalog}
    assert MachineId("501") not in catalog_ids
    assert MachineId("501") not in unassigned
    assert MachineId("701") in catalog_ids


def test_catalog_excludes_unassigned_machines() -> None:
    # edge: unassigned с непустыми weekdays не попадает в materialize-каталог
    snapshot = TechnicianLocationsSnapshot(
        machines_by_technician_id={},
        technician_names_by_id={},
        unassigned_machines=(
            VendingMachine(
                id=MachineId("201"),
                name="Orphan",
                service_weekdays=frozenset({2, 4}),
            ),
        ),
    )
    catalog = catalog_from_locations_snapshot(snapshot)
    assert catalog == ()


def test_catalog_includes_assigned_machines() -> None:
    # happy: закреплённая машина с weekdays в каталоге
    machine = VendingMachine(
        id=MachineId("101"),
        name="Cafe",
        service_weekdays=frozenset({2}),
    )
    snapshot = TechnicianLocationsSnapshot(
        machines_by_technician_id={TechnicianId("001"): (machine,)},
        technician_names_by_id={TechnicianId("001"): "Ivan"},
        unassigned_machines=(
            VendingMachine(
                id=MachineId("201"),
                name="Orphan",
                service_weekdays=frozenset({2}),
            ),
        ),
    )
    catalog = catalog_from_locations_snapshot(snapshot)
    assert len(catalog) == 1
    assert catalog[0].machine_id == MachineId("101")
    assert catalog[0].service_weekdays == frozenset({2})
