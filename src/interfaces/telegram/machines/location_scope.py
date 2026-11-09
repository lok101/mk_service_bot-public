from __future__ import annotations

from aiogram_dialog import DialogManager
from beartype import beartype

from src.application.machine_operations import LocationListScope

LOCATION_SCOPE_KEY = "location_scope"


@beartype
def start_data_for_scope(scope: LocationListScope) -> dict[str, str]:
    return {LOCATION_SCOPE_KEY: scope.value}


def location_scope_from_manager(dialog_manager: DialogManager) -> LocationListScope:
    raw = dialog_manager.dialog_data.get(LOCATION_SCOPE_KEY)
    if not isinstance(raw, str):
        start_data = dialog_manager.start_data
        if isinstance(start_data, dict):
            fallback = start_data.get(LOCATION_SCOPE_KEY)
            if isinstance(fallback, str):
                raw = fallback

    if raw == LocationListScope.OTHERS.value:
        return LocationListScope.OTHERS

    return LocationListScope.OWN
