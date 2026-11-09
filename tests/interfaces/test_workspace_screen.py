from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.domain.ids import MachineId, TechnicianId
from src.domain.models import PrefilledFormLink
from src.domain.results import ServiceCapabilities
from src.interfaces.telegram.dialog_layout import TELEGRAM_DIALOG_MIN_WIDTH_LINE
from src.interfaces.telegram.machines.workspace_screen import (
    build_workspace_screen_text,
    button_label,
    revision_due_line,
)
from src.interfaces.telegram.machines.workspace_styles import (
    awaiting_handover,
    prefixed_button_label,
    workspace_action_button_texts,
    workspace_button_style_flags,
)

_MSK = ZoneInfo("Europe/Moscow")
_CHECKED_AT = datetime(2026, 5, 25, 9, 0, tzinfo=UTC)
_EXPIRES = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
_NO_LAST_LOADING = "📦 Последняя загрузка: нет данных"
_NO_LAST_SERVICE = "🛠️ Последнее обслуживание: нет данных"


def _caps(
    *,
    responsibility_phase: str = "awaiting_handover",
    can_complete_revision: bool = True,
    can_submit_loading: bool = False,
    can_submit_loading_photos: bool = False,
    can_complete_maintenance: bool = False,
    loading_completed: bool = False,
    loading_photos_completed: bool = False,
    maintenance_completed_today: bool = False,
    revision_due_status: str | None = None,
    responsibility_expires_at: datetime | None = None,
) -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        responsibility_phase=responsibility_phase,  # type: ignore[arg-type]
        can_complete_revision=can_complete_revision,
        can_submit_loading=can_submit_loading,
        can_submit_loading_photos=can_submit_loading_photos,
        can_complete_maintenance=can_complete_maintenance,
        revision_form_link=PrefilledFormLink(url="https://example.com/rev"),
        loading_completed=loading_completed,
        loading_photos_completed=loading_photos_completed,
        maintenance_completed_today=maintenance_completed_today,
        revision_due_status=revision_due_status,  # type: ignore[arg-type]
        responsibility_expires_at=responsibility_expires_at,
    )


def test_button_labels_are_fixed_russian() -> None:
    assert button_label("revision") == "Инвентаризация"
    assert button_label("loading_photos") == "Загрузить фото"
    assert button_label("complete_maintenance") == "Завершить без фото"


def test_workspace_capability_prefix_success_is_check() -> None:
    # happy: snack keeps capability ✅/⛔; MM inventory/photos use phase cues
    caps = _caps(
        can_complete_revision=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
    )
    flags = workspace_button_style_flags(caps, is_micromarket=True)
    texts = workspace_action_button_texts(
        flags,
        snack_available=True,
        snack_stub=False,
        micromarket_available=True,
        micromarket_stub=False,
        is_micromarket=True,
        caps=caps,
    )
    assert texts["revision_button_text"].startswith("✅ ")
    assert texts["revision_button_text"].endswith("Инвентаризация")
    assert texts["micromarket_inventory_button_text"].startswith("✅ ")
    assert texts["loading_photos_button_text"].startswith("5️⃣ ")
    assert texts["snack_inventory_button_text"].startswith("✅ ")


def test_workspace_capability_prefix_danger_is_block() -> None:
    # unavailable snack still ⛔; MM photos use phase cue 5️⃣ (not capability ⛔)
    caps = _caps(
        responsibility_phase="awaiting_handover",
        can_submit_loading=False,
        can_submit_loading_photos=False,
    )
    flags = workspace_button_style_flags(caps, is_micromarket=True)
    texts = workspace_action_button_texts(
        flags,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=True,
        caps=caps,
    )
    assert texts["loading_button_text"].startswith("⛔ ")
    assert texts["loading_photos_button_text"].startswith("5️⃣ ")
    assert texts["snack_inventory_button_text"].startswith("⛔ ")


def test_workspace_back_label_has_no_capability_prefix() -> None:
    # edge
    assert prefixed_button_label("back", available=True) == "Назад к списку аппаратов"
    assert not prefixed_button_label("back", available=False).startswith("✅")
    assert not prefixed_button_label("back", available=False).startswith("⛔")


def test_complete_maintenance_never_uses_success_style() -> None:
    flags = workspace_button_style_flags(
        _caps(
            responsibility_phase="responsible",
            can_complete_maintenance=True,
            maintenance_completed_today=False,
        ),
    )
    assert flags["complete_maintenance_style_success"] is False


def test_responsible_screen_text_matches_compact_format() -> None:
    caps = _caps(
        responsibility_phase="responsible",
        can_submit_loading=True,
        revision_due_status="not_due",
        responsibility_expires_at=_EXPIRES,
    )
    text = build_workspace_screen_text(
        caps=caps,
        machine_name="VM 1",
        machine_id="vm-1",
        last_loading_line="📦 Последняя загрузка: 09.06.2026 14:30",
        last_service_line=_NO_LAST_SERVICE,
        form_error=None,
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert "Техник" not in text
    assert "Обслуживание" not in text
    assert "Локация:" not in text
    assert "Аппарат ID:" not in text
    assert "Фото:" not in text
    assert text.splitlines() == [
        TELEGRAM_DIALOG_MIN_WIDTH_LINE,
        "VM 1",
        "Id аппарата: vm-1",
        "",
        "📦 Последняя загрузка: 09.06.2026 14:30",
        _NO_LAST_SERVICE,
        "",
        "Инвентаризация: 25.05.2026",
    ]


def test_responsible_screen_omits_revision_when_status_missing() -> None:
    text = build_workspace_screen_text(
        caps=_caps(responsibility_phase="responsible", can_submit_loading=True),
        machine_name="VM 1",
        machine_id="vm-1",
        last_loading_line=_NO_LAST_LOADING,
        last_service_line=_NO_LAST_SERVICE,
        form_error=None,
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert "Инвентаризация" not in text
    assert text.splitlines() == [
        TELEGRAM_DIALOG_MIN_WIDTH_LINE,
        "VM 1",
        "Id аппарата: vm-1",
        "",
        _NO_LAST_LOADING,
        _NO_LAST_SERVICE,
    ]


def test_responsible_screen_revision_after_last_service() -> None:
    caps = _caps(
        responsibility_phase="responsible",
        can_submit_loading=True,
        revision_due_status="not_due",
        responsibility_expires_at=_EXPIRES,
    )
    text = build_workspace_screen_text(
        caps=caps,
        machine_name="VM 1",
        machine_id="vm-1",
        last_loading_line=_NO_LAST_LOADING,
        last_service_line=_NO_LAST_SERVICE,
        form_error=None,
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    rev_idx = text.index("Инвентаризация: 25.05.2026")
    last_idx = text.index(_NO_LAST_SERVICE)
    assert last_idx < rev_idx


def test_handover_screen_text_matches_compact_format() -> None:
    text = build_workspace_screen_text(
        caps=_caps(can_submit_loading=True),
        machine_name="VM 1",
        machine_id="vm-1",
        last_loading_line=_NO_LAST_LOADING,
        last_service_line=_NO_LAST_SERVICE,
        form_error=None,
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert "Передача аппарата" not in text
    assert "Аппарат:" not in text
    assert text.splitlines() == [
        TELEGRAM_DIALOG_MIN_WIDTH_LINE,
        "VM 1",
        "Id аппарата: vm-1",
        "",
        _NO_LAST_LOADING,
        _NO_LAST_SERVICE,
        "",
        "❗ Инвентаризация: сегодня",
        "❗ Сначала укажите загрузку, затем инвентаризацию.",
    ]


def test_workspace_screen_appends_form_error_after_main_text() -> None:
    text = build_workspace_screen_text(
        caps=_caps(),
        machine_name="VM 1",
        machine_id="vm-1",
        last_loading_line=_NO_LAST_LOADING,
        last_service_line=_NO_LAST_SERVICE,
        form_error="ошибка токена",
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert text.endswith("🔴 ОШИБКА 🔴\n\nошибка токена")
    assert text.splitlines()[0] == TELEGRAM_DIALOG_MIN_WIDTH_LINE
    revision_idx = text.index("❗ Инвентаризация: сегодня")
    error_idx = text.index("🔴 ОШИБКА 🔴")
    assert revision_idx < error_idx


def test_onboarding_form_buttons_success_when_can() -> None:
    flags = workspace_button_style_flags(
        _caps(can_submit_loading=True, loading_completed=False),
    )
    assert flags["revision_style_success"] is False
    assert flags["loading_style_success"] is True
    assert flags["loading_style_danger"] is False
    assert flags["loading_photos_style_danger"] is False
    assert flags["loading_photos_style_success"] is False


def test_handover_loading_style_success_when_can_submit_loading() -> None:
    flags = workspace_button_style_flags(
        _caps(
            responsibility_phase="awaiting_handover",
            can_submit_loading=True,
            loading_completed=False,
        ),
    )
    assert flags["loading_style_success"] is True
    assert flags["loading_style_danger"] is False


def test_active_loading_style_success_even_when_loading_completed() -> None:
    # after loading in handover, active phase moves to revision (not loading)
    flags = workspace_button_style_flags(
        _caps(
            responsibility_phase="awaiting_handover",
            can_complete_revision=True,
            can_submit_loading=True,
            loading_completed=True,
        ),
    )
    assert awaiting_handover(_caps(responsibility_phase="responsible")) is False
    assert flags["loading_style_success"] is False
    assert flags["revision_style_success"] is True
    assert flags["loading_style_danger"] is False


def test_loading_photos_style_success_when_can_submit() -> None:
    flags = workspace_button_style_flags(
        _caps(
            responsibility_phase="responsible",
            can_submit_loading_photos=True,
            loading_completed=True,
            loading_photos_completed=False,
        ),
    )
    assert flags["loading_photos_style_success"] is True


def test_show_maintenance_back_visible_before_maintenance_completed() -> None:
    caps_pending = _caps(
        responsibility_phase="responsible",
        can_submit_loading=True,
        can_complete_maintenance=False,
        maintenance_completed_today=False,
    )
    assert caps_pending.maintenance_completed_today is False
    assert caps_pending.can_complete_maintenance is False


def test_revision_due_line_not_due() -> None:
    line = revision_due_line(
        caps=_caps(
            responsibility_phase="responsible",
            revision_due_status="not_due",
            responsibility_expires_at=_EXPIRES,
        ),
        timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert line == "Инвентаризация: 25.05.2026"


def test_revision_due_line_not_due_on_deadline_day_shows_date_not_today() -> None:
    line = revision_due_line(
        caps=_caps(
            responsibility_phase="responsible",
            revision_due_status="not_due",
            responsibility_expires_at=_EXPIRES,
        ),
        timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert line == "Инвентаризация: 25.05.2026"
    assert "сегодня" not in line


def test_revision_due_line_overdue_returns_none() -> None:
    line = revision_due_line(
        caps=_caps(
            responsibility_phase="responsible",
            revision_due_status="overdue",
            responsibility_expires_at=_EXPIRES,
        ),
        timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert line is None


def test_revision_due_line_awaiting_handover_always_today() -> None:
    line = revision_due_line(
        caps=_caps(responsibility_phase="awaiting_handover"),
        timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert line == "❗ Инвентаризация: сегодня"


def test_revision_due_line_responsible_missing_status_returns_none() -> None:
    line = revision_due_line(
        caps=_caps(
            responsibility_phase="responsible",
            revision_due_status=None,
            responsibility_expires_at=None,
        ),
        timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert line is None


def test_force_majeure_effective_caps_screen_has_due_no_handover_instruction() -> None:
    # responsible with deadline date — due line, no handover instruction
    caps = _caps(
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=True,
        can_submit_loading_photos=True,
        can_complete_maintenance=True,
        revision_due_status="not_due",
        responsibility_expires_at=datetime(2026, 5, 25, 0, 0, tzinfo=_MSK),
    )
    text = build_workspace_screen_text(
        caps=caps,
        machine_name="Аппарат",
        machine_id="vm-1",
        last_loading_line=_NO_LAST_LOADING,
        last_service_line=_NO_LAST_SERVICE,
        form_error=None,
        service_timezone=_MSK,
        checked_at=_CHECKED_AT,
    )
    assert "Инвентаризация: 25.05.2026" in text
    assert "Сначала укажите загрузку, затем инвентаризацию" not in text


def test_force_majeure_effective_caps_not_awaiting_handover_style() -> None:
    caps = _caps(
        responsibility_phase="responsible",
        can_complete_revision=False,
        revision_due_status="not_due",
        responsibility_expires_at=datetime(2026, 5, 25, 0, 0, tzinfo=_MSK),
    )
    assert awaiting_handover(caps) is False


def test_coffee_phase_cue_prefixes_and_active_success() -> None:
    # happy: revision-needed and revision-not-needed cue matrices + SUCCESS only on active
    handover_start = workspace_button_style_flags(
        _caps(
            responsibility_phase="awaiting_handover",
            can_complete_revision=False,
            can_submit_loading=True,
            loading_completed=False,
        ),
    )
    handover_start_texts = workspace_action_button_texts(
        handover_start,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=False,
        caps=_caps(
            responsibility_phase="awaiting_handover",
            can_submit_loading=True,
            loading_completed=False,
        ),
    )
    assert handover_start_texts["loading_button_text"].startswith("1️⃣ ")
    assert handover_start_texts["revision_button_text"].startswith("2️⃣ ")
    assert handover_start_texts["loading_photos_button_text"].startswith("3️⃣ ")
    assert handover_start["loading_style_success"] is True
    assert handover_start["revision_style_success"] is False
    assert handover_start["loading_photos_style_success"] is False
    assert handover_start["loading_style_danger"] is False
    assert handover_start["loading_photos_style_danger"] is False

    handover_loaded = workspace_button_style_flags(
        _caps(
            responsibility_phase="awaiting_handover",
            can_complete_revision=True,
            can_submit_loading=True,
            loading_completed=True,
        ),
    )
    handover_loaded_texts = workspace_action_button_texts(
        handover_loaded,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=False,
        caps=_caps(
            responsibility_phase="awaiting_handover",
            can_complete_revision=True,
            loading_completed=True,
        ),
    )
    assert handover_loaded_texts["loading_button_text"].startswith("✅ ")
    assert handover_loaded_texts["revision_button_text"].startswith("2️⃣ ")
    assert handover_loaded_texts["loading_photos_button_text"].startswith("3️⃣ ")
    assert handover_loaded["loading_style_success"] is False
    assert handover_loaded["revision_style_success"] is True
    assert handover_loaded["loading_photos_style_success"] is False

    after_revision = workspace_button_style_flags(
        _caps(
            responsibility_phase="responsible",
            can_complete_revision=False,
            can_submit_loading=True,
            can_submit_loading_photos=True,
            loading_completed=True,
            loading_photos_completed=False,
        ),
        revision_completed_today=True,
    )
    after_revision_texts = workspace_action_button_texts(
        after_revision,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=False,
        caps=_caps(
            responsibility_phase="responsible",
            loading_completed=True,
            can_submit_loading_photos=True,
        ),
        revision_completed_today=True,
    )
    assert after_revision_texts["loading_button_text"].startswith("✅ ")
    assert after_revision_texts["revision_button_text"].startswith("✅ ")
    assert after_revision_texts["loading_photos_button_text"].startswith("3️⃣ ")
    assert after_revision["loading_style_success"] is False
    assert after_revision["revision_style_success"] is False
    assert after_revision["loading_photos_style_success"] is True

    not_needed_start = workspace_button_style_flags(
        _caps(
            responsibility_phase="responsible",
            can_complete_revision=False,
            can_submit_loading=True,
            loading_completed=False,
        ),
    )
    not_needed_start_texts = workspace_action_button_texts(
        not_needed_start,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=False,
        caps=_caps(responsibility_phase="responsible", can_submit_loading=True),
    )
    assert not_needed_start_texts["loading_button_text"].startswith("1️⃣ ")
    assert not_needed_start_texts["revision_button_text"].startswith("❎ ")
    assert not_needed_start_texts["loading_photos_button_text"].startswith("2️⃣ ")
    assert not_needed_start["loading_style_success"] is True
    assert not_needed_start["revision_style_success"] is False
    assert not_needed_start["loading_photos_style_success"] is False
    assert not_needed_start["loading_style_danger"] is False


def test_complete_maintenance_label_without_phase_cue() -> None:
    # edge: «Завершить без фото» без emoji-префикса и без цветного style
    flags = workspace_button_style_flags(
        _caps(
            responsibility_phase="responsible",
            can_complete_maintenance=True,
            can_submit_loading_photos=True,
            loading_completed=True,
        ),
    )
    texts = workspace_action_button_texts(
        flags,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        is_micromarket=False,
        caps=_caps(
            responsibility_phase="responsible",
            can_complete_maintenance=True,
            loading_completed=True,
        ),
        complete_available=True,
    )
    assert texts["complete_maintenance_button_text"] == "Завершить без фото"
    assert flags["complete_maintenance_style_success"] is False
    assert flags["complete_maintenance_style_danger"] is False
