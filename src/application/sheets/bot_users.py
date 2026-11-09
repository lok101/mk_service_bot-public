from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.shared.sheet_rows import (
    cell_value,
    is_active_cell,
    normalize_header_cells,
    row_has_values,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId

BOT_USER_ACTIVE_COLUMN = "is active"
BOT_USER_ACTIVE_FALLBACK_COLUMN = "activ"
BOT_USER_ID_COLUMN = "id"
BOT_USER_NAME_COLUMN = "имя"
BOT_USER_ROLE_COLUMN = "роль"
BOT_USER_TELEGRAM_ID_COLUMN = "телеграм id"
BOT_USER_TECHNICIAN_ID_COLUMN = "id техника"

ROLE_ADMINISTRATOR_LABEL = "администратор"
ROLE_TECHNICIAN_LABEL = "техник"


@beartype
@dataclass(frozen=True, slots=True)
class SystemUsersSnapshot:
    users_by_telegram_id: dict[int, SystemUser]
    users_by_technician_id: dict[TechnicianId, SystemUser]


@beartype
def build_system_users_snapshot(rows: list[list[str]]) -> SystemUsersSnapshot:
    users_by_telegram_id = parse_bot_user_rows(rows)
    users_by_technician_id: dict[TechnicianId, SystemUser] = {}
    for bot_user in users_by_telegram_id.values():
        if bot_user.technician_id is None:
            continue
        users_by_technician_id[bot_user.technician_id] = bot_user

    return SystemUsersSnapshot(
        users_by_telegram_id=users_by_telegram_id,
        users_by_technician_id=users_by_technician_id,
    )


@beartype
def parse_bot_user_rows(rows: list[list[str]]) -> dict[int, SystemUser]:
    if not rows:
        raise ValueError("Bot users sheet is empty")

    column_indexes = _find_bot_user_column_indexes(rows[0])
    users_by_telegram_id: dict[int, SystemUser] = {}

    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue

        user_code = cell_value(row, column_indexes.user_id)
        user_name = cell_value(row, column_indexes.name)
        role_label = cell_value(row, column_indexes.role)
        telegram_id_raw = cell_value(row, column_indexes.telegram_id)
        technician_code = cell_value(row, column_indexes.technician_id)

        if not user_code or not user_name or not role_label:
            continue

        if not telegram_id_raw:
            continue

        telegram_user_id = _parse_telegram_user_id(telegram_id_raw, row_number=row_number)
        role = _parse_bot_user_role(role_label, row_number=row_number)
        is_active = is_active_cell(cell_value(row, column_indexes.active))
        technician_id = TechnicianId(technician_code) if technician_code else None

        bot_user = SystemUser(
            user_id=SystemUserId(user_code),
            name=user_name,
            role=role,
            is_active=is_active,
            telegram_user_id=telegram_user_id,
            technician_id=technician_id,
            company_roles=frozenset(),
        )
        if telegram_user_id in users_by_telegram_id:
            raise ValueError(
                f"Duplicate Telegram id in bot users sheet at row {row_number}: {telegram_user_id}",
            )

        users_by_telegram_id[telegram_user_id] = bot_user

    if not users_by_telegram_id:
        raise ValueError("Bot users sheet has no rows with Telegram id")

    return users_by_telegram_id


@beartype
@dataclass(frozen=True, slots=True)
class _BotUserColumnIndexes:
    active: int
    user_id: int
    name: int
    role: int
    telegram_id: int
    technician_id: int


@beartype
def _find_bot_user_column_indexes(header_row: list[str]) -> _BotUserColumnIndexes:
    normalized_headers = normalize_header_cells(header_row)

    try:
        name_column_index = normalized_headers.index(BOT_USER_NAME_COLUMN)
        role_column_index = normalized_headers.index(BOT_USER_ROLE_COLUMN)
        telegram_id_column_index = normalized_headers.index(BOT_USER_TELEGRAM_ID_COLUMN)
        technician_id_column_index = normalized_headers.index(BOT_USER_TECHNICIAN_ID_COLUMN)
    except ValueError as error:
        raise ValueError(
            "Bot users sheet must contain Имя, Роль, Телеграм Id, and id техника columns",
        ) from error

    if BOT_USER_ID_COLUMN in normalized_headers:
        user_id_column_index = normalized_headers.index(BOT_USER_ID_COLUMN)
    else:
        user_id_column_index = 1

    if BOT_USER_ACTIVE_COLUMN in normalized_headers:
        active_column_index = normalized_headers.index(BOT_USER_ACTIVE_COLUMN)
    elif BOT_USER_ACTIVE_FALLBACK_COLUMN in normalized_headers:
        active_column_index = normalized_headers.index(BOT_USER_ACTIVE_FALLBACK_COLUMN)
    else:
        active_column_index = 0

    return _BotUserColumnIndexes(
        active=active_column_index,
        user_id=user_id_column_index,
        name=name_column_index,
        role=role_column_index,
        telegram_id=telegram_id_column_index,
        technician_id=technician_id_column_index,
    )


@beartype
def _parse_telegram_user_id(raw_value: str, *, row_number: int) -> int:
    normalized = raw_value.strip().replace(" ", "")
    if not normalized.isdigit():
        raise ValueError(
            f"Invalid Telegram id in bot users sheet at row {row_number}: {raw_value!r}",
        )

    return int(normalized)


@beartype
def _parse_bot_user_role(raw_value: str, *, row_number: int) -> BotRole:
    normalized = raw_value.strip().casefold()
    if normalized == ROLE_ADMINISTRATOR_LABEL:
        return BotRole.ADMINISTRATOR
    if normalized == ROLE_TECHNICIAN_LABEL:
        return BotRole.TECHNICIAN

    raise ValueError(
        f"Unknown role in bot users sheet at row {row_number}: {raw_value!r}",
    )
