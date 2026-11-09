from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data.ports import SystemUserStore
from src.application.sheets import SystemUsersSnapshot
from src.domain.ids import TechnicianId
from src.domain.system_user import SystemUser

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class SystemUsersSnapshotSink(Protocol):
    def apply_system_users_snapshot(self, snapshot: SystemUsersSnapshot) -> None: ...


@beartype
def hydrate_provider_from_system_users(
    sink: SystemUsersSnapshotSink,
    store: SystemUserStore,
) -> None:
    records = store.list_all()
    users_by_telegram_id: dict[int, SystemUser] = {
        record.user.telegram_user_id: record.user for record in records
    }
    owner_by_technician: dict[TechnicianId, int] = {}
    for record in records:
        tech_id = record.user.technician_id
        if tech_id is None:
            continue
        prev = owner_by_technician.get(tech_id)
        if prev is not None and prev != record.user.telegram_user_id:
            _LOGGER.warning(
                "system_users_duplicate_technician_id",
                extra={
                    "technician_id": tech_id.value,
                    "telegram_user_id": record.user.telegram_user_id,
                    "other_telegram_user_id": prev,
                },
            )
        owner_by_technician[tech_id] = record.user.telegram_user_id
    users_by_technician_id: dict[TechnicianId, SystemUser] = {
        record.user.technician_id: record.user
        for record in records
        if record.user.technician_id is not None
    }
    sink.apply_system_users_snapshot(
        SystemUsersSnapshot(
            users_by_telegram_id=users_by_telegram_id,
            users_by_technician_id=users_by_technician_id,
        ),
    )
