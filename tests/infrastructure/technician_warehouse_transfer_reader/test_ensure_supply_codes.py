from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.application.technician_warehouse.errors import TechnicianWarehouseImportBlocked
from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladError,
    MoySkladValidationError,
)

from .fakes import (
    _MAIN_STORE_ID,
    _reader,
)


def test_ensure_supply_store_codes_exist_ok_when_all_found() -> None:
    """happy: все codes существуют → без raise."""
    client = FakeMoySkladClient(
        store_ids_by_code={
            "main": _MAIN_STORE_ID,
            "supply": UUID("00000000-0000-0000-0000-000000000099"),
        },
    )
    asyncio.run(
        _reader(client).ensure_supply_store_codes_exist(("main", "supply")),
    )
    assert client.get_store_id_by_code_calls == ["main", "supply"]


def test_ensure_supply_store_codes_fail_fast_on_first_missing() -> None:
    """edge/error: fail-fast на первом отсутствующем; последующие не вызываются."""
    client = FakeMoySkladClient(
        store_ids_by_code={"main": _MAIN_STORE_ID},
        store_id_by_code_errors={
            "missing-a": MoySkladValidationError("Склад с кодом 'missing-a' не найден."),
        },
    )
    with pytest.raises(TechnicianWarehouseImportBlocked, match="missing-a"):
        asyncio.run(
            _reader(client).ensure_supply_store_codes_exist(
                ("main", "missing-a", "missing-b"),
            ),
        )
    assert client.get_store_id_by_code_calls == ["main", "missing-a"]


def test_ensure_supply_store_codes_propagates_moysklad_unavailable() -> None:
    """error: сетевой/HTTP сбой → MoySkladUnavailable."""
    client = FakeMoySkladClient(
        store_id_by_code_errors={"main": MoySkladError("connection reset")},
    )
    with pytest.raises(MoySkladUnavailable, match="connection reset"):
        asyncio.run(_reader(client).ensure_supply_store_codes_exist(("main",)))
