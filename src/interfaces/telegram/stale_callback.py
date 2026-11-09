from __future__ import annotations

import logging

from aiogram.types.error_event import ErrorEvent
from beartype import beartype

_LOGGER = logging.getLogger(__name__)

_STALE_NEEDLES = ("query is too old", "query id is invalid")


@beartype
def is_stale_callback_query_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(needle in text for needle in _STALE_NEEDLES)


@beartype
async def handle_stale_callback_query(event: ErrorEvent) -> None:
    if not is_stale_callback_query_error(event.exception):
        raise event.exception
    _LOGGER.warning("stale_telegram_callback_query")
