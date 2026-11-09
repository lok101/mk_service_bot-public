from __future__ import annotations

from pydantic import Field, SecretStr

from src.config._base import ServiceSettingsBase


class MoySkladSettings(ServiceSettingsBase):
    """МойСклад API; поля опциональны до подключения prod-контейнера."""

    api_token: SecretStr | None = Field(
        default=None,
        validation_alias="MOYSKLAD_API_TOKEN",
    )
    organization_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_ORGANIZATION_ID",
    )
    project_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_PROJECT_ID",
    )
    request_timeout_seconds: int = Field(
        default=30,
        validation_alias="MOYSKLAD_REQUEST_TIMEOUT_SECONDS",
    )
    request_attempts: int = Field(
        default=3,
        validation_alias="MOYSKLAD_REQUEST_ATTEMPTS",
    )
    rate_limit_requests_per_window: int = Field(
        default=15,
        validation_alias="MOYSKLAD_RATE_LIMIT_REQUESTS_PER_WINDOW",
        gt=0,
    )
    rate_limit_window_seconds: float = Field(
        default=3.0,
        validation_alias="MOYSKLAD_RATE_LIMIT_WINDOW_SECONDS",
        gt=0,
    )
    rate_limit_backoff_seconds: float = Field(
        default=60.0,
        validation_alias="MOYSKLAD_RATE_LIMIT_BACKOFF_SECONDS",
        gt=0,
    )
    http_max_in_flight: int = Field(
        default=2,
        validation_alias="MOYSKLAD_HTTP_MAX_IN_FLIGHT",
        ge=1,
        le=5,
    )
    http_max_consecutive_high: int = Field(
        default=3,
        validation_alias="MOYSKLAD_HTTP_MAX_CONSECUTIVE_HIGH",
        ge=1,
    )
    demand_agent_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_DEMAND_AGENT_ID",
    )
    main_store_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_MAIN_STORE_ID",
    )
    snack_sales_channel_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_SNACK_SALES_CHANNEL_ID",
    )

    @property
    def is_configured(self) -> bool:
        return self.api_token is not None and bool(
            self.api_token.get_secret_value().strip(),
        )
