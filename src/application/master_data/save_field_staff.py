from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.master_data.ports import TechnicianStore
from src.application.master_data.system_users import (
    SaveSystemUsers,
    SystemUserDraft,
    SystemUsersInvalid,
)
from src.application.master_data.technicians import (
    CreateTechnician,
    TechnicianValidationError,
    UpdateTechnician,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import AdminPanel, BotRole, SystemUserId

_LOGGER = logging.getLogger(__name__)
_AUDIT_COMMAND = "save_field_staff"


class FieldStaffInvalid(Exception):
    @beartype
    def __init__(self, message: str) -> None:
        super().__init__(message)


@beartype
@dataclass(frozen=True, slots=True)
class FieldStaffRowDraft:
    telegram_user_id: int
    name: str
    bot_role: BotRole
    is_active: bool
    user_id: SystemUserId | None
    technician_is_active: bool
    linked_technician_id: TechnicianId | None


@beartype
@dataclass(slots=True)
class SaveFieldStaff:
    save_system_users: SaveSystemUsers
    create_technician: CreateTechnician | None
    update_technician: UpdateTechnician | None
    technician_store: TechnicianStore | None
    technicians_enabled: bool

    @beartype
    def execute(
        self,
        rows: tuple[FieldStaffRowDraft, ...],
        *,
        actor_telegram_user_id: int,
        actor_panels: frozenset[AdminPanel],
        now: datetime,
    ) -> None:
        if not self.technicians_enabled:
            raise FieldStaffInvalid("field staff requires MASTER_DATA_TECHNICIANS_ENABLED")
        if (
            self.create_technician is None
            or self.update_technician is None
            or self.technician_store is None
        ):
            raise FieldStaffInvalid("field staff requires technician stores")

        self._preflight_rows(rows)

        try:
            resolved_ids = self._resolve_technician_ids(
                rows,
                actor_telegram_user_id=actor_telegram_user_id,
                now=now,
            )
        except TechnicianValidationError as exc:
            raise FieldStaffInvalid(str(exc)) from exc

        existing_roles_by_tg = {
            record.user.telegram_user_id: record.user.company_roles
            for record in self.save_system_users.store.list_all()
        }
        drafts = tuple(
            SystemUserDraft(
                telegram_user_id=row.telegram_user_id,
                name=row.name,
                bot_role=row.bot_role,
                is_active=row.is_active,
                technician_id=resolved_ids[index],
                company_roles=existing_roles_by_tg.get(row.telegram_user_id, frozenset()),
                user_id=row.user_id,
            )
            for index, row in enumerate(rows)
        )
        directory_ids = frozenset(t.technician_id for t in self.technician_store.list_all())
        try:
            self.save_system_users.execute(
                drafts,
                directory_technician_ids=directory_ids,
                actor_telegram_user_id=actor_telegram_user_id,
                actor_panels=actor_panels,
                now=now,
            )
        except SystemUsersInvalid as exc:
            raise FieldStaffInvalid(str(exc)) from exc
        _LOGGER.info(
            "save_field_staff",
            extra={"actor": actor_telegram_user_id, "n": len(rows), "command": _AUDIT_COMMAND},
        )

    @beartype
    def _preflight_rows(self, rows: tuple[FieldStaffRowDraft, ...]) -> None:
        seen_telegram_ids: set[int] = set()
        for row in rows:
            if row.telegram_user_id in seen_telegram_ids:
                raise FieldStaffInvalid(f"duplicate telegram user id {row.telegram_user_id}")
            seen_telegram_ids.add(row.telegram_user_id)
            if not row.name.strip():
                raise FieldStaffInvalid("technician name must not be blank")

    @beartype
    def _resolve_technician_ids(
        self,
        rows: tuple[FieldStaffRowDraft, ...],
        *,
        actor_telegram_user_id: int,
        now: datetime,
    ) -> list[TechnicianId | None]:
        create = self.create_technician
        update = self.update_technician
        if create is None or update is None:
            raise FieldStaffInvalid("field staff requires technician stores")
        resolved: list[TechnicianId | None] = []
        for row in rows:
            if row.linked_technician_id is None:
                created = create.execute(
                    name=row.name,
                    actor_telegram_user_id=actor_telegram_user_id,
                    now=now,
                )
                tech_id = created.technician_id
                if not row.technician_is_active:
                    update.execute(
                        technician_id=tech_id,
                        name=None,
                        is_active=False,
                        actor_telegram_user_id=actor_telegram_user_id,
                        now=now,
                    )
                resolved.append(tech_id)
            else:
                update.execute(
                    technician_id=row.linked_technician_id,
                    name=row.name,
                    is_active=row.technician_is_active,
                    actor_telegram_user_id=actor_telegram_user_id,
                    now=now,
                )
                resolved.append(row.linked_technician_id)
        return resolved
