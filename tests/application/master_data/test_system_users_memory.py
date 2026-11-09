from __future__ import annotations

from datetime import UTC, datetime

from src.application.master_data import InMemorySystemUserStore, SystemUserRecord
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
    company_roles_from_legacy_panels,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_system_user_company_roles_roundtrip_memory() -> None:
    store = InMemorySystemUserStore()
    assert store.is_empty() is True
    user = SystemUser(
        user_id=SystemUserId("42"),
        name="A",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=42,
        technician_id=None,
        company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
    )
    rec = SystemUserRecord(user=user, updated_at=_NOW, updated_by_telegram_user_id=1)
    store.replace_all((rec,))
    assert store.is_empty() is False
    loaded = store.get(42)
    assert loaded is not None
    assert loaded.user.company_roles == frozenset({CompanyRole.ACCESS_ADMINISTRATOR})
    assert AdminPanel.USERS in loaded.user.panels


def test_legacy_users_only_panels_migrate_to_access_administrator() -> None:
    roles = company_roles_from_legacy_panels(frozenset({AdminPanel.USERS}))
    assert roles == frozenset({CompanyRole.ACCESS_ADMINISTRATOR})


def test_legacy_settlement_only_panels_migrate_to_settlement_operator() -> None:
    roles = company_roles_from_legacy_panels(frozenset({AdminPanel.SETTLEMENT_ANALYSIS}))
    assert roles == frozenset({CompanyRole.SETTLEMENT_OPERATOR})


def test_legacy_incomplete_panel_cover_leaves_remainder_without_roles() -> None:
    roles = company_roles_from_legacy_panels(
        frozenset({AdminPanel.SETTLEMENT_ANALYSIS, AdminPanel.ROSTER})
    )
    assert roles == frozenset({CompanyRole.SETTLEMENT_OPERATOR})
