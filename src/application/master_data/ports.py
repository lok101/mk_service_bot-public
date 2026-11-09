from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data.companies import MasterCompany
from src.domain.ids import MachineId, TechnicianId

if TYPE_CHECKING:
    from src.application.master_data.models import (
        MasterDataAuditRecord,
        MasterLocation,
        MasterMachine,
        MasterPlacement,
    )
    from src.application.master_data.system_users import (
        SystemUserAuditRecord,
        SystemUserRecord,
    )
    from src.application.master_data.technicians import Technician


@runtime_checkable
class MasterLocationStore(Protocol):
    @beartype
    def get(self, location_id: str) -> MasterLocation | None: ...

    @beartype
    def upsert(self, location: MasterLocation) -> None: ...

    @beartype
    def delete(self, location_id: str) -> None: ...

    @beartype
    def list_all(self) -> tuple[MasterLocation, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...


@runtime_checkable
class MasterMachineStore(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> MasterMachine | None: ...

    @beartype
    def upsert(self, machine: MasterMachine) -> None: ...

    @beartype
    def list_all(self) -> tuple[MasterMachine, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...


@runtime_checkable
class MasterPlacementStore(Protocol):
    @beartype
    def insert(self, placement: MasterPlacement) -> None: ...

    @beartype
    def update(self, placement: MasterPlacement) -> None: ...

    @beartype
    def get_open(self, machine_id: MachineId) -> MasterPlacement | None: ...

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[MasterPlacement, ...]: ...

    @beartype
    def list_all(self) -> tuple[MasterPlacement, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...


@runtime_checkable
class SystemUserStore(Protocol):
    @beartype
    def get(self, telegram_user_id: int) -> SystemUserRecord | None: ...

    @beartype
    def list_all(self) -> tuple[SystemUserRecord, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...

    @beartype
    def replace_all(self, records: tuple[SystemUserRecord, ...]) -> None: ...

    @beartype
    def save_batch(
        self,
        records: tuple[SystemUserRecord, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
        audit_command: str,
    ) -> None: ...

    @beartype
    def list_audit(self) -> tuple[SystemUserAuditRecord, ...]: ...


@runtime_checkable
class TechnicianStore(Protocol):
    @beartype
    def get(self, technician_id: TechnicianId) -> Technician | None: ...

    @beartype
    def upsert(self, technician: Technician) -> None: ...

    @beartype
    def list_all(self) -> tuple[Technician, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...


@runtime_checkable
class CompanyStore(Protocol):
    @beartype
    def get(self, company_id: int) -> MasterCompany | None: ...

    @beartype
    def upsert(self, company: MasterCompany) -> None: ...

    @beartype
    def list_all(self) -> tuple[MasterCompany, ...]: ...

    @beartype
    def is_empty(self) -> bool: ...


@runtime_checkable
class MasterDataCounterStore(Protocol):
    @beartype
    def get(self, name: str) -> int: ...

    @beartype
    def set(self, name: str, value: int) -> None: ...

    @beartype
    def allocate_next(self, name: str) -> int: ...


@runtime_checkable
class MasterDataAuditStore(Protocol):
    @beartype
    def append(self, record: MasterDataAuditRecord) -> None: ...

    @beartype
    def list_all(self) -> tuple[MasterDataAuditRecord, ...]: ...


@runtime_checkable
class MasterDataStores(Protocol):
    @property
    def locations(self) -> MasterLocationStore: ...

    @property
    def machines(self) -> MasterMachineStore: ...

    @property
    def placements(self) -> MasterPlacementStore: ...

    @property
    def counters(self) -> MasterDataCounterStore: ...

    @property
    def audit(self) -> MasterDataAuditStore: ...
