from __future__ import annotations

from unittest.mock import MagicMock

from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
    MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.interfaces.telegram.machines.micromarket_field_checklist import (
    clear_checklist_progress,
    get_checklist_step,
    inventory_unlocked_by_checklist,
    sync_checklist_machine,
    try_advance_checklist,
)
from src.interfaces.telegram.machines.workspace_screen import button_label
from src.interfaces.telegram.machines.workspace_styles import (
    micromarket_phase_cue_prefixes,
    workspace_action_button_texts,
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


def test_micromarket_field_checklist_sequential_advance() -> None:
    # happy: 0→1→2→3; cannot skip
    data: dict[str, object] = {}
    assert get_checklist_step(data) == 0
    assert try_advance_checklist(data, target_step=2) is False
    assert try_advance_checklist(data, target_step=1) is True
    assert get_checklist_step(data) == 1
    assert try_advance_checklist(data, target_step=1) is True  # no-op
    assert try_advance_checklist(data, target_step=3) is False
    assert try_advance_checklist(data, target_step=2) is True
    assert try_advance_checklist(data, target_step=3) is True
    assert get_checklist_step(data) == 3


def test_micromarket_inventory_locked_until_checklist_or_already_done() -> None:
    # edge: step<3 locks; already-done unlocks
    assert inventory_unlocked_by_checklist(checklist_step=0, inventory_already_done=False) is False
    assert inventory_unlocked_by_checklist(checklist_step=2, inventory_already_done=False) is False
    assert inventory_unlocked_by_checklist(checklist_step=3, inventory_already_done=False) is True
    assert inventory_unlocked_by_checklist(checklist_step=0, inventory_already_done=True) is True


def test_micromarket_photos_complete_ignore_checklist_step() -> None:
    # edge: button texts for photos/complete do not encode checklist step
    caps = _caps(can_submit_loading_photos=True, can_complete_maintenance=True)
    texts = workspace_action_button_texts(
        {"loading_photos_style_success": True},
        snack_available=False,
        snack_stub=False,
        micromarket_available=True,
        micromarket_stub=False,
        complete_available=True,
        is_micromarket=True,
        caps=caps,
        checklist_step=0,
    )
    assert texts["loading_photos_button_text"].startswith("5️⃣ ")
    assert texts["complete_maintenance_button_text"] == button_label("complete_maintenance")
    texts_after = workspace_action_button_texts(
        {"loading_photos_style_success": True},
        snack_available=False,
        snack_stub=False,
        micromarket_available=True,
        micromarket_stub=False,
        complete_available=True,
        is_micromarket=True,
        caps=caps,
        checklist_step=3,
    )
    assert texts_after["loading_photos_button_text"] == texts["loading_photos_button_text"]
    assert (
        texts_after["complete_maintenance_button_text"] == texts["complete_maintenance_button_text"]
    )


def test_micromarket_field_checklist_clears_on_back() -> None:
    # happy: clear + machine switch reset
    data: dict[str, object] = {}
    sync_checklist_machine(data, machine_id="701")
    assert try_advance_checklist(data, target_step=1) is True
    clear_checklist_progress(data)
    assert get_checklist_step(data) == 0

    sync_checklist_machine(data, machine_id="701")
    assert try_advance_checklist(data, target_step=1) is True
    sync_checklist_machine(data, machine_id="702")
    assert get_checklist_step(data) == 0


def test_micromarket_phase_cue_prefixes_five_steps() -> None:
    # happy: five cues evolve with checklist + inventory/photos
    pending = micromarket_phase_cue_prefixes(
        _caps(complete_maintenance_block_reason=MICROMARKET_INVENTORY_REQUIRED_REASON),
        checklist_step=0,
    )
    assert pending == ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")

    after_two = micromarket_phase_cue_prefixes(
        _caps(complete_maintenance_block_reason=MICROMARKET_INVENTORY_REQUIRED_REASON),
        checklist_step=2,
    )
    assert after_two == ("✅", "✅", "3️⃣", "4️⃣", "5️⃣")

    ready_inventory = micromarket_phase_cue_prefixes(
        _caps(complete_maintenance_block_reason=MICROMARKET_INVENTORY_REQUIRED_REASON),
        checklist_step=3,
    )
    assert ready_inventory == ("✅", "✅", "✅", "4️⃣", "5️⃣")

    after_inv = micromarket_phase_cue_prefixes(
        _caps(
            can_submit_loading_photos=True,
            can_complete_maintenance=True,
            complete_maintenance_block_reason=MICROMARKET_LOADING_PHOTOS_OPEN_REASON,
        ),
        checklist_step=0,
    )
    assert after_inv == ("1️⃣", "2️⃣", "3️⃣", "✅", "5️⃣")

    photos_done = micromarket_phase_cue_prefixes(
        _caps(can_complete_maintenance=True, loading_photos_completed=True),
        checklist_step=3,
    )
    assert photos_done == ("✅", "✅", "✅", "✅", "✅")


def test_micromarket_workspace_button_order_checklist_before_inventory() -> None:
    # happy: checklist buttons before inventory → photos → complete
    window = build_workspace_window(MagicMock(), MagicMock())
    ids = [widget.widget_id for widget in window.keyboard.buttons if widget.widget_id]
    assert ids.index("workspace_mm_checklist_1") < ids.index("workspace_mm_checklist_2")
    assert ids.index("workspace_mm_checklist_2") < ids.index("workspace_mm_checklist_3")
    assert ids.index("workspace_mm_checklist_3") < ids.index("workspace_micromarket_inventory")
    assert ids.index("workspace_micromarket_inventory") < ids.index("workspace_loading_photos")
