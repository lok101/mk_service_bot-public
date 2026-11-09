from __future__ import annotations

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


class ProductProcurementMirrorSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="PRODUCT_PROCUREMENT_MIRROR_ENABLED",
    )
    sync_interval_seconds: int = Field(
        default=3600,
        validation_alias="PRODUCT_PROCUREMENT_MIRROR_SYNC_INTERVAL_SECONDS",
        ge=60,
    )
    supply_concurrency: int = Field(
        default=2,
        validation_alias="PRODUCT_PROCUREMENT_MIRROR_SUPPLY_CONCURRENCY",
        ge=1,
        le=32,
    )
    collection: str = Field(
        default="product_procurement_mirror",
        validation_alias="MONGODB_PRODUCT_PROCUREMENT_MIRROR_COLLECTION",
        min_length=1,
    )
    attr_package_quantity_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_ATTR_PACKAGE_QUANTITY_ID",
    )
    attr_supplier_product_name_id: str = Field(
        default="",
        validation_alias="MOYSKLAD_ATTR_SUPPLIER_PRODUCT_NAME_ID",
    )
