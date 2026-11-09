from __future__ import annotations

import pytest

from src.application.sheets.bot_users import (
    build_system_users_snapshot,
    parse_bot_user_rows,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole


@pytest.fixture
def bot_user_rows() -> list[list[str]]:
    return [
        [
            "is active",
            "id",
            "Имя",
            "Роль",
            "Телеграм Id",
            "id техника",
        ],
        ["TRUE", "10001", "Александр", "Администратор", "7089874822", ""],
        ["TRUE", "10004", "Илья", "Техник", "111222333", "001"],
        ["FALSE", "10005", "Роман", "Техник", "444555666", "002"],
    ]


def test_parse_bot_user_rows_indexes_by_telegram_id(
    bot_user_rows: list[list[str]],
) -> None:
    users = parse_bot_user_rows(bot_user_rows)

    admin = users[7089874822]
    assert admin.name == "Александр"
    assert admin.role is BotRole.ADMINISTRATOR
    assert admin.is_active is True
    assert admin.technician_id is None

    technician = users[111222333]
    assert technician.role is BotRole.TECHNICIAN
    assert technician.technician_id == TechnicianId("001")

    inactive = users[444555666]
    assert inactive.is_active is False


def test_build_system_users_snapshot(bot_user_rows: list[list[str]]) -> None:
    snapshot = build_system_users_snapshot(bot_user_rows)

    assert len(snapshot.users_by_telegram_id) == 3


def test_parse_bot_user_rows_skips_rows_without_telegram_id() -> None:
    rows = [
        ["is active", "id", "Имя", "Роль", "Телеграм Id", "id техника"],
        ["TRUE", "10001", "Без Telegram", "Техник", "", "001"],
        ["TRUE", "10002", "С Telegram", "Техник", "12345", "002"],
    ]

    users = parse_bot_user_rows(rows)

    assert list(users) == [12345]


def test_parse_bot_user_rows_raises_on_duplicate_telegram_id() -> None:
    rows = [
        ["is active", "id", "Имя", "Роль", "Телеграм Id", "id техника"],
        ["TRUE", "10001", "Первый", "Техник", "12345", "001"],
        ["TRUE", "10002", "Второй", "Техник", "12345", "002"],
    ]

    with pytest.raises(ValueError, match="Duplicate Telegram id"):
        parse_bot_user_rows(rows)


def test_parse_bot_user_rows_raises_on_unknown_role() -> None:
    rows = [
        ["is active", "id", "Имя", "Роль", "Телеграм Id", "id техника"],
        ["TRUE", "10001", "Тест", "Менеджер", "12345", ""],
    ]

    with pytest.raises(ValueError, match="Unknown role"):
        parse_bot_user_rows(rows)
