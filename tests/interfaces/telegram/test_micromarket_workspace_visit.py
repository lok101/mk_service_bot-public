from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.application.master_data import MachineKind
from src.application.micromarket_loading.issue_inventory_link import (
    IssueMicromarketInventoryLink,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ResponsibilityPhase, ServiceCapabilities
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketInventoryFormRegistry,
    InMemoryMicromarketPlanogramStore,
    StaticMachineKindLookup,
    StubMicromarketInventoryFormFactory,
    StubMicromarketInventoryFormsConfig,
)
from src.interfaces.telegram.machines.workspace_getter import build_workspace_payload
from src.interfaces.telegram.machines.workspace_screen import build_workspace_screen_text

_MACHINE = MachineId("701")
_TECH = TechnicianId("tech-1")
_ISSUED_AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _bot_user() -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("10001"),
        name="Test",
        role=BotRole.TECHNICIAN,
        is_active=True,
        telegram_user_id=1,
        technician_id=_TECH,
        company_roles=frozenset(),
    )


def _caps_awaiting() -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=_TECH,
        machine_id=_MACHINE,
        responsibility_phase="awaiting_handover",
        can_complete_revision=False,
        can_submit_loading=False,
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        revision_form_link=None,
        complete_maintenance_block_reason="нужна инвентаризация холодильника",
    )


def _issue_uc() -> IssueMicromarketInventoryLink:
    return IssueMicromarketInventoryLink(
        registry=InMemoryMicromarketInventoryFormRegistry(),
        factory=StubMicromarketInventoryFormFactory(),
        forms_settings=StubMicromarketInventoryFormsConfig(),
        field_forms_public_base_url="https://bot.example.com",
        now_template_id="tpl-now",
        as_of_template_id="tpl-as-of",
        token_entry_id="entry.mm",
        now_token_secret="now-secret",
        as_of_token_secret="as-of-secret",
        clock=lambda: _ISSUED_AT,
        qty_max=30,
    )


def _visit_caps(
    *,
    responsibility_phase: ResponsibilityPhase = "awaiting_handover",
    can_complete_revision: bool = False,
    can_submit_loading: bool = False,
    can_submit_loading_photos: bool = False,
    can_complete_maintenance: bool = False,
    complete_maintenance_block_reason: str | None = None,
    loading_photos_block_reason: str | None = None,
) -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=_TECH,
        machine_id=_MACHINE,
        responsibility_phase=responsibility_phase,
        can_complete_revision=can_complete_revision,
        can_submit_loading=can_submit_loading,
        can_submit_loading_photos=can_submit_loading_photos,
        can_complete_maintenance=can_complete_maintenance,
        revision_form_link=None,
        complete_maintenance_block_reason=complete_maintenance_block_reason,
        loading_photos_block_reason=loading_photos_block_reason,
    )


def _build_workspace_payload(
    *,
    caps: ServiceCapabilities,
    kind: MachineKind = MachineKind.MICRO_MARKET,
    machine_name: str = "MM 701",
) -> dict[str, object]:
    deps = MagicMock()
    deps.service_display_timezone = ZoneInfo("UTC")
    deps.get_service_capabilities.execute.return_value = caps
    deps.issue_snack_inventory_link = None
    deps.snack_inventory_cells = None
    deps.issue_micromarket_inventory_link = _issue_uc()
    deps.micromarket_planogram_store = InMemoryMicromarketPlanogramStore()
    deps.micromarket_stock_store = InMemoryMicromarketDeviceStockStore()
    deps.machine_kind_lookup = StaticMachineKindLookup({_MACHINE.value: kind})
    manager = MagicMock()
    manager.dialog_data = {"machine_id": _MACHINE.value, "machine_name": machine_name}
    from src.interfaces.telegram.machines.maintenance_screen import MaintenanceScreenFlags

    with (
        patch(
            "src.interfaces.telegram.machines.workspace_getter.maintenance_screen_flags",
            return_value=MaintenanceScreenFlags(
                loading_completed=False,
                can_complete_maintenance=True,
                show_maintenance_back=False,
            ),
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_service_line_for_machine",
            return_value="🛠️ Последнее обслуживание: нет данных",
        ),
        patch(
            "src.interfaces.telegram.machines.workspace_getter.last_loading_line_for_machine",
            return_value="📦 Последняя загрузка: нет данных",
        ),
    ):
        return build_workspace_payload(
            deps,
            dialog_manager=manager,
            bot_user=_bot_user(),
            machine_id=_MACHINE,
        )


def test_micromarket_workspace_screen_omits_coffee_handover_lines() -> None:
    text = build_workspace_screen_text(
        caps=_caps_awaiting(),
        machine_name="MM 701",
        machine_id="701",
        last_loading_line="📦 Последняя загрузка: нет данных",
        last_service_line="🛠️ Последнее обслуживание: нет данных",
        form_error=None,
        service_timezone=ZoneInfo("UTC"),
        checked_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        is_micromarket=True,
    )
    assert "При необходимости укажите загрузку" not in text
    assert "Инвентаризация: сегодня" not in text
    assert "MM 701" in text


def test_coffee_workspace_screen_keeps_handover_lines() -> None:
    text = build_workspace_screen_text(
        caps=_caps_awaiting(),
        machine_name="Coffee 1",
        machine_id="101",
        last_loading_line="📦 Последняя загрузка: нет данных",
        last_service_line="🛠️ Последнее обслуживание: нет данных",
        form_error=None,
        service_timezone=ZoneInfo("UTC"),
        checked_at=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
        is_micromarket=False,
    )
    assert "Сначала укажите загрузку, затем инвентаризацию" in text
    assert "Инвентаризация: сегодня" in text


def test_micromarket_workspace_hides_coffee_loading_and_revision() -> None:
    payload = _build_workspace_payload(caps=_visit_caps())
    assert payload["show_coffee_revision"] is False
    assert payload["show_coffee_loading"] is False
    assert payload["loading_has_url"] is False
    assert payload["micromarket_inventory_available"] is True
    assert "Сначала укажите загрузку, затем инвентаризацию" not in str(
        payload["workspace_screen_text"],
    )


def test_micromarket_workspace_skips_photos_onboarding_stub() -> None:
    payload = _build_workspace_payload(
        caps=_visit_caps(
            can_submit_loading_photos=True,
            can_complete_maintenance=True,
        ),
    )
    assert payload["loading_photos_onboarding_stub"] is False
    assert payload["can_submit_loading_photos"] is True
    assert payload["loading_photos_responsible_stub"] is False


def test_micromarket_workspace_photos_stub_when_visit_blocked() -> None:
    payload = _build_workspace_payload(caps=_visit_caps())
    assert payload["loading_photos_onboarding_stub"] is False
    assert payload["can_submit_loading_photos"] is False
    assert payload["loading_photos_responsible_stub"] is True
    assert payload["can_complete_maintenance"] is False


def test_micromarket_workspace_visit_styles_follow_capabilities_not_phase() -> None:
    payload = _build_workspace_payload(
        caps=_visit_caps(
            can_complete_maintenance=True,
            can_submit_loading_photos=True,
        ),
    )
    assert payload["complete_maintenance_style_danger"] is False
    assert payload["loading_photos_style_danger"] is False
    # Decision 4 / MM cues: complete plain; photos still open → 5️⃣
    assert str(payload["complete_maintenance_button_text"]) == "Завершить без фото"
    assert str(payload["loading_photos_button_text"]).startswith("5️⃣")


def test_coffee_workspace_keeps_loading_revision_surface() -> None:
    payload = _build_workspace_payload(
        caps=_visit_caps(),
        kind=MachineKind.COFFEE,
        machine_name="Coffee 1",
    )
    assert payload["show_coffee_revision"] is True
    assert payload["show_coffee_loading"] is True
    assert payload["loading_photos_onboarding_stub"] is True
