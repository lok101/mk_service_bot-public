"""Application configuration (pydantic-settings).

When adding a new external service integration, add a dedicated settings class
in ``src/config/<service>.py`` extending ``ServiceSettingsBase`` and register it
on ``Settings`` in ``settings.py``. See ``AGENTS.md`` for agent guidelines.
"""

from src.config.google_forms import (
    GoogleFormsSettings,
)
from src.config.google_sheets import GoogleSheetsSettings
from src.config.moysklad import MoySkladSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.service_rules import ServiceRulesSettings
from src.config.settings import Settings, get_settings, reset_settings
from src.config.telegram import TelegramSettings

__all__ = [
    "GoogleFormsSettings",
    "GoogleSheetsSettings",
    "MoySkladSettings",
    "ServiceCalendarSettings",
    "ServiceRulesSettings",
    "Settings",
    "TelegramSettings",
    "get_settings",
    "reset_settings",
]
