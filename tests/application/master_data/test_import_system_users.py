from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    ImportSystemUsersFromSheets,
    InMemorySystemUserStore,
    SystemUserRecord,
)
from src.application.sheets.bot_users import SystemUsersSnapshot
from src.domain.ids import TechnicianId
from src.domain.system_user import (
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _snapshot_one_admin_one_tech() -> SystemUsersSnapshot:
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1001,
        technician_id=None,
        company_roles=frozenset(),
    )
    tech = SystemUser(
        user_id=SystemUserId("2"),
        name="Tech",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1002,
        technician_id=TechnicianId("t1"),
        company_roles=frozenset(),
    )
    return SystemUsersSnapshot(
        users_by_telegram_id={1001: admin, 1002: tech},
        users_by_technician_id={TechnicianId("t1"): tech},
    )


def test_import_admin_bot_role_gets_empty_company_roles() -> None:
    store = InMemorySystemUserStore()
    snapshot = _snapshot_one_admin_one_tech()
    ImportSystemUsersFromSheets(store=store).execute(
        snapshot=snapshot,
        now=_NOW,
        actor_telegram_user_id=0,
    )
    admin = store.get(1001)
    assert admin is not None
    assert admin.user.company_roles == frozenset()
    assert admin.user.panels == frozenset()
    tech = store.get(1002)
    assert tech is not None
    assert tech.user.company_roles == frozenset()
    assert tech.user.panels == frozenset()


def test_import_noop_when_store_not_empty() -> None:
    store = InMemorySystemUserStore()
    existing = SystemUser(
        user_id=SystemUserId("9"),
        name="Keep",
        role=BotRole.NONE,
        is_active=True,
        telegram_user_id=9,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    store.replace_all(
        (SystemUserRecord(user=existing, updated_at=_NOW, updated_by_telegram_user_id=0),)
    )
    ImportSystemUsersFromSheets(store=store).execute(
        snapshot=_snapshot_one_admin_one_tech(),
        now=_NOW,
        actor_telegram_user_id=0,
    )
    assert store.get(9) is not None
    assert store.get(1001) is None


def test_import_writes_import_system_users_audit() -> None:
    store = InMemorySystemUserStore()
    ImportSystemUsersFromSheets(store=store).execute(
        snapshot=_snapshot_one_admin_one_tech(),
        now=_NOW,
        actor_telegram_user_id=0,
    )
    audits = store.list_audit()
    assert any(a.audit_command == "import_system_users" for a in audits)
    assert any(a.telegram_user_id == 1001 and a.after is not None for a in audits)


def test_import_inactive_admin_gets_no_web_panels() -> None:
    store = InMemorySystemUserStore()
    inactive = SystemUser(
        user_id=SystemUserId("3"),
        name="ExAdmin",
        role=BotRole.ADMINISTRATOR,
        is_active=False,
        telegram_user_id=1003,
        technician_id=None,
        company_roles=frozenset(),
    )
    snapshot = SystemUsersSnapshot(
        users_by_telegram_id={1003: inactive},
        users_by_technician_id={},
    )
    ImportSystemUsersFromSheets(store=store).execute(
        snapshot=snapshot,
        now=_NOW,
        actor_telegram_user_id=0,
    )
    loaded = store.get(1003)
    assert loaded is not None
    assert loaded.user.company_roles == frozenset()
    assert loaded.user.panels == frozenset()


def test_import_logs_system_users_import(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemorySystemUserStore()
    with caplog.at_level(logging.INFO):
        ImportSystemUsersFromSheets(store=store).execute(
            snapshot=_snapshot_one_admin_one_tech(),
            now=_NOW,
            actor_telegram_user_id=0,
        )
    record = next(r for r in caplog.records if r.getMessage() == "system_users_import")
    assert record.levelno == logging.INFO
    assert record.imported == 2
