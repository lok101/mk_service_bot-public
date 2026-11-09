from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId
from src.domain.models import PrefilledFormLink

ResponsibilityPhase = Literal["awaiting_handover", "responsible"]
RevisionDueStatus = Literal["not_due", "overdue"]

MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON = "Обслуживание на этом аппарате уже завершено сегодня."

LOADING_NOT_ALLOWED_REASON = "Загрузка доступна только после инвентаризации текущего техника."

MAINTENANCE_NOT_ALLOWED_REASON = (
    "Завершение обслуживания доступно только после инвентаризации текущего техника."
)

REVISION_NOT_ALLOWED_REASON = "Инвентаризация доступна только при передаче аппарата."

LOADING_PHOTOS_NOT_ALLOWED_REASON = (
    "Фото загрузки доступны только после инвентаризации текущего техника."
)

LOADING_PHOTOS_REQUIRE_LOADING_REASON = "Фото загрузки доступны только после указания загрузки."

LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON = "Недостаточно фотографий для отправки пакета загрузки."

LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON = "Фото загрузки за сегодня уже отправлены."

MAINTENANCE_COOLDOWN_REASON = "С момента обслуживания на другой локации прошло менее {n} мин."


@beartype
def maintenance_cooldown_reason(minutes: int) -> str:
    return MAINTENANCE_COOLDOWN_REASON.format(n=minutes)


@beartype
def loading_photos_excess_count_reason(max_count: int) -> str:
    return f"Максимум {max_count} фотографий."


@beartype
@dataclass(frozen=True, slots=True)
class ServiceCapabilities:
    technician_id: TechnicianId
    machine_id: MachineId
    responsibility_phase: ResponsibilityPhase
    can_complete_revision: bool
    can_submit_loading: bool
    can_submit_loading_photos: bool
    can_complete_maintenance: bool
    revision_form_link: PrefilledFormLink | None
    loading_completed: bool = False
    loading_photos_completed: bool = False
    maintenance_completed_today: bool = False
    responsibility_expires_at: datetime | None = None
    revision_due_status: RevisionDueStatus | None = None
    complete_maintenance_block_reason: str | None = None
    loading_photos_block_reason: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianRevisionOutlookEntry:
    machine_id: MachineId
    responsibility_expires_at: datetime | None
    revision_due_status: RevisionDueStatus | None


@beartype
@dataclass(frozen=True, slots=True)
class LoadingFormPrepared:
    technician_id: TechnicianId
    machine_id: MachineId
    form_link: PrefilledFormLink


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceAlreadyCompletedToday:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceCooldownActive:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class LoadingNotAllowed:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class MaintenanceNotAllowed:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class RevisionNotAllowed:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosNotAllowed:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosInsufficientCount:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str
    min_photo_count: int
    actual_count: int


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosAlreadySubmittedToday:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str
