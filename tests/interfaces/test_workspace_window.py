from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from src.interfaces.telegram.machines.workspace_window import build_workspace_window


def _widget_ids(window) -> list[str]:
    return [widget.widget_id for widget in window.keyboard.buttons if widget.widget_id]


def test_workspace_window_puts_loading_before_revision() -> None:
    window = build_workspace_window(MagicMock(), MagicMock())
    ids = _widget_ids(window)

    assert ids.index("workspace_loading_url") < ids.index("workspace_revision_url")
    assert ids.index("workspace_loading_stub") < ids.index("workspace_revision_stub")
    assert ids.index("workspace_revision_url") < ids.index("workspace_micromarket_inventory_url")
    assert ids.index("workspace_micromarket_inventory_url") < ids.index(
        "workspace_micromarket_inventory"
    )
    assert ids.index("workspace_micromarket_inventory") < ids.index("workspace_loading_photos")
    assert ids.index("workspace_loading_photos") < ids.index("workspace_complete_maintenance")
    assert ids.index("workspace_complete_maintenance") < ids.index("workspace_back_to_machines")


def test_workspace_window_uses_format_for_action_labels() -> None:
    src = inspect.getsource(build_workspace_window)
    assert "{revision_button_text}" in src
    assert "{loading_button_text}" in src
    assert "{loading_photos_button_text}" in src
    assert "{complete_maintenance_button_text}" in src
    assert "{snack_inventory_button_text}" in src
    assert "{micromarket_inventory_button_text}" in src
    assert 'button_label("back")' in src or "button_label('back')" in src
