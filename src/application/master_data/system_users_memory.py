from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.application.master_data.system_users import (
    SystemUserAuditRecord,
    SystemUserRecord,
)


@beartype
@dataclass(slots=True)
class InMemorySystemUserStore:
    _by_telegram_id: dict[int, SystemUserRecord] = field(default_factory=dict)
    _audit: list[SystemUserAuditRecord] = field(default_factory=list)

    def get(self, telegram_user_id: int) -> SystemUserRecord | None:
        return self._by_telegram_id.get(telegram_user_id)

    def list_all(self) -> tuple[SystemUserRecord, ...]:
        return tuple(self._by_telegram_id.values())

    def is_empty(self) -> bool:
        return not self._by_telegram_id

    def replace_all(self, records: tuple[SystemUserRecord, ...]) -> None:
        self._by_telegram_id = {record.user.telegram_user_id: record for record in records}

    def save_batch(
        self,
        records: tuple[SystemUserRecord, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
        audit_command: str,
    ) -> None:
        incoming = {record.user.telegram_user_id: record for record in records}
        for telegram_user_id, record in incoming.items():
            before = self._by_telegram_id.get(telegram_user_id)
            self._audit.append(
                SystemUserAuditRecord(
                    at=at,
                    actor_telegram_user_id=actor_telegram_user_id,
                    audit_command=audit_command,
                    telegram_user_id=telegram_user_id,
                    before=before,
                    after=record,
                ),
            )
            self._by_telegram_id[telegram_user_id] = record

    def list_audit(self) -> tuple[SystemUserAuditRecord, ...]:
        return tuple(self._audit)
