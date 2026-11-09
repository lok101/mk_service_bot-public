from __future__ import annotations

import inspect

import pytest

from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.machines.getters import machines_list_payload


def _technician() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("10029"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=100200300,
        technician_id=TechnicianId("029"),
        company_roles=frozenset(),
    )


def test_machines_list_payload_omits_warehouse_book_when_book_has_stock() -> None:
    # happy: list text never shows domain book block (ISS-429)
    payload = machines_list_payload(_technician(), options=[])
    text = str(payload["machines_screen_text"])
    assert "Склад (расчёт)" not in text
    assert "доменная расчётная книга" not in text
    assert "warehouse_book_block" not in inspect.signature(machines_list_payload).parameters


def test_machines_list_payload_omits_warehouse_book_when_empty() -> None:
    # edge: empty options still no book / disclaimer
    payload = machines_list_payload(_technician(), options=[])
    text = str(payload["machines_screen_text"])
    assert "📦 Склад" not in text
    assert "доменная расчётная книга" not in text


def test_format_warehouse_book_block_removed() -> None:
    # error/regression: dead formatter must not remain importable
    with pytest.raises(ImportError):
        from src.interfaces.telegram.machines.getters import (  # noqa: F401
            format_warehouse_book_block,
        )
