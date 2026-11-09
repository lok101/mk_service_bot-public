from __future__ import annotations

from unittest.mock import MagicMock

from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
    MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.interfaces.telegram.machines.workspace_screen import button_label
from src.interfaces.telegram.machines.workspace_styles import (
    micromarket_phase_cue_prefixes,
    workspace_action_button_texts,
    workspace_button_style_flags,
)
from src.interfaces.telegram.machines.workspace_window import build_workspace_window


def _caps(
    *,
    can_submit_loading_photos: bool = False,
    can_complete_maintenance: bool = False,
    loading_photos_completed: bool = False,
    complete_maintenance_block_reason: str | None = None,
) -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("001"),
        machine_id=MachineId("701"),
        responsibility_phase="responsible",
        can_complete_revision=False,
        can_submit_loading=False,
        can_submit_loading_photos=can_submit_loading_photos,
        can_complete_maintenance=can_complete_maintenance,
        revision_form_link=None,
        loading_photos_completed=loading_photos_completed,
        complete_maintenance_block_reason=complete_maintenance_block_reason,
    )


def test_micromarket_phase_cue_prefixes_inventory_photos() -> None:
    # happy: with checklist_step=3, inventory 4️⃣ until gate clears; photos 5️⃣ → ✅
    pending = micromarket_phase_cue_prefixes(
        _caps(complete_maintenance_block_reason=MICROMARKET_INVENTORY_REQUIRED_REASON),
        checklist_step=3,
    )
    assert pending == ("✅", "✅", "✅", "4️⃣", "5️⃣")

    after_inventory = micromarket_phase_cue_prefixes(
        _caps(
            can_submit_loading_photos=True,
            can_complete_maintenance=True,
        ),
        checklist_step=3,
    )
    assert after_inventory == ("✅", "✅", "✅", "✅", "5️⃣")

    other_blocker = micromarket_phase_cue_prefixes(
        _caps(complete_maintenance_block_reason=MICROMARKET_LOADING_PHOTOS_OPEN_REASON),
        checklist_step=3,
    )
    assert other_blocker == ("✅", "✅", "✅", "✅", "5️⃣")

    photos_done = micromarket_phase_cue_prefixes(
        _caps(
            can_complete_maintenance=True,
            loading_photos_completed=True,
        ),
        checklist_step=3,
    )
    assert photos_done == ("✅", "✅", "✅", "✅", "✅")


def test_micromarket_workspace_button_order_inventory_before_photos() -> None:
    # happy: MM widgets order inventory → photos → complete → back
    window = build_workspace_window(MagicMock(), MagicMock())
    ids = [widget.widget_id for widget in window.keyboard.buttons if widget.widget_id]
    assert ids.index("workspace_micromarket_inventory") < ids.index("workspace_loading_photos")
    assert ids.index("workspace_loading_photos") < ids.index("workspace_complete_maintenance")
    assert ids.index("workspace_complete_maintenance") < ids.index("workspace_back_to_machines")


def test_micromarket_complete_label_plain_without_capability_prefix() -> None:
    # edge: complete is plain label — no phase number, no ✅/⛔
    flags = workspace_button_style_flags(
        _caps(can_complete_maintenance=True, can_submit_loading_photos=True),
        is_micromarket=True,
        checklist_step=3,
    )
    texts = workspace_action_button_texts(
        flags,
        snack_available=False,
        snack_stub=False,
        micromarket_available=True,
        micromarket_stub=False,
        complete_available=True,
        is_micromarket=True,
        caps=_caps(can_complete_maintenance=True, can_submit_loading_photos=True),
        checklist_step=3,
    )
    assert texts["complete_maintenance_button_text"] == button_label("complete_maintenance")
    assert texts["complete_maintenance_button_text"] == "Завершить без фото"
    assert not texts["complete_maintenance_button_text"].startswith("✅")
    assert not texts["complete_maintenance_button_text"].startswith("⛔")
    assert "1️⃣" not in texts["complete_maintenance_button_text"]
    assert "5️⃣" not in texts["complete_maintenance_button_text"]

    assert texts["micromarket_inventory_button_text"].startswith("✅ ")
    assert texts["loading_photos_button_text"].startswith("5️⃣ ")
