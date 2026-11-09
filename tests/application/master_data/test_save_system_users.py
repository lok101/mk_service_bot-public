from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    SYSTEM_USER_COUNTER_KEY,
    InMemoryMasterDataCounterStore,
    InMemorySystemUserStore,
    InMemoryTechnicianStore,
    SaveSystemUsers,
    SystemUserDraft,
    SystemUserRecord,
    SystemUsersInvalid,
    Technician,
    technician_ids_for_system_users_validation,
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

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_ADMIN_ROLES = frozenset({CompanyRole.ACCESS_ADMINISTRATOR})


def _all_panels() -> frozenset[AdminPanel]:
    return frozenset(permission_panels())


def _users_admin(
    *,
    telegram_user_id: int,
    user_id: str,
    company_roles: frozenset[CompanyRole] = _ADMIN_ROLES,
) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId(user_id),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=telegram_user_id,
        technician_id=None,
        company_roles=company_roles,
    )


def _record(user: SystemUser) -> SystemUserRecord:
    return SystemUserRecord(user=user, updated_at=_NOW, updated_by_telegram_user_id=1)


def _admin_draft(
    *,
    telegram_user_id: int = 1,
    user_id: str = "1",
    company_roles: frozenset[CompanyRole] = _ADMIN_ROLES,
) -> SystemUserDraft:
    return SystemUserDraft(
        telegram_user_id=telegram_user_id,
        name="Admin",
        bot_role=BotRole.ADMINISTRATOR,
        is_active=True,
        technician_id=None,
        company_roles=company_roles,
        user_id=SystemUserId(user_id),
    )


def test_save_rejects_duplicate_technician_id_in_batch() -> None:
    store = InMemorySystemUserStore()
    seed = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(seed),))
    uc = SaveSystemUsers(store=store, counters=InMemoryMasterDataCounterStore())
    shared = TechnicianId("tech-1")
    with pytest.raises(SystemUsersInvalid, match="technician"):
        uc.execute(
            drafts=(
                _admin_draft(),
                SystemUserDraft(
                    telegram_user_id=2,
                    name="A",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    technician_id=shared,
                    company_roles=frozenset(),
                    user_id=None,
                ),
                SystemUserDraft(
                    telegram_user_id=3,
                    name="B",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    technician_id=shared,
                    company_roles=frozenset(),
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset({shared}),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )


def test_save_rejects_duplicate_technician_id_against_existing() -> None:
    store = InMemorySystemUserStore()
    admin = _users_admin(telegram_user_id=1, user_id="1")
    existing = SystemUser(
        user_id=SystemUserId("2"),
        name="Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=2,
        technician_id=TechnicianId("tech-1"),
        company_roles=frozenset(),
    )
    store.replace_all((_record(admin), _record(existing)))
    uc = SaveSystemUsers(store=store, counters=InMemoryMasterDataCounterStore())
    with pytest.raises(SystemUsersInvalid, match="technician"):
        uc.execute(
            drafts=(
                SystemUserDraft(
                    telegram_user_id=1,
                    name="Admin",
                    bot_role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    technician_id=TechnicianId("tech-1"),
                    company_roles=_ADMIN_ROLES,
                    user_id=SystemUserId("1"),
                ),
            ),
            directory_technician_ids=frozenset({TechnicianId("tech-1")}),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )
    assert store.get(2) is not None


def test_save_rejects_role_change_outside_actor_scope() -> None:
    store = InMemorySystemUserStore()
    admin = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(admin),))
    uc = SaveSystemUsers(store=store, counters=InMemoryMasterDataCounterStore())
    with pytest.raises(SystemUsersInvalid, match="actor scope"):
        uc.execute(
            drafts=(
                _admin_draft(),
                SystemUserDraft(
                    telegram_user_id=2,
                    name="Acc",
                    bot_role=BotRole.NONE,
                    is_active=True,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.SETTLEMENT_OPERATOR}),
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset(),
            actor_telegram_user_id=1,
            actor_panels=frozenset({AdminPanel.SETTLEMENT_ANALYSIS}),
            now=_NOW,
        )


def test_save_rejects_last_access_administrator_removal() -> None:
    store = InMemorySystemUserStore()
    only_admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1,
        technician_id=None,
        company_roles=frozenset(
            {
                CompanyRole.ACCESS_ADMINISTRATOR,
                CompanyRole.SERVICE_OPERATIONS_COORDINATOR,
            }
        ),
    )
    store.replace_all(
        (
            SystemUserRecord(
                user=only_admin,
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        )
    )
    uc = SaveSystemUsers(store=store, counters=InMemoryMasterDataCounterStore())
    with pytest.raises(SystemUsersInvalid, match="access administrator"):
        uc.execute(
            drafts=(
                SystemUserDraft(
                    telegram_user_id=1,
                    name="Admin",
                    bot_role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                    user_id=SystemUserId("1"),
                ),
            ),
            directory_technician_ids=frozenset(),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )
    assert CompanyRole.ACCESS_ADMINISTRATOR in store.get(1).user.company_roles  # type: ignore[union-attr]


def test_save_rejects_duplicate_telegram_id() -> None:
    uc = SaveSystemUsers(store=InMemorySystemUserStore(), counters=InMemoryMasterDataCounterStore())
    draft = SystemUserDraft(
        telegram_user_id=5,
        name="A",
        bot_role=BotRole.NONE,
        is_active=True,
        technician_id=None,
        company_roles=_ADMIN_ROLES,
        user_id=None,
    )
    dup = SystemUserDraft(
        telegram_user_id=5,
        name="B",
        bot_role=BotRole.NONE,
        is_active=True,
        technician_id=None,
        company_roles=_ADMIN_ROLES,
        user_id=None,
    )
    with pytest.raises(SystemUsersInvalid, match="telegram"):
        uc.execute(
            drafts=(draft, dup),
            directory_technician_ids=frozenset(),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )


def test_save_rejects_unknown_technician() -> None:
    uc = SaveSystemUsers(store=InMemorySystemUserStore(), counters=InMemoryMasterDataCounterStore())
    with pytest.raises(SystemUsersInvalid, match="technician"):
        uc.execute(
            drafts=(
                SystemUserDraft(
                    telegram_user_id=1,
                    name="A",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    technician_id=TechnicianId("t-missing"),
                    company_roles=_ADMIN_ROLES,
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset({TechnicianId("t-ok")}),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )


def test_save_rejects_non_positive_telegram_id() -> None:
    uc = SaveSystemUsers(store=InMemorySystemUserStore(), counters=InMemoryMasterDataCounterStore())
    with pytest.raises(SystemUsersInvalid, match="telegram"):
        uc.execute(
            drafts=(
                SystemUserDraft(
                    telegram_user_id=0,
                    name="A",
                    bot_role=BotRole.NONE,
                    is_active=True,
                    technician_id=None,
                    company_roles=_ADMIN_ROLES,
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset(),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )


def test_save_system_users_happy_allocates_and_audits() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    seed = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all(
        (SystemUserRecord(user=seed, updated_at=_NOW, updated_by_telegram_user_id=1),)
    )
    uc = SaveSystemUsers(store=store, counters=counters)
    uc.execute(
        drafts=(
            _admin_draft(),
            SystemUserDraft(
                telegram_user_id=2,
                name="Acc",
                bot_role=BotRole.NONE,
                is_active=True,
                technician_id=None,
                company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                user_id=None,
            ),
        ),
        directory_technician_ids=frozenset(),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    assert store.get(2) is not None
    assert store.get(2).user.user_id.value == "2"  # type: ignore[union-attr]
    assert store.get(2).user.company_roles == frozenset(  # type: ignore[union-attr]
        {CompanyRole.SERVICE_OPERATIONS_COORDINATOR}
    )
    audits = store.list_audit()
    assert any(a.audit_command == "save_system_users" for a in audits)


class _CountingSystemUserStore:
    """Delegates to memory store; counts write ops for single-path assert."""

    def __init__(self, inner: InMemorySystemUserStore) -> None:
        self._inner = inner
        self.save_batch_calls = 0
        self.replace_all_calls = 0

    def get(self, telegram_user_id: int) -> SystemUserRecord | None:
        return self._inner.get(telegram_user_id)

    def list_all(self) -> tuple[SystemUserRecord, ...]:
        return self._inner.list_all()

    def is_empty(self) -> bool:
        return self._inner.is_empty()

    def replace_all(self, records: tuple[SystemUserRecord, ...]) -> None:
        self.replace_all_calls += 1
        self._inner.replace_all(records)

    def save_batch(
        self,
        records: tuple[SystemUserRecord, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
        audit_command: str,
    ) -> None:
        self.save_batch_calls += 1
        self._inner.save_batch(
            records,
            actor_telegram_user_id=actor_telegram_user_id,
            at=at,
            audit_command=audit_command,
        )

    def list_audit(self):
        return self._inner.list_audit()


def test_save_upsert_preserves_omitted_user() -> None:
    inner = InMemorySystemUserStore()
    admin = _users_admin(telegram_user_id=1, user_id="1")
    other = SystemUser(
        user_id=SystemUserId("2"),
        name="Other",
        role=BotRole.NONE,
        is_active=True,
        telegram_user_id=2,
        technician_id=None,
        company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
    )
    inner.replace_all((_record(admin), _record(other)))
    store = _CountingSystemUserStore(inner)
    uc = SaveSystemUsers(store=store, counters=InMemoryMasterDataCounterStore())
    uc.execute(
        drafts=(
            SystemUserDraft(
                telegram_user_id=1,
                name="Admin Renamed",
                bot_role=BotRole.ADMINISTRATOR,
                is_active=True,
                technician_id=None,
                company_roles=_ADMIN_ROLES,
                user_id=SystemUserId("1"),
            ),
        ),
        directory_technician_ids=frozenset(),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )

    assert store.get(2) is not None
    assert store.get(2).user.name == "Other"
    assert store.get(1) is not None
    assert store.get(1).user.name == "Admin Renamed"
    assert store.save_batch_calls == 1
    deletion_audits = [a for a in store.list_audit() if a.telegram_user_id == 2 and a.after is None]
    assert deletion_audits == []


def test_save_guard_failure_does_not_advance_counter() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    counters.set(SYSTEM_USER_COUNTER_KEY, 1)
    seed = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(seed),))
    uc = SaveSystemUsers(store=store, counters=counters)

    with pytest.raises(SystemUsersInvalid, match="access administrator"):
        uc.execute(
            drafts=(
                SystemUserDraft(
                    telegram_user_id=1,
                    name="Admin",
                    bot_role=BotRole.ADMINISTRATOR,
                    is_active=True,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                    user_id=SystemUserId("1"),
                ),
                SystemUserDraft(
                    telegram_user_id=99,
                    name="New",
                    bot_role=BotRole.NONE,
                    is_active=True,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset(),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )

    assert counters.get(SYSTEM_USER_COUNTER_KEY) == 1
    assert store.get(99) is None


def test_save_service_coordinator_derives_visit_board() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    store.replace_all((_record(_users_admin(telegram_user_id=1, user_id="1")),))
    uc = SaveSystemUsers(store=store, counters=counters)
    uc.execute(
        drafts=(
            _admin_draft(),
            SystemUserDraft(
                telegram_user_id=2,
                name="Ops2",
                bot_role=BotRole.NONE,
                is_active=True,
                technician_id=None,
                company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                user_id=None,
            ),
        ),
        directory_technician_ids=frozenset(),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    saved = store.get(2)
    assert saved is not None
    assert AdminPanel.VISIT_BOARD in saved.user.panels
    assert AdminPanel.ROSTER in saved.user.panels


def test_save_users_accepts_inactive_technician_id() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    seed = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(seed),))
    inactive = TechnicianId("10002")
    uc = SaveSystemUsers(store=store, counters=counters)
    uc.execute(
        drafts=(
            _admin_draft(),
            SystemUserDraft(
                telegram_user_id=2,
                name="Linked",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                technician_id=inactive,
                company_roles=frozenset(),
                user_id=None,
            ),
        ),
        directory_technician_ids=frozenset({inactive}),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    saved = store.get(2)
    assert saved is not None
    assert saved.user.technician_id == inactive


def test_save_users_rejects_unknown_technician_when_technicians_enabled() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    seed = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(seed),))
    known = TechnicianId("10001")
    uc = SaveSystemUsers(store=store, counters=counters)
    with pytest.raises(SystemUsersInvalid, match="technician"):
        uc.execute(
            drafts=(
                _admin_draft(),
                SystemUserDraft(
                    telegram_user_id=2,
                    name="Linked",
                    bot_role=BotRole.TECHNICIAN,
                    is_active=True,
                    technician_id=TechnicianId("missing"),
                    company_roles=frozenset(),
                    user_id=None,
                ),
            ),
            directory_technician_ids=frozenset({known}),
            actor_telegram_user_id=1,
            actor_panels=_all_panels(),
            now=_NOW,
        )
    assert store.get(2) is None


def test_technician_ids_for_validation_uses_store_including_inactive() -> None:
    tech_store = InMemoryTechnicianStore()
    active = TechnicianId("1")
    inactive = TechnicianId("2")
    tech_store.upsert(Technician(technician_id=active, name="A", is_active=True))
    tech_store.upsert(Technician(technician_id=inactive, name="B", is_active=False))
    ids = technician_ids_for_system_users_validation(
        technicians_enabled=True,
        technician_store=tech_store,
        directory_snapshot_ids=frozenset({TechnicianId("sheet-only")}),
    )
    assert ids == frozenset({active, inactive})


def test_technician_ids_for_validation_uses_snapshot_when_flag_off() -> None:
    snapshot = frozenset({TechnicianId("sheet-1")})
    ids = technician_ids_for_system_users_validation(
        technicians_enabled=False,
        technician_store=None,
        directory_snapshot_ids=snapshot,
    )
    assert ids == snapshot


def test_save_system_users_preserve_technician_link_on_access_save() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    admin = _users_admin(telegram_user_id=1, user_id="1")
    tech_id = TechnicianId("10001")
    field = SystemUser(
        user_id=SystemUserId("2"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset(),
    )
    store.replace_all((_record(admin), _record(field)))
    uc = SaveSystemUsers(store=store, counters=counters)
    uc.execute(
        drafts=(
            _admin_draft(),
            SystemUserDraft(
                telegram_user_id=3003,
                name="Иван",
                bot_role=BotRole.NONE,
                is_active=True,
                technician_id=None,
                company_roles=frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR}),
                user_id=SystemUserId("2"),
            ),
        ),
        directory_technician_ids=frozenset({tech_id}),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
        preserve_technician_links=True,
    )
    saved = store.get(3003)
    assert saved is not None
    assert saved.user.technician_id == tech_id
    assert saved.user.role is BotRole.TECHNICIAN
    assert saved.user.company_roles == frozenset({CompanyRole.SERVICE_OPERATIONS_COORDINATOR})


def test_save_system_users_access_office_no_technician() -> None:
    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    admin = _users_admin(telegram_user_id=1, user_id="1")
    store.replace_all((_record(admin),))
    uc = SaveSystemUsers(store=store, counters=counters)
    uc.execute(
        drafts=(
            _admin_draft(),
            SystemUserDraft(
                telegram_user_id=2002,
                name="Office",
                bot_role=BotRole.NONE,
                is_active=True,
                technician_id=None,
                company_roles=frozenset({CompanyRole.SETTLEMENT_OPERATOR}),
                user_id=None,
            ),
        ),
        directory_technician_ids=frozenset(),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    office = store.get(2002)
    assert office is not None
    assert office.user.technician_id is None
    assert office.user.role is BotRole.NONE
    assert office.user.company_roles == frozenset({CompanyRole.SETTLEMENT_OPERATOR})


def test_save_field_staff_preserves_company_roles() -> None:
    from src.application.master_data import (
        InMemoryMasterDataAuditStore,
    )
    from src.application.master_data.save_field_staff import (
        FieldStaffRowDraft,
        SaveFieldStaff,
    )
    from src.application.master_data.technicians import CreateTechnician, UpdateTechnician

    store = InMemorySystemUserStore()
    counters = InMemoryMasterDataCounterStore()
    tech_store = InMemoryTechnicianStore()
    tech_id = TechnicianId("10001")
    tech_store.upsert(Technician(technician_id=tech_id, name="Иван", is_active=True))
    admin = _users_admin(telegram_user_id=1, user_id="1")
    field = SystemUser(
        user_id=SystemUserId("2"),
        name="Иван",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=3003,
        technician_id=tech_id,
        company_roles=frozenset({CompanyRole.SETTLEMENT_OPERATOR}),
    )
    store.replace_all((_record(admin), _record(field)))
    audit = InMemoryMasterDataAuditStore()
    uc = SaveFieldStaff(
        save_system_users=SaveSystemUsers(store=store, counters=counters),
        create_technician=CreateTechnician(store=tech_store, counters=counters, audit=audit),
        update_technician=UpdateTechnician(store=tech_store, audit=audit),
        technician_store=tech_store,
        technicians_enabled=True,
    )
    uc.execute(
        rows=(
            FieldStaffRowDraft(
                telegram_user_id=3003,
                name="Иван",
                bot_role=BotRole.TECHNICIAN,
                is_active=True,
                user_id=SystemUserId("2"),
                technician_is_active=True,
                linked_technician_id=tech_id,
            ),
        ),
        actor_telegram_user_id=1,
        actor_panels=_all_panels(),
        now=_NOW,
    )
    saved = store.get(3003)
    assert saved is not None
    assert saved.user.company_roles == frozenset({CompanyRole.SETTLEMENT_OPERATOR})
