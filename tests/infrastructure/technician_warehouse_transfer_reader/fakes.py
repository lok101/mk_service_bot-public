from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_API_BASE_URL
from src.infrastructure.integrations.moysklad.technician_warehouse_transfer_reader import (
    MoySkladTechnicianWarehouseTransferReader,
)

_FROM = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
_TO = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
_MAIN_STORE_ID = UUID("00000000-0000-0000-0000-000000000010")
_TECH_STORE_ID = UUID("00000000-0000-0000-0000-000000000011")
_MACHINE_STORE_ID = UUID("00000000-0000-0000-0000-000000000012")
_OTHER_TECH_STORE_ID = UUID("00000000-0000-0000-0000-000000000013")


def _store_meta_only(store_id: UUID) -> dict[str, object]:
    """Meta-only store ref (expand miss)."""
    return {"meta": {"href": f"{MOYSKLAD_API_BASE_URL}/entity/store/{store_id}"}}


def _store_expanded(
    store_id: UUID,
    *,
    code: str | None = None,
) -> dict[str, object]:
    """Expanded store object (keys beyond meta). ``code=None`` → нет ключа code."""
    store: dict[str, object] = {
        "meta": {"href": f"{MOYSKLAD_API_BASE_URL}/entity/store/{store_id}"},
        "id": str(store_id),
        "name": f"store-{store_id}",
    }
    if code is not None:
        store["code"] = code
    return store


def _move_row(
    move_id: str,
    *,
    source: dict[str, object] | None = None,
    target: dict[str, object] | None = None,
    source_id: UUID = _MAIN_STORE_ID,
    target_id: UUID = _TECH_STORE_ID,
    applicable: bool = True,
) -> dict[str, object]:
    return {
        "id": move_id,
        "moment": "2026-06-01 12:00:00.000",
        "updated": "2026-06-01 12:00:00.000",
        "applicable": applicable,
        "sourceStore": source if source is not None else _store_expanded(source_id, code="main"),
        "targetStore": target if target is not None else _store_expanded(target_id, code="tech-1"),
    }


def _reader(client: FakeMoySkladClient) -> MoySkladTechnicianWarehouseTransferReader:
    return MoySkladTechnicianWarehouseTransferReader(client=client)


def _client_with_supply_move() -> FakeMoySkladClient:
    client = FakeMoySkladClient(move_rows=[_move_row("move-1")])
    client.move_positions["move-1"] = [
        {"assortment": {"code": "coffee-rich", "name": "Coffee Rich"}, "quantity": 10},
    ]
    return client
