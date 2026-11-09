from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    REVISION_NOT_ALLOWED_REASON,
    ServiceCapabilities,
)
from src.interfaces.telegram.dialog_layout import TELEGRAM_DIALOG_MIN_WIDTH_LINE
from src.interfaces.telegram.machines.form_workflow_error import format_form_error_block

_LABEL_REVISION = "Инвентаризация"
_LABEL_LOADING = "Указать загрузку"
_LABEL_LOADING_PHOTOS = "Загрузить фото"
_LABEL_COMPLETE_MAINTENANCE = "Завершить без фото"
_LABEL_SNACK_INVENTORY = "Инвентаризация снека"
_LABEL_MM_CHECKLIST_1 = "Снять просроченные"
_LABEL_MM_CHECKLIST_2 = "Разложить по местам"
_LABEL_MM_CHECKLIST_3 = "Выложить привезённое"
_LABEL_BACK = "Назад к списку аппаратов"

_HANDOVER_INSTRUCTION = "❗ Сначала укажите загрузку, затем инвентаризацию."


@beartype
def button_label(action: str) -> str:
    labels = {
        "revision": _LABEL_REVISION,
        "loading": _LABEL_LOADING,
        "loading_photos": _LABEL_LOADING_PHOTOS,
        "complete_maintenance": _LABEL_COMPLETE_MAINTENANCE,
        "snack_inventory": _LABEL_SNACK_INVENTORY,
        "micromarket_inventory": _LABEL_REVISION,
        "mm_checklist_1": _LABEL_MM_CHECKLIST_1,
        "mm_checklist_2": _LABEL_MM_CHECKLIST_2,
        "mm_checklist_3": _LABEL_MM_CHECKLIST_3,
        "back": _LABEL_BACK,
    }
    if action not in labels:
        raise ValueError(f"Unknown workspace button action: {action!r}")
    return labels[action]


@beartype
def stub_reason_for_action(action: str) -> str:
    reasons = {
        "revision": REVISION_NOT_ALLOWED_REASON,
        "loading": LOADING_NOT_ALLOWED_REASON,
        "loading_photos": LOADING_PHOTOS_NOT_ALLOWED_REASON,
        "complete_maintenance": MAINTENANCE_NOT_ALLOWED_REASON,
    }
    if action not in reasons:
        raise ValueError(f"Unknown workspace stub action: {action!r}")
    return reasons[action]


@beartype
def revision_due_line(
    *,
    caps: ServiceCapabilities,
    timezone: ZoneInfo,
    checked_at: datetime,
) -> str | None:
    if caps.responsibility_phase == "awaiting_handover":
        return "❗ Инвентаризация: сегодня"
    if caps.responsibility_phase != "responsible":
        return None
    if caps.revision_due_status is None or caps.responsibility_expires_at is None:
        return None
    if caps.revision_due_status == "overdue":
        return None

    date_str = caps.responsibility_expires_at.astimezone(timezone).strftime("%d.%m.%Y")
    return f"Инвентаризация: {date_str}"


@beartype
def build_workspace_screen_text(
    *,
    caps: ServiceCapabilities,
    machine_name: str,
    machine_id: str,
    last_loading_line: str,
    last_service_line: str,
    form_error: str | None,
    service_timezone: ZoneInfo,
    checked_at: datetime,
    is_micromarket: bool = False,
) -> str:
    lines = [
        TELEGRAM_DIALOG_MIN_WIDTH_LINE,
        machine_name,
        f"Id аппарата: {machine_id}",
        "",
        last_loading_line,
        last_service_line,
        "",
    ]
    if not is_micromarket:
        due_line = revision_due_line(
            caps=caps,
            timezone=service_timezone,
            checked_at=checked_at,
        )
        if due_line is not None:
            lines.append(due_line)
        if caps.responsibility_phase == "awaiting_handover":
            lines.append(_HANDOVER_INSTRUCTION)

    phase_block = "\n".join(lines)
    parts = [phase_block]
    if form_error is not None:
        parts.extend(["", format_form_error_block(form_error)])
    return "\n".join(parts)
