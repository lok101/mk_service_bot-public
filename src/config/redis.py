from __future__ import annotations

from pydantic import Field

from src.config._base import ServiceSettingsBase


class RedisSettings(ServiceSettingsBase):
    uri: str | None = Field(default=None, validation_alias="REDIS_URI")
    fsm_key_prefix: str = Field(
        default="mk_service_bot:fsm",
        validation_alias="REDIS_FSM_KEY_PREFIX",
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.uri and self.uri.strip())
