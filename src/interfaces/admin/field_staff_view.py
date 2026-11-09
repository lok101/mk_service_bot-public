from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data import SystemUserStore, TechnicianStore
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole
from src.interfaces.admin.technicians_view import TechnicianListStatus, parse_technician_list_status

__all__ = [
    "FieldStaffPageView",
    "FieldStaffRowView",
    "build_field_staff_page_view",
    "parse_technician_list_status",
]


@beartype
@dataclass(frozen=True, slots=True)
class _LinkedSystemUser:
    telegram_user_id: int
    bot_role: str
    user_is_active: bool
    user_id: str


@beartype
@dataclass(frozen=True, slots=True)
class FieldStaffRowView:
    technician_id: str
    name: str
    telegram_user_id: int
    bot_role: str
    technician_is_active: bool
    user_is_active: bool
    user_id: str | None


@beartype
@dataclass(frozen=True, slots=True)
class FieldStaffPageView:
    rows: tuple[FieldStaffRowView, ...]
    status: TechnicianListStatus
    bot_roles: tuple[tuple[str, str], ...]


@beartype
def build_field_staff_page_view(
    technician_store: TechnicianStore,
    system_user_store: SystemUserStore,
    *,
    status: TechnicianListStatus,
) -> FieldStaffPageView:
    users_by_technician: dict[TechnicianId, _LinkedSystemUser] = {}
    for record in system_user_store.list_all():
        linked_technician_id = record.user.technician_id
        if linked_technician_id is None:
            continue
        users_by_technician[linked_technician_id] = _LinkedSystemUser(
            telegram_user_id=record.user.telegram_user_id,
            bot_role=record.user.role.value,
            user_is_active=record.user.is_active,
            user_id=record.user.user_id.value,
        )
    rows: list[FieldStaffRowView] = []
    for technician in sorted(
        technician_store.list_all(),
        key=lambda item: item.technician_id.value,
    ):
        if not _matches_status(technician.is_active, status):
            continue
        linked_user = users_by_technician.get(technician.technician_id)
        if linked_user is None:
            rows.append(
                FieldStaffRowView(
                    technician_id=technician.technician_id.value,
                    name=technician.name,
                    telegram_user_id=0,
                    bot_role=BotRole.TECHNICIAN.value,
                    technician_is_active=technician.is_active,
                    user_is_active=False,
                    user_id=None,
                ),
            )
            continue
        rows.append(
            FieldStaffRowView(
                technician_id=technician.technician_id.value,
                name=technician.name,
                telegram_user_id=linked_user.telegram_user_id,
                bot_role=linked_user.bot_role,
                technician_is_active=technician.is_active,
                user_is_active=linked_user.user_is_active,
                user_id=linked_user.user_id,
            ),
        )
    bot_roles = tuple((role.value, role.label_ru) for role in BotRole)
    return FieldStaffPageView(rows=tuple(rows), status=status, bot_roles=bot_roles)


@beartype
def _matches_status(is_active: bool, status: TechnicianListStatus) -> bool:
    if status == "all":
        return True
    if status == "active":
        return is_active
    return not is_active
