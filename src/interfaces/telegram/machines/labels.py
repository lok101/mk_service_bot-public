from __future__ import annotations

from beartype import beartype

from src.interfaces.telegram.contracts import TelegramMachineOption

MACHINE_LIST_NAME_WIDTH = 200
_MACHINE_NAME_ADDRESS_SEPARATOR = " | "
_MACHINE_NAME_CODE_SEPARATOR = " - "


@beartype
def format_machine_list_label(
    name: str,
    width: int = MACHINE_LIST_NAME_WIDTH,
) -> str:
    if _MACHINE_NAME_CODE_SEPARATOR not in name:
        return name.ljust(width)

    _, location_name = name.split(_MACHINE_NAME_CODE_SEPARATOR, 1)
    return f"{location_name.ljust(width)}"


@beartype
def machine_option_id(option: TelegramMachineOption) -> str:
    return option.id.value
