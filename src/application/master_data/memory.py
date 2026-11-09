from __future__ import annotations

import threading
from dataclasses import dataclass, field

from beartype import beartype

from src.application.master_data.models import (
    MasterDataAuditRecord,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
    OpenPlacementExists,
)
from src.domain.ids import MachineId


@beartype
@dataclass(slots=True)
class InMemoryMasterLocationStore:
    _by_id: dict[str, MasterLocation] = field(default_factory=dict)

    def get(self, location_id: str) -> MasterLocation | None:
        return self._by_id.get(location_id)

    def upsert(self, location: MasterLocation) -> None:
        self._by_id[location.location_id] = location

    def delete(self, location_id: str) -> None:
        self._by_id.pop(location_id, None)

    def list_all(self) -> tuple[MasterLocation, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id


@beartype
@dataclass(slots=True)
class InMemoryMasterMachineStore:
    _by_id: dict[MachineId, MasterMachine] = field(default_factory=dict)

    def get(self, machine_id: MachineId) -> MasterMachine | None:
        return self._by_id.get(machine_id)

    def upsert(self, machine: MasterMachine) -> None:
        self._by_id[machine.machine_id] = machine

    def list_all(self) -> tuple[MasterMachine, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id


@beartype
@dataclass(slots=True)
class InMemoryMasterPlacementStore:
    _by_id: dict[str, MasterPlacement] = field(default_factory=dict)

    def insert(self, placement: MasterPlacement) -> None:
        if placement.valid_to is None and self.get_open(placement.machine_id) is not None:
            raise OpenPlacementExists(
                f"open placement already exists for machine {placement.machine_id.value!r}",
            )
        self._by_id[placement.placement_id] = placement

    def update(self, placement: MasterPlacement) -> None:
        self._by_id[placement.placement_id] = placement

    def get_open(self, machine_id: MachineId) -> MasterPlacement | None:
        for placement in self._by_id.values():
            if placement.machine_id == machine_id and placement.valid_to is None:
                return placement
        return None

    def list_for_machine(self, machine_id: MachineId) -> tuple[MasterPlacement, ...]:
        return tuple(p for p in self._by_id.values() if p.machine_id == machine_id)

    def list_all(self) -> tuple[MasterPlacement, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id


@beartype
@dataclass(slots=True)
class InMemoryMasterDataCounterStore:
    _values: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, name: str) -> int:
        with self._lock:
            return self._values.get(name, 0)

    def set(self, name: str, value: int) -> None:
        with self._lock:
            self._values[name] = value

    def allocate_next(self, name: str) -> int:
        with self._lock:
            next_value = self._values.get(name, 0) + 1
            self._values[name] = next_value
            return next_value


@beartype
@dataclass(slots=True)
class InMemoryMasterDataAuditStore:
    _records: list[MasterDataAuditRecord] = field(default_factory=list)

    def append(self, record: MasterDataAuditRecord) -> None:
        self._records.append(record)

    def list_all(self) -> tuple[MasterDataAuditRecord, ...]:
        return tuple(self._records)


@beartype
@dataclass(slots=True)
class InMemoryMasterDataStores:
    locations: InMemoryMasterLocationStore = field(default_factory=InMemoryMasterLocationStore)
    machines: InMemoryMasterMachineStore = field(default_factory=InMemoryMasterMachineStore)
    placements: InMemoryMasterPlacementStore = field(default_factory=InMemoryMasterPlacementStore)
    counters: InMemoryMasterDataCounterStore = field(default_factory=InMemoryMasterDataCounterStore)
    audit: InMemoryMasterDataAuditStore = field(default_factory=InMemoryMasterDataAuditStore)
