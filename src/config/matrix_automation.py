from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase
from src.config.product_catalog_ms import FolderIdsCsv


class MatrixAutomationSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    google_sheets_spreadsheet_id: str = Field(
        default="",
        validation_alias="MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID",
    )
    product_multipliers_sheet_id: int | None = Field(
        default=None,
        validation_alias="MATRIX_PRODUCT_MULTIPLIERS_SHEET_ID",
        ge=0,
    )
    max_price_delta_pct: Decimal = Field(
        default=Decimal("30"),
        validation_alias="MATRIX_MAX_PRICE_DELTA_PCT",
        ge=0,
    )
    scale_price_min: Decimal = Field(
        default=Decimal("10"),
        validation_alias="MATRIX_SCALE_PRICE_MIN",
        gt=0,
    )
    scale_price_max: Decimal = Field(
        default=Decimal("500"),
        validation_alias="MATRIX_SCALE_PRICE_MAX",
        gt=0,
    )
    scale_rate_min: Decimal = Field(
        default=Decimal("0.1"),
        validation_alias="MATRIX_SCALE_RATE_MIN",
        gt=0,
    )
    scale_rate_max: Decimal = Field(
        default=Decimal("2.0"),
        validation_alias="MATRIX_SCALE_RATE_MAX",
        gt=0,
    )
    curvature_min: Decimal = Field(
        default=Decimal("0.5"),
        validation_alias="MATRIX_CURVATURE_MIN",
        gt=0,
    )
    curvature_max: Decimal = Field(
        default=Decimal("3"),
        validation_alias="MATRIX_CURVATURE_MAX",
        gt=0,
    )
    margin_floor_min: Decimal = Field(
        default=Decimal("10"),
        validation_alias="MATRIX_MARGIN_FLOOR_MIN",
        gt=0,
    )
    margin_floor_max: Decimal = Field(
        default=Decimal("100"),
        validation_alias="MATRIX_MARGIN_FLOOR_MAX",
        gt=0,
    )
    product_multiplier_min: Decimal = Field(
        default=Decimal("0.8"),
        validation_alias="MATRIX_PRODUCT_MULTIPLIER_MIN",
        gt=0,
    )
    product_multiplier_max: Decimal = Field(
        default=Decimal("3.0"),
        validation_alias="MATRIX_PRODUCT_MULTIPLIER_MAX",
        gt=0,
    )
    matrix_multiplier_min: Decimal = Field(
        default=Decimal("0.8"),
        validation_alias="MATRIX_MATRIX_MULTIPLIER_MIN",
        gt=0,
    )
    matrix_multiplier_max: Decimal = Field(
        default=Decimal("3.0"),
        validation_alias="MATRIX_MATRIX_MULTIPLIER_MAX",
        gt=0,
    )
    blocking_cell_price: Decimal = Field(
        default=Decimal("999"),
        validation_alias="MATRIX_BLOCKING_CELL_PRICE",
        gt=0,
    )
    load_timeout_seconds: int = Field(
        default=300,
        validation_alias="MATRIX_LOAD_TIMEOUT_SECONDS",
        ge=1,
    )
    apply_timeout_seconds: int = Field(
        default=300,
        validation_alias="MATRIX_APPLY_TIMEOUT_SECONDS",
        ge=1,
    )
    status_poll_interval_seconds: int = Field(
        default=15,
        validation_alias="MATRIX_STATUS_POLL_INTERVAL_SECONDS",
        ge=1,
    )
    command_send_delay_seconds: int = Field(
        default=7,
        validation_alias="MATRIX_COMMAND_SEND_DELAY_SECONDS",
        ge=1,
    )
    poll_api_max_retries: int = Field(
        default=10,
        validation_alias="MATRIX_POLL_API_MAX_RETRIES",
        ge=1,
    )
    retry_send_command_delay_seconds: int = Field(
        default=10,
        validation_alias="MATRIX_RETRY_SEND_COMMAND_DELAY_SECONDS",
        ge=1,
    )
    blocking_cell_label: str = Field(default="БЛОК", validation_alias="MATRIX_BLOCKING_CELL_LABEL")
    worker_enabled: bool = Field(default=False, validation_alias="MATRIX_WORKER_ENABLED")
    layout_master_enabled: bool = Field(
        default=False,
        validation_alias="MATRIX_LAYOUT_MASTER_ENABLED",
    )
    sku_catalog_master_enabled: bool = Field(
        default=False,
        validation_alias="MATRIX_SKU_CATALOG_MASTER_ENABLED",
    )
    sku_catalog_ms_product_folder_ids: FolderIdsCsv = Field(
        default=(),
        validation_alias="MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS",
    )
    worker_cron_hour: int = Field(
        default=3,
        validation_alias="MATRIX_WORKER_CRON_HOUR",
        ge=0,
        le=23,
    )
    kept_alert_pct: Decimal = Field(
        default=Decimal("20"),
        validation_alias="MATRIX_KEPT_ALERT_PCT",
        ge=0,
        le=100,
    )
    substitution_guard_enabled: bool = Field(
        default=False,
        validation_alias="MATRIX_SUBSTITUTION_GUARD_ENABLED",
    )
    supply_fetch_concurrency: int = Field(
        default=2,
        validation_alias="MATRIX_SUPPLY_FETCH_CONCURRENCY",
        ge=1,
        le=32,
    )

    @field_validator("blocking_cell_label")
    @classmethod
    def validate_blocking_cell_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MATRIX_BLOCKING_CELL_LABEL must not be empty")
        return normalized

    @field_validator(
        "max_price_delta_pct",
        "scale_price_min",
        "scale_price_max",
        "scale_rate_min",
        "scale_rate_max",
        "curvature_min",
        "curvature_max",
        "margin_floor_min",
        "margin_floor_max",
        "product_multiplier_min",
        "product_multiplier_max",
        "matrix_multiplier_min",
        "matrix_multiplier_max",
        "blocking_cell_price",
        "kept_alert_pct",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return value
        if value is None or value == "":
            return value
        return Decimal(str(value).replace(",", "."))

    @field_validator(
        "product_multipliers_sheet_id",
        mode="before",
    )
    @classmethod
    def empty_sheet_id_is_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.scale_price_min > self.scale_price_max:
            raise ValueError(
                "MATRIX_SCALE_PRICE_MIN must be <= MATRIX_SCALE_PRICE_MAX",
            )
        if self.scale_rate_min > self.scale_rate_max:
            raise ValueError(
                "MATRIX_SCALE_RATE_MIN must be <= MATRIX_SCALE_RATE_MAX",
            )
        if self.curvature_min > self.curvature_max:
            raise ValueError(
                "MATRIX_CURVATURE_MIN must be <= MATRIX_CURVATURE_MAX",
            )
        if self.margin_floor_min > self.margin_floor_max:
            raise ValueError(
                "MATRIX_MARGIN_FLOOR_MIN must be <= MATRIX_MARGIN_FLOOR_MAX",
            )
        if self.product_multiplier_min > self.product_multiplier_max:
            raise ValueError(
                "MATRIX_PRODUCT_MULTIPLIER_MIN must be <= MATRIX_PRODUCT_MULTIPLIER_MAX",
            )
        if self.matrix_multiplier_min > self.matrix_multiplier_max:
            raise ValueError(
                "MATRIX_MATRIX_MULTIPLIER_MIN must be <= MATRIX_MATRIX_MULTIPLIER_MAX",
            )
        if not (self.product_multiplier_min <= Decimal("1") <= self.product_multiplier_max):
            raise ValueError(
                "MATRIX_PRODUCT_MULTIPLIER_MIN must be <= 1 <= MATRIX_PRODUCT_MULTIPLIER_MAX",
            )
        return self

    @model_validator(mode="after")
    def validate_spreadsheet_sheet_ids(self) -> Self:
        if not self.google_sheets_spreadsheet_id:
            return self
        missing = [
            name
            for name, value in (
                (
                    "MATRIX_PRODUCT_MULTIPLIERS_SHEET_ID",
                    self.product_multipliers_sheet_id,
                ),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"When MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID is set, required: {', '.join(missing)}",
            )
        return self

    @model_validator(mode="after")
    def validate_worker_enabled_requires_spreadsheet(self) -> Self:
        if not self.worker_enabled:
            return self
        if not self.google_sheets_spreadsheet_id.strip():
            raise ValueError(
                "When MATRIX_WORKER_ENABLED=true, MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID is required",
            )
        return self
