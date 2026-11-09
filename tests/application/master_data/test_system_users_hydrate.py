from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    InMemorySystemUserStore,
    SystemUserRecord,
    hydrate_provider_from_system_users,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId

_NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def test_hydrate_logs_duplicate_technician_id(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemorySystemUserStore()
    shared = TechnicianId("tech-dup")
    store.replace_all(
        (
            SystemUserRecord(
                user=SystemUser(
                    user_id=SystemUserId("1"),
                    name="A",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=1,
                    technician_id=shared,
                    company_roles=frozenset(),
                ),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
            SystemUserRecord(
                user=SystemUser(
                    user_id=SystemUserId("2"),
                    name="B",
                    role=BotRole.TECHNICIAN,
                    is_active=True,
                    telegram_user_id=2,
                    technician_id=shared,
                    company_roles=frozenset(),
                ),
                updated_at=_NOW,
                updated_by_telegram_user_id=1,
            ),
        ),
    )
    provider = ReferenceDataProvider()
    with caplog.at_level("WARNING"):
        hydrate_provider_from_system_users(provider, store)
    assert any("duplicate_technician" in r.message.lower() for r in caplog.records)
