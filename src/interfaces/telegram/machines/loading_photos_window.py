from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram.enums import ContentType
from aiogram_dialog import Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Const, Format

from src.interfaces.telegram.machines.handlers import MachineListHandlers
from src.interfaces.telegram.machines.state import MachineListState

_LABEL_BACK = "Назад"
_LABEL_SEND = "Отправить"
_LABEL_PREV = "◀"
_LABEL_NEXT = "▶"


def build_loading_photos_window(
    handlers: MachineListHandlers,
    getter: Callable[..., Awaitable[dict[str, object]]],
) -> Window:
    return Window(
        Format("{loading_photos_screen_text}"),
        DynamicMedia(selector="media", when="has_photos"),
        MessageInput(
            handlers.on_loading_photos_photo_received,
            content_types=[ContentType.PHOTO],
        ),
        Row(
            Button(
                Const(_LABEL_PREV),
                id="loading_photos_prev",
                on_click=handlers.on_loading_photos_prev,
                when="show_photo_pagination",
            ),
            Button(
                Const(_LABEL_NEXT),
                id="loading_photos_next",
                on_click=handlers.on_loading_photos_next,
                when="show_photo_pagination",
            ),
        ),
        Button(
            Const(_LABEL_BACK),
            id="loading_photos_back",
            on_click=handlers.on_loading_photos_back,
        ),
        Button(
            Const(_LABEL_SEND),
            id="loading_photos_send",
            on_click=handlers.on_loading_photos_send,
            when="can_send_photos",
        ),
        Button(
            Const(_LABEL_SEND),
            id="loading_photos_send_stub",
            on_click=handlers.on_loading_photos_send_stub,
            when=lambda data, *_: not data.get("can_send_photos"),
        ),
        getter=getter,
        state=MachineListState.loading_photos,
    )
