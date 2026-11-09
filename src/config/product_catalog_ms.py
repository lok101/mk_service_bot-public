from __future__ import annotations

from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


def _parse_folder_ids(value: Any) -> tuple[UUID, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return tuple(item if isinstance(item, UUID) else UUID(str(item)) for item in value)
    raw = value.split(",") if isinstance(value, str) else value
    seen: set[UUID] = set()
    result: list[UUID] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        folder_id = UUID(text)
        if folder_id in seen:
            continue
        seen.add(folder_id)
        result.append(folder_id)
    return tuple(result)


FolderIdsCsv = Annotated[tuple[UUID, ...], NoDecode, BeforeValidator(_parse_folder_ids)]


class ProductCatalogMsSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sync_enabled: bool = Field(
        default=False,
        validation_alias="PRODUCT_CATALOG_MS_SYNC_ENABLED",
    )
    product_folder_ids: FolderIdsCsv = Field(
        default=(),
        validation_alias="PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS",
    )
    sync_interval_seconds: int = Field(
        default=3600,
        validation_alias="PRODUCT_CATALOG_MS_SYNC_INTERVAL_SECONDS",
        ge=60,
    )
    staleness_alert_seconds: int = Field(
        default=7200,
        validation_alias="PRODUCT_CATALOG_MS_STALENESS_ALERT_SECONDS",
        ge=60,
    )

    @model_validator(mode="after")
    def validate_staleness_not_below_interval(self) -> Self:
        if self.staleness_alert_seconds < self.sync_interval_seconds:
            raise ValueError(
                "PRODUCT_CATALOG_MS_STALENESS_ALERT_SECONDS must be >= "
                "PRODUCT_CATALOG_MS_SYNC_INTERVAL_SECONDS",
            )
        return self
