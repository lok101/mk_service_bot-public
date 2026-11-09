from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.ports import MaintenanceCooldownBypassStore
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.maintenance_cooldown_policy import (
    is_maintenance_cooldown_bypassed,
    maintenance_cooldown_bypass_expires_at,
)


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceCooldownBypassStatus:
    active: bool
    service_date: date | None
    expires_at: datetime | None
    activated_at: datetime | None
    reason: str | None


@beartype
@dataclass(frozen=True, slots=True)
class DisableMaintenanceCooldownBypassForTodayService:
    store: MaintenanceCooldownBypassStore
    service_calendar_timezone: ZoneInfo
    service_day_end_hour: int

    @beartype
    def execute(
        self,
        *,
        activated_at: datetime,
        reason: str | None,
    ) -> MaintenanceCooldownBypassSnapshot:
        return self.store.upsert_for_today(
            activated_at=activated_at,
            reason=reason,
            service_calendar_timezone=self.service_calendar_timezone,
        )


@beartype
@dataclass(frozen=True, slots=True)
class GetMaintenanceCooldownBypassStatusService:
    store: MaintenanceCooldownBypassStore
    service_calendar_timezone: ZoneInfo
    service_day_end_hour: int
    checked_at: datetime

    @beartype
    def execute(self) -> MaintenanceCooldownBypassStatus:
        snapshot = self.store.get_snapshot()
        if snapshot is None:
            return MaintenanceCooldownBypassStatus(
                active=False,
                service_date=None,
                expires_at=None,
                activated_at=None,
                reason=None,
            )
        expires_at = maintenance_cooldown_bypass_expires_at(
            snapshot.service_date,
            self.service_calendar_timezone,
            day_end_hour=self.service_day_end_hour,
        )
        active = is_maintenance_cooldown_bypassed(
            checked_at=self.checked_at,
            bypass_service_date=snapshot.service_date,
            service_calendar_timezone=self.service_calendar_timezone,
            day_end_hour=self.service_day_end_hour,
        )
        return MaintenanceCooldownBypassStatus(
            active=active,
            service_date=snapshot.service_date,
            expires_at=expires_at,
            activated_at=snapshot.activated_at,
            reason=snapshot.reason,
        )


@beartype
@dataclass(frozen=True, slots=True)
class ClearMaintenanceCooldownBypassService:
    store: MaintenanceCooldownBypassStore

    @beartype
    def execute(self) -> bool:
        return self.store.clear()
