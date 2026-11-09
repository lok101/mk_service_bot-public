from __future__ import annotations

from beartype import beartype

__all__ = [
    "NOTHING_SENT",
    "NOTHING_SENT_MICROMARKET",
    "skipped_names_message",
    "skipped_names_message_micromarket",
]

NOTHING_SENT = "В Kit ничего не отправлено: у активных позиций нет связи с МойСкладом."
NOTHING_SENT_MICROMARKET = "В Kit ничего не отправлено: у активных позиций нет доменного товара."
_SKIPPED_PREFIX = "Не отправлено, нет связи с МойСкладом: "
_SKIPPED_PREFIX_MICROMARKET = "Не отправлено, нет доменного товара: "


@beartype
def skipped_names_message(names: tuple[str, ...]) -> str:
    return _SKIPPED_PREFIX + ", ".join(names)


@beartype
def skipped_names_message_micromarket(names: tuple[str, ...]) -> str:
    return _SKIPPED_PREFIX_MICROMARKET + ", ".join(names)
