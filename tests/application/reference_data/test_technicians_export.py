from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import (
    CreateTechnician,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    InMemoryTechnicianStore,
    Technician,
)
from src.application.reference_data.master_data_export import (
    TECHNICIANS_EXPORT_HEADER,
    build_technicians_directory_export_rows,
)
from src.domain.ids import TechnicianId

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_ACTOR = 1


def test_export_technician_rows_shape() -> None:
    store = InMemoryTechnicianStore()
    store.upsert(
        Technician(
            technician_id=TechnicianId("10003"),
            name="Данил",
            is_active=True,
        )
    )
    store.upsert(
        Technician(
            technician_id=TechnicianId("10002"),
            name="Inactive",
            is_active=False,
        )
    )
    rows = build_technicians_directory_export_rows(store)
    assert rows[0] == TECHNICIANS_EXPORT_HEADER
    assert rows[0] == ["Id", "Имя"]
    assert ["10003", "Данил"] in rows
    assert ["10002", "Inactive"] in rows


def test_export_failure_keeps_technician() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()

    def boom() -> None:
        raise RuntimeError("sheets down")

    uc = CreateTechnician(
        store=store,
        counters=counters,
        audit=audit,
        export_hook=boom,
    )
    tech = uc.execute(name="X", actor_telegram_user_id=_ACTOR, now=_NOW)
    assert store.get(tech.technician_id) is not None
