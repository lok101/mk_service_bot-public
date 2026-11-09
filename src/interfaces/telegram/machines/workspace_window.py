from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.enums import ButtonStyle
from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button, Url
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Const, Format

from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.machines.workspace_screen import button_label
from src.interfaces.telegram.machines.workspace_styles import button_style_chain

_REVISION_STYLE = button_style_chain(success_when="revision_style_success")
_LOADING_STYLE = button_style_chain(
    success_when="loading_style_success",
    danger_when="loading_style_danger",
)
_LOADING_PHOTOS_STYLE = button_style_chain(
    success_when="loading_photos_style_success",
    danger_when="loading_photos_style_danger",
)
_MM_CHECKLIST_1_STYLE = button_style_chain(success_when="mm_checklist_1_style_success")
_MM_CHECKLIST_2_STYLE = button_style_chain(success_when="mm_checklist_2_style_success")
_MM_CHECKLIST_3_STYLE = button_style_chain(success_when="mm_checklist_3_style_success")
# Coffee complete is always neutral Style(); MM still keys off danger flag when set.
_COMPLETE_STYLE = (
    Style(style=ButtonStyle.DANGER, when="complete_maintenance_style_danger") | Style()
)


def build_workspace_window(
    handlers: MachineListHandlers,
    getter: Callable[..., Awaitable[dict[str, object]]],
) -> Window:
    return Window(
        Format("{workspace_screen_text}"),
        Url(
            Format("{loading_button_text}"),
            Format("{dialog_data[loading_form_url]}"),
            id="workspace_loading_url",
            when=lambda data, *_: (
                data.get("show_coffee_loading", True) and data.get("loading_has_url")
            ),
            style=_LOADING_STYLE,
        ),
        Button(
            Format("{loading_button_text}"),
            id="workspace_loading_stub",
            on_click=handlers.on_loading_stub,
            when=lambda data, *_: (
                data.get("show_coffee_loading", True) and not data.get("loading_has_url")
            ),
            style=_LOADING_STYLE,
        ),
        Url(
            Format("{revision_button_text}"),
            Format("{dialog_data[revision_form_url]}"),
            id="workspace_revision_url",
            when=lambda data, *_: (
                data.get("show_coffee_revision", True) and data.get("revision_has_url")
            ),
            style=_REVISION_STYLE,
        ),
        Button(
            Format("{revision_button_text}"),
            id="workspace_revision_stub",
            on_click=handlers.on_revision_stub,
            when=lambda data, *_: (
                data.get("show_coffee_revision", True) and not data.get("revision_has_url")
            ),
            style=_REVISION_STYLE,
        ),
        Button(
            Format("{mm_checklist_1_button_text}"),
            id="workspace_mm_checklist_1",
            on_click=handlers.on_mm_checklist_1_click,
            when="show_mm_field_checklist",
            style=_MM_CHECKLIST_1_STYLE,
        ),
        Button(
            Format("{mm_checklist_2_button_text}"),
            id="workspace_mm_checklist_2",
            on_click=handlers.on_mm_checklist_2_click,
            when="show_mm_field_checklist",
            style=_MM_CHECKLIST_2_STYLE,
        ),
        Button(
            Format("{mm_checklist_3_button_text}"),
            id="workspace_mm_checklist_3",
            on_click=handlers.on_mm_checklist_3_click,
            when="show_mm_field_checklist",
            style=_MM_CHECKLIST_3_STYLE,
        ),
        Url(
            Format("{micromarket_inventory_button_text}"),
            Format("{dialog_data[micromarket_inventory_form_url]}"),
            id="workspace_micromarket_inventory_url",
            when=lambda data, *_: (
                data.get("micromarket_inventory_clickable")
                and data.get("micromarket_inventory_has_url")
            ),
        ),
        Button(
            Format("{micromarket_inventory_button_text}"),
            id="workspace_micromarket_inventory",
            on_click=handlers.on_micromarket_inventory_click,
            when=lambda data, *_: (
                data.get("micromarket_inventory_clickable")
                and not data.get("micromarket_inventory_has_url")
            ),
        ),
        Button(
            Format("{micromarket_inventory_button_text}"),
            id="workspace_micromarket_inventory_checklist_stub",
            on_click=handlers.on_micromarket_inventory_checklist_stub,
            when="micromarket_inventory_checklist_locked",
        ),
        Button(
            Format("{micromarket_inventory_button_text}"),
            id="workspace_micromarket_inventory_stub",
            on_click=handlers.on_micromarket_inventory_stub,
            when="micromarket_inventory_show_stub",
        ),
        Button(
            Format("{loading_photos_button_text}"),
            id="workspace_loading_photos",
            on_click=handlers.on_loading_photos_click,
            when="can_submit_loading_photos",
            style=_LOADING_PHOTOS_STYLE,
        ),
        Button(
            Format("{loading_photos_button_text}"),
            id="workspace_loading_photos_onboarding_stub",
            on_click=handlers.on_loading_photos_stub,
            when="loading_photos_onboarding_stub",
            style=_LOADING_PHOTOS_STYLE,
        ),
        Button(
            Format("{loading_photos_button_text}"),
            id="workspace_loading_photos_responsible_stub",
            on_click=handlers.on_loading_photos_stub,
            when="loading_photos_responsible_stub",
            style=_LOADING_PHOTOS_STYLE,
        ),
        Button(
            Format("{complete_maintenance_button_text}"),
            id="workspace_complete_maintenance",
            on_click=handlers.on_maintenance_completed,
            when="can_complete_maintenance",
            style=_COMPLETE_STYLE,
        ),
        Button(
            Format("{complete_maintenance_button_text}"),
            id="workspace_complete_maintenance_stub",
            on_click=handlers.on_complete_maintenance_stub,
            when=lambda data, *_: not data.get("can_complete_maintenance"),
            style=_COMPLETE_STYLE,
        ),
        Button(
            Format("{snack_inventory_button_text}"),
            id="workspace_snack_inventory",
            on_click=handlers.on_snack_inventory_click,
            when=lambda data, *_: (
                data.get("show_snack_inventory", True) and data.get("snack_inventory_available")
            ),
        ),
        Button(
            Format("{snack_inventory_button_text}"),
            id="workspace_snack_inventory_stub",
            on_click=handlers.on_snack_inventory_stub,
            when=lambda data, *_: (
                data.get("show_snack_inventory", True) and data.get("snack_inventory_show_stub")
            ),
        ),
        Button(
            Const(button_label("back")),
            id="workspace_back_to_machines",
            on_click=handlers.on_back_to_machines,
            when="show_maintenance_back",
        ),
        getter=getter,
        state=MachineListState.workspace,
    )
