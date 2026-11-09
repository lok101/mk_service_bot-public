from __future__ import annotations

from pathlib import Path

from beartype import beartype
from pydantic import Field

from src.config._base import ServiceSettingsBase


class KitVendingSettings(ServiceSettingsBase):
    """KitVending API; ingestion выключен по умолчанию (`SALES_INGESTION_ENABLED=false`)."""

    api_base_url: str = Field(
        default="https://api2.kit-invest.ru/APIService.svc",
        validation_alias="KITVENDING_API_BASE_URL",
    )
    accounts_path: Path = Field(
        default=Path("kit_platform_accounts.json"),
        validation_alias="KIT_PLATFORM_ACCOUNTS_PATH",
    )
    catalog_cache_ttl_seconds: int = Field(
        default=21600,
        validation_alias="KITVENDING_CATALOG_CACHE_TTL_SECONDS",
        ge=60,
    )
    requests_per_window: int = Field(
        default=1,
        validation_alias="KITVENDING_REQUESTS_PER_WINDOW",
        ge=1,
    )
    window_seconds: float = Field(
        default=10.0,
        validation_alias="KITVENDING_WINDOW_SECONDS",
        gt=0,
    )
    backoff_seconds: float = Field(
        default=60.0,
        validation_alias="KITVENDING_BACKOFF_SECONDS",
        gt=0,
    )
    initial_lookback_days: int = Field(
        default=7,
        validation_alias="KITVENDING_INITIAL_LOOKBACK_DAYS",
        ge=1,
        le=90,
    )
    ingestion_enabled: bool = Field(default=False, validation_alias="SALES_INGESTION_ENABLED")
    poll_interval_seconds: int = Field(
        default=900,
        validation_alias="SALES_INGEST_POLL_INTERVAL_SECONDS",
        ge=60,
    )
    sale_resolve_alert_cooldown_minutes: int = Field(
        default=60,
        validation_alias="KITVENDING_SALE_RESOLVE_ALERT_COOLDOWN_MINUTES",
        ge=1,
    )
    sales_ingest_overlap_seconds: int = Field(
        default=1800,
        validation_alias="KITVENDING_SALES_INGEST_OVERLAP_SECONDS",
        ge=0,
    )

    @property
    def is_configured(self) -> bool:
        if not bool(self.api_base_url.strip()):
            return False
        return self.accounts_path.is_file()

    @beartype
    def require_configured_for_ingestion(self) -> None:
        if not self.ingestion_enabled:
            return
        from src.infrastructure.integrations.kitvending.platform_accounts import (
            accounts_file_is_valid,
        )

        if accounts_file_is_valid(self.accounts_path):
            return
        raise ValueError(
            "SALES_INGESTION_ENABLED=true, но KitVending accounts не настроены: "
            f"проверьте файл {self.accounts_path}"
        )
