from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.master_data.models import (
    TECHNICIAN_COUNTER_KEY,
    MasterDataAuditRecord,
    allocate_technician_id,
)
from src.application.master_data.ports import (
    MasterDataAuditStore,
    MasterDataCounterStore,
    TechnicianStore,
)
from src.application.sheets import TechniciansDirectorySnapshot
from src.domain.ids import TechnicianId

_LOGGER = logging.getLogger(__name__)
_CREATE_AUDIT_COMMAND = "create_technician"
_UPDATE_AUDIT_COMMAND = "update_technician"


@beartype
@dataclass(frozen=True, slots=True)
class Technician:
    technician_id: TechnicianId
    name: str
    is_active: bool


class TechnicianValidationError(Exception):
    """Blank name / unknown id."""


@beartype
def max_numeric_technician_id(store: TechnicianStore) -> int:
    max_id = 0
    for technician in store.list_all():
        value = technician.technician_id.value
        if value.isdigit():
            max_id = max(max_id, int(value))
    return max_id


@beartype
def set_technician_counter_from_existing(
    store: TechnicianStore,
    counters: MasterDataCounterStore,
) -> None:
    counters.set(TECHNICIAN_COUNTER_KEY, max_numeric_technician_id(store))


@beartype
def _maybe_export(export_hook: Callable[[], None] | None) -> None:
    if export_hook is None:
        return
    try:
        export_hook()
    except Exception:
        _LOGGER.exception("technician sheets export failed; domain change kept")


@beartype
def _append_audit(
    audit: MasterDataAuditStore,
    *,
    at: datetime,
    actor_telegram_user_id: int,
    command: str,
    technician_id: TechnicianId,
) -> None:
    audit.append(
        MasterDataAuditRecord(
            at=at,
            actor_telegram_user_id=actor_telegram_user_id,
            command=command,
            payload={"technician_id": technician_id.value},
        )
    )


@beartype
def _require_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise TechnicianValidationError("technician name must not be blank")
    return stripped


@beartype
@dataclass(frozen=True, slots=True)
class ImportTechniciansResult:
    imported: int


@beartype
@dataclass(slots=True)
class ImportTechniciansFromSheets:
    store: TechnicianStore
    counters: MasterDataCounterStore

    @beartype
    def execute(self, snapshot: TechniciansDirectorySnapshot) -> ImportTechniciansResult:
        if not self.store.is_empty():
            return ImportTechniciansResult(imported=0)
        if not snapshot.names_by_id:
            raise TechnicianValidationError("technicians directory snapshot is empty")
        for technician_id, name in snapshot.names_by_id.items():
            self.store.upsert(
                Technician(
                    technician_id=technician_id,
                    name=_require_name(name),
                    is_active=True,
                ),
            )
        set_technician_counter_from_existing(self.store, self.counters)
        imported = len(snapshot.names_by_id)
        _LOGGER.info("import_technicians", extra={"imported": imported})
        return ImportTechniciansResult(imported=imported)


@beartype
@dataclass(slots=True)
class CreateTechnician:
    store: TechnicianStore
    counters: MasterDataCounterStore
    audit: MasterDataAuditStore
    export_hook: Callable[[], None] | None = None

    @beartype
    def execute(
        self,
        *,
        name: str,
        actor_telegram_user_id: int,
        now: datetime,
    ) -> Technician:
        stripped = _require_name(name)
        technician_id = TechnicianId(allocate_technician_id(self.counters))
        technician = Technician(
            technician_id=technician_id,
            name=stripped,
            is_active=True,
        )
        self.store.upsert(technician)
        _append_audit(
            self.audit,
            at=now,
            actor_telegram_user_id=actor_telegram_user_id,
            command=_CREATE_AUDIT_COMMAND,
            technician_id=technician_id,
        )
        _LOGGER.info("create_technician", extra={"technician_id": technician_id.value})
        _maybe_export(self.export_hook)
        return technician


@beartype
@dataclass(slots=True)
class UpdateTechnician:
    store: TechnicianStore
    audit: MasterDataAuditStore
    export_hook: Callable[[], None] | None = None

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        name: str | None,
        is_active: bool | None,
        actor_telegram_user_id: int,
        now: datetime,
    ) -> Technician:
        if name is None and is_active is None:
            raise TechnicianValidationError("update requires name or is_active")
        existing = self.store.get(technician_id)
        if existing is None:
            raise TechnicianValidationError(f"unknown technician {technician_id.value!r}")
        new_name = existing.name if name is None else _require_name(name)
        new_active = existing.is_active if is_active is None else is_active
        technician = Technician(
            technician_id=technician_id,
            name=new_name,
            is_active=new_active,
        )
        self.store.upsert(technician)
        _append_audit(
            self.audit,
            at=now,
            actor_telegram_user_id=actor_telegram_user_id,
            command=_UPDATE_AUDIT_COMMAND,
            technician_id=technician_id,
        )
        _log_update(existing, technician)
        _maybe_export(self.export_hook)
        return technician


@beartype
def _log_update(before: Technician, after: Technician) -> None:
    extra = {"technician_id": after.technician_id.value}
    if before.name != after.name:
        _LOGGER.info("rename_technician", extra=extra)
    if before.is_active and not after.is_active:
        _LOGGER.info("deactivate_technician", extra=extra)
    elif not before.is_active and after.is_active:
        _LOGGER.info("reactivate_technician", extra=extra)
