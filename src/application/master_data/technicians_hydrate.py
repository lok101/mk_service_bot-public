from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data.ports import TechnicianStore
from src.application.sheets import TechniciansDirectorySnapshot
from src.domain.ids import TechnicianId


@runtime_checkable
class TechniciansDirectorySnapshotSink(Protocol):
    def apply_technicians_directory_snapshot(
        self,
        snapshot: TechniciansDirectorySnapshot,
    ) -> None: ...


@beartype
def hydrate_technicians_directory(
    sink: TechniciansDirectorySnapshotSink,
    store: TechnicianStore,
) -> None:
    technicians = tuple(store.list_all())
    if not technicians:
        return
    names_by_id: dict[TechnicianId, str] = {
        technician.technician_id: technician.name for technician in technicians
    }
    sink.apply_technicians_directory_snapshot(
        TechniciansDirectorySnapshot(names_by_id=names_by_id),
    )
