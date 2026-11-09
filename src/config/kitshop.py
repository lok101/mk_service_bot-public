from __future__ import annotations

from pathlib import Path

from beartype import beartype
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class KitShopSettings(ServiceSettingsBase):
    """Kit Shop API; ingestion off by default (`KITSHOP_SALES_INGESTION_ENABLED=false`)."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    api_base_url: str = Field(
        default="https://api.kitshop.ru/APIService.svc",
        validation_alias="KITSHOP_API_BASE_URL",
    )
    # Reuse path with Vending — same JSON file; do not duplicate login env.
    accounts_path: Path = Field(
        default=Path("kit_platform_accounts.json"),
        validation_alias="KIT_PLATFORM_ACCOUNTS_PATH",
    )
    requests_per_window: int = Field(
        default=1,
        validation_alias="KITSHOP_REQUESTS_PER_WINDOW",
        ge=1,
    )
    window_seconds: float = Field(
        default=6.0,
        validation_alias="KITSHOP_WINDOW_SECONDS",
        gt=0,
    )
    backoff_seconds: float = Field(
        default=60.0,
        validation_alias="KITSHOP_BACKOFF_SECONDS",
        gt=0,
    )
    max_consecutive_high_requests: int = Field(
        default=3,
        validation_alias="KITSHOP_MAX_CONSECUTIVE_HIGH_REQUESTS",
        ge=1,
    )
    reference_refresh_interval_seconds: int = Field(
        default=3600,
        validation_alias="KITSHOP_REFERENCE_REFRESH_INTERVAL_SECONDS",
        ge=60,
    )
    # Ingest fields used from fragment 03/04; defaults here so Settings is complete.
    ingestion_enabled: bool = Field(
        default=False,
        validation_alias="KITSHOP_SALES_INGESTION_ENABLED",
    )
    discovery_interval_seconds: int = Field(
        default=900,
        validation_alias="KITSHOP_SALES_DISCOVERY_INTERVAL_SECONDS",
        ge=60,
    )
    drain_interval_seconds: int = Field(
        default=6,
        validation_alias="KITSHOP_SALES_DRAIN_INTERVAL_SECONDS",
        ge=1,
    )
    ingest_overlap_seconds: int = Field(
        default=1800,
        validation_alias="KITSHOP_SALES_INGEST_OVERLAP_SECONDS",
        ge=0,
    )
    initial_lookback_days: int = Field(
        default=7,
        validation_alias="KITSHOP_INITIAL_LOOKBACK_DAYS",
        ge=1,
        le=90,
    )
    sale_alert_cooldown_minutes: int = Field(
        default=60,
        validation_alias="KITSHOP_SALE_ALERT_COOLDOWN_MINUTES",
        ge=1,
    )
    catalog_ensure_on_publish_enabled: bool = Field(
        default=False,
        validation_alias="KITSHOP_CATALOG_ENSURE_ON_PUBLISH_ENABLED",
    )
    # Temporary: allow expired peer leaf while CA chain + hostname stay enforced.
    tls_allow_expired_peer_certificate: bool = Field(
        default=False,
        validation_alias="KITSHOP_TLS_ALLOW_EXPIRED_PEER_CERTIFICATE",
    )

    @property
    def is_configured(self) -> bool:
        if not bool(self.api_base_url.strip()):
            return False
        return self.accounts_path.is_file()

    @beartype
    def require_configured_for_ingestion(self) -> None:
        """Fail-fast when ingest enabled without valid kit_shop accounts (wired in fragment 04)."""
        if not self.ingestion_enabled:
            return
        from src.infrastructure.integrations.kitvending.platform_accounts import (
            accounts_file_is_valid,
            load_kit_platform_accounts,
        )

        if not accounts_file_is_valid(self.accounts_path):
            raise ValueError(
                "KITSHOP_SALES_INGESTION_ENABLED=true, но Kit platform accounts не настроены: "
                f"проверьте файл {self.accounts_path}"
            )
        shop_accounts = [
            a
            for a in load_kit_platform_accounts(self.accounts_path)
            if a.platform.value == "kit_shop"
        ]
        if len(shop_accounts) != 1:
            raise ValueError(
                "KITSHOP_SALES_INGESTION_ENABLED=true требует ровно один account "
                f"platform=kit_shop (найдено {len(shop_accounts)}) в {self.accounts_path}"
            )
