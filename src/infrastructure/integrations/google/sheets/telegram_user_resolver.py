from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.reference_data import ReferenceDataProvider
from src.domain.ids import TechnicianId
from src.domain.system_user import SystemUser


@beartype
@dataclass(slots=True)
class GoogleSheetsTelegramUserResolver(TelegramUserResolver):
    provider: ReferenceDataProvider

    @beartype
    def resolve(self, telegram_user_id: int) -> SystemUser | None:
        snapshot = self.provider.system_users_or_none()
        if snapshot is None:
            return None
        return snapshot.users_by_telegram_id.get(telegram_user_id)

    @beartype
    def find_by_technician_id(self, technician_id: TechnicianId) -> SystemUser | None:
        snapshot = self.provider.system_users_or_none()
        if snapshot is None:
            return None
        return snapshot.users_by_technician_id.get(technician_id)
