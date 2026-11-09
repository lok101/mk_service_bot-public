from __future__ import annotations

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.domain.ids import TechnicianId
from src.infrastructure.integrations.google.sheets.telegram_user_resolver import (
    GoogleSheetsTelegramUserResolver,
)

_HEADER = ["id", "имя", "роль", "телеграм id", "id техника", "is active"]
_ROW = ["u-1", "Иван", "техник", "555", "tech-1", "1"]


def _resolver(rows: list[list[str]] | None) -> GoogleSheetsTelegramUserResolver:
    provider = ReferenceDataProvider()
    if rows is not None:
        provider.apply_rows(ReferenceDataSourceId.BOT_USERS, rows)
    return GoogleSheetsTelegramUserResolver(provider=provider)


def test_resolve_returns_user() -> None:
    resolver = _resolver([_HEADER, _ROW])
    user = resolver.resolve(555)
    assert user is not None
    assert user.technician_id == TechnicianId("tech-1")


def test_resolve_returns_none_when_degraded() -> None:
    assert _resolver(None).resolve(555) is None
    assert _resolver(None).find_by_technician_id(TechnicianId("tech-1")) is None
