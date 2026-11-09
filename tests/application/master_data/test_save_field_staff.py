from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    CreateTechnician,
    FieldStaffInvalid,
    FieldStaffRowDraft,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
    SaveFieldStaff,
    SaveSystemUsers,
    SystemUserRecord,
    Technician,
    UpdateTechnician,
)
from src.application.master_data.memory import (
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
)
from src.domain.ids import TechnicianId
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
    permission_panels,
)

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
_ACTOR = 1


def test_save_field_staff_module_exports() -> None:
    from src.application.master_data import (
        FieldStaffInvalid,
        FieldStaffRowDraft,
        SaveFieldStaff,
    )

    assert SaveFieldStaff is not None
    assert FieldStaffRowDraft is not None
    assert FieldStaffInvalid is not None


def _all_panels() -> frozenset[AdminPanel]:
    return frozenset(permission_panels())


def _seed_users_admin(store: InMemorySystemUserStore) -> None:
    user = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ACTOR,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    store.replace_all(
        (
            SystemUserRecord(
                user=user,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ACTOR,
            ),
        ),
    )


def _build_save_field_staff(
    *,
    user_store: InMemorySystemUserStore,
    tech_store: InMemoryTechnicianStore,
    technicians_enabled: bool = True,
) -> SaveFieldStaff:
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    create = CreateTechnician(store=tech_store, counters=counters, audit=audit)
    update = UpdateTechnician(store=tech_store, audit=audit)
    return SaveFieldStaff(
        save_system_users=SaveSystemUsers(store=user_store, counters=counters),
        create_technician=create,
        update_technician=update,
        technician_store=tech_store,
        technicians_enabled=technicians_enabled,
    )


def test_save_field_staff_creates_pair_with_empty_panels() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    _seed_users_admin(user_store)
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Данил",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=None,
                technician_is_active=True,
                linked_technician_id=None,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    techs = tech_store.list_all()
    assert len(techs) == 1
    assert techs[0].name == "Данил"
    assert techs[0].is_active is True
    field = user_store.get(3003)
    assert field is not None
    assert field.user.technician_id == techs[0].technician_id
    assert field.user.name == "Данил"
    assert field.user.panels == frozenset()


def test_save_field_staff_update_preserves_existing_panels() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    tech_id = TechnicianId("10001")
    tech_store.upsert(Technician(technician_id=tech_id, name="Данил", is_active=True))
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ACTOR,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    field_user = SystemUser(
        user_id=SystemUserId("2"),
        name="Данил",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
    )
    user_store.replace_all(
        (
            SystemUserRecord(
                user=admin,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ACTOR,
            ),
            SystemUserRecord(
                user=field_user,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ACTOR,
            ),
        ),
    )
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Данил К.",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=SystemUserId("2"),
                technician_is_active=True,
                linked_technician_id=tech_id,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    field = user_store.get(3003)
    assert field is not None
    assert field.user.name == "Данил К."
    assert tech_store.get(tech_id).name == "Данил К."
    assert AdminPanel.ROSTER in field.user.panels


def test_save_field_staff_update_preserves_panels_when_actor_lacks_those_panels() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    tech_id = TechnicianId("10001")
    tech_store.upsert(Technician(technician_id=tech_id, name="Данил", is_active=True))
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=_ACTOR,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    field_user = SystemUser(
        user_id=SystemUserId("2"),
        name="Данил",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
    )
    user_store.replace_all(
        (
            SystemUserRecord(
                user=admin,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ACTOR,
            ),
            SystemUserRecord(
                user=field_user,
                updated_at=_NOW,
                updated_by_telegram_user_id=_ACTOR,
            ),
        ),
    )
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Данил К.",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=SystemUserId("2"),
                technician_is_active=True,
                linked_technician_id=tech_id,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=frozenset({AdminPanel.MASTER_DATA}),
        now=_NOW,
    )
    field = user_store.get(3003)
    assert field is not None
    assert field.user.name == "Данил К."
    assert tech_store.get(tech_id).name == "Данил К."
    assert AdminPanel.ROSTER in field.user.panels


def test_save_field_staff_rename_syncs_technician_name() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    _seed_users_admin(user_store)
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Данил",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=None,
                technician_is_active=True,
                linked_technician_id=None,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    field = user_store.get(3003)
    assert field is not None
    tech_id = field.user.technician_id
    assert tech_id is not None
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Данил К.",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=field.user.user_id,
                technician_is_active=True,
                linked_technician_id=tech_id,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    assert user_store.get(3003).user.name == "Данил К."
    assert tech_store.get(tech_id).name == "Данил К."


def test_save_field_staff_links_orphan_technician() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    _seed_users_admin(user_store)
    orphan_id = TechnicianId("10001")
    tech_store.upsert(Technician(technician_id=orphan_id, name="Орфан", is_active=True))
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Орфан",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=None,
                technician_is_active=True,
                linked_technician_id=orphan_id,
            ),
        ),
        actor_telegram_user_id=_ACTOR,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    assert len(tech_store.list_all()) == 1
    field = user_store.get(3003)
    assert field is not None
    assert field.user.technician_id == orphan_id
    assert field.user.panels == frozenset()


def test_save_field_staff_validation_fail_no_partial_write() -> None:
    user_store = InMemorySystemUserStore()
    tech_store = InMemoryTechnicianStore()
    _seed_users_admin(user_store)
    before_users = user_store.list_all()
    uc = _build_save_field_staff(user_store=user_store, tech_store=tech_store)
    with pytest.raises(FieldStaffInvalid):
        uc.execute(
            rows=(
                FieldStaffRowDraft(
                    telegram_user_id=3003,
                    name="A",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    user_id=None,
                    technician_is_active=True,
                    linked_technician_id=None,
                ),
                FieldStaffRowDraft(
                    telegram_user_id=3003,
                    name="Dup",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    user_id=None,
                    technician_is_active=True,
                    linked_technician_id=None,
                ),
            ),
            actor_telegram_user_id=_ACTOR,
            actor_panels=_all_panels(),
            now=_NOW,
        )
    assert user_store.list_all() == before_users
    assert tech_store.list_all() == ()
