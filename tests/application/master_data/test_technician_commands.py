from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    CreateTechnician,
    InMemoryTechnicianStore,
    Technician,
    TechnicianValidationError,
    UpdateTechnician,
    set_technician_counter_from_existing,
)
from src.application.master_data.memory import (
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
)
from src.application.master_data.models import TECHNICIAN_COUNTER_KEY
from src.domain.ids import TechnicianId

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
_ACTOR = 1


def test_create_technician_allocates_numeric_id() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    uc = CreateTechnician(store=store, counters=counters, audit=audit)
    tech = uc.execute(name="  Данил  ", actor_telegram_user_id=_ACTOR, now=_NOW)
    assert tech.technician_id.value == "1"
    assert tech.name == "Данил"
    assert tech.is_active is True
    assert store.get(tech.technician_id) == tech


def test_create_rejects_blank_name() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    uc = CreateTechnician(store=store, counters=counters, audit=audit)
    with pytest.raises(TechnicianValidationError):
        uc.execute(name="  ", actor_telegram_user_id=_ACTOR, now=_NOW)


def test_allocate_skips_non_numeric_legacy() -> None:
    store = InMemoryTechnicianStore()
    store.upsert(Technician(TechnicianId("abc"), "Legacy", True))
    store.upsert(Technician(TechnicianId("10017"), "Egor", True))
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    set_technician_counter_from_existing(store, counters)
    uc = CreateTechnician(store=store, counters=counters, audit=audit)
    tech = uc.execute(name="New", actor_telegram_user_id=_ACTOR, now=_NOW)
    assert tech.technician_id.value == "10018"


def test_create_after_import_uses_max_plus_one() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    counters.set(TECHNICIAN_COUNTER_KEY, 10017)
    audit = InMemoryMasterDataAuditStore()
    uc = CreateTechnician(store=store, counters=counters, audit=audit)
    tech = uc.execute(name="New", actor_telegram_user_id=_ACTOR, now=_NOW)
    assert tech.technician_id.value == "10018"


def test_deactivate_sets_inactive() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="Данил",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    UpdateTechnician(store=store, audit=audit).execute(
        technician_id=created.technician_id,
        name=None,
        is_active=False,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    stored = store.get(created.technician_id)
    assert stored is not None
    assert stored.is_active is False
    assert stored.name == "Данил"


def test_rename_keeps_active() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="Данил",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    UpdateTechnician(store=store, audit=audit).execute(
        technician_id=created.technician_id,
        name="Данил К.",
        is_active=None,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    stored = store.get(created.technician_id)
    assert stored is not None
    assert stored.name == "Данил К."
    assert stored.is_active is True


def test_reactivate() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="Данил",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    update = UpdateTechnician(store=store, audit=audit)
    update.execute(
        technician_id=created.technician_id,
        name=None,
        is_active=False,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    update.execute(
        technician_id=created.technician_id,
        name=None,
        is_active=True,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    stored = store.get(created.technician_id)
    assert stored is not None
    assert stored.is_active is True


def test_update_unknown_rejects() -> None:
    store = InMemoryTechnicianStore()
    audit = InMemoryMasterDataAuditStore()
    with pytest.raises(TechnicianValidationError):
        UpdateTechnician(store=store, audit=audit).execute(
            technician_id=TechnicianId("missing"),
            name="x",
            is_active=None,
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_writes_audit() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    tech = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="Данил",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    records = audit.list_all()
    assert records[-1].command == "create_technician"
    assert records[-1].payload["technician_id"] == tech.technician_id.value
    assert records[-1].actor_telegram_user_id == _ACTOR


def test_update_writes_audit() -> None:
    store = InMemoryTechnicianStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateTechnician(store=store, counters=counters, audit=audit).execute(
        name="Данил",
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    UpdateTechnician(store=store, audit=audit).execute(
        technician_id=created.technician_id,
        name=None,
        is_active=False,
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    records = audit.list_all()
    assert records[-1].command == "update_technician"
    assert records[-1].payload["technician_id"] == created.technician_id.value
    assert records[-1].actor_telegram_user_id == _ACTOR
