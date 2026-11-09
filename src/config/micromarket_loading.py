from __future__ import annotations

from typing import Self
from uuid import UUID

from beartype import beartype
from pydantic import Field, SecretStr, field_validator, model_validator

from src.config._base import ServiceSettingsBase
from src.config.product_catalog_ms import FolderIdsCsv


class MicromarketLoadingSettings(ServiceSettingsBase):
    sale_unresolved_alert_min: int = Field(
        default=1,
        validation_alias="MICROMARKET_SALE_UNRESOLVED_ALERT_MIN",
        ge=1,
    )
    ms_product_folder_ids: FolderIdsCsv = Field(
        default=(),
        validation_alias="MICROMARKET_MS_PRODUCT_FOLDER_IDS",
    )
    field_forms_public_base_url: str = Field(
        default="",
        validation_alias="FIELD_FORMS_PUBLIC_BASE_URL",
    )
    inventory_form_now_template_id: str | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_NOW_TEMPLATE_ID",
    )
    inventory_form_as_of_template_id: str | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_AS_OF_TEMPLATE_ID",
    )
    inventory_form_now_token_secret: SecretStr | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET",
    )
    inventory_form_as_of_token_secret: SecretStr | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_AS_OF_TOKEN_SECRET",
    )
    inventory_form_token_entry_id: str | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_TOKEN_ENTRY_ID",
    )
    inventory_form_copy_folder_id: str | None = Field(
        default=None,
        validation_alias="MICROMARKET_INVENTORY_FORM_COPY_FOLDER_ID",
    )
    execute_enabled: bool = Field(
        default=False,
        validation_alias="MICROMARKET_LOADING_EXECUTE_ENABLED",
    )
    warehouse_gate_enabled: bool = Field(
        default=True,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_GATE_ENABLED",
    )
    main_warehouse_id: UUID | None = Field(
        default=None,
        validation_alias="MICROMARKET_LOADING_MAIN_WAREHOUSE_ID",
    )
    organization_id: UUID | None = Field(
        default=None,
        validation_alias="MICROMARKET_LOADING_ORGANIZATION_ID",
    )
    project_id: UUID | None = Field(
        default=None,
        validation_alias="MICROMARKET_LOADING_PROJECT_ID",
    )
    products_path: str = Field(
        default="",
        validation_alias="MICROMARKET_LOADING_PRODUCTS_PATH",
    )
    products_recursive: bool = Field(
        default=False,
        validation_alias="MICROMARKET_LOADING_PRODUCTS_RECURSIVE",
    )
    warehouses_path: str = Field(
        default="",
        validation_alias="MICROMARKET_LOADING_WAREHOUSES_PATH",
    )
    warehouses_recursive: bool = Field(
        default=False,
        validation_alias="MICROMARKET_LOADING_WAREHOUSES_RECURSIVE",
    )
    warehouse_stock_sync_interval_seconds: int = Field(
        default=180,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_STOCK_SYNC_INTERVAL_SECONDS",
        ge=15,
    )
    warehouse_stock_staleness_alert_seconds: int = Field(
        default=360,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_STOCK_STALENESS_ALERT_SECONDS",
        ge=15,
    )
    warehouse_stock_sync_failure_backoff_seconds: int = Field(
        default=90,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_STOCK_SYNC_FAILURE_BACKOFF_SECONDS",
        ge=0,
    )
    warehouse_stock_staleness_alert_cooldown_seconds: int = Field(
        default=900,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_STOCK_STALENESS_ALERT_COOLDOWN_SECONDS",
        ge=60,
    )
    warehouse_stock_cold_wait_seconds: int = Field(
        default=15,
        validation_alias="MICROMARKET_LOADING_WAREHOUSE_STOCK_COLD_WAIT_SECONDS",
        ge=0,
    )
    move_outbox_poll_interval_seconds: float = Field(
        default=0.25,
        validation_alias="MICROMARKET_LOADING_MOVE_OUTBOX_POLL_INTERVAL_SECONDS",
        gt=0,
    )
    move_outbox_poll_timeout_seconds: float = Field(
        default=90.0,
        validation_alias="MICROMARKET_LOADING_MOVE_OUTBOX_POLL_TIMEOUT_SECONDS",
        gt=0,
    )

    @field_validator("field_forms_public_base_url", mode="before")
    @classmethod
    def _normalize_field_forms_public_base_url(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @model_validator(mode="after")
    def validate_warehouse_stock_staleness_not_below_interval(self) -> Self:
        if (
            self.warehouse_stock_staleness_alert_seconds
            < self.warehouse_stock_sync_interval_seconds
        ):
            raise ValueError(
                "MICROMARKET_LOADING_WAREHOUSE_STOCK_STALENESS_ALERT_SECONDS must be >= "
                "MICROMARKET_LOADING_WAREHOUSE_STOCK_SYNC_INTERVAL_SECONDS",
            )
        return self

    @property
    def is_micromarket_inventory_now_configured(self) -> bool:
        return bool(self.field_forms_public_base_url.strip()) and (
            self.inventory_form_now_token_secret is not None
            and bool(self.inventory_form_now_token_secret.get_secret_value())
        )

    @beartype
    def require_micromarket_inventory_now(self) -> None:
        missing: list[str] = []
        if not self.field_forms_public_base_url.strip():
            missing.append("FIELD_FORMS_PUBLIC_BASE_URL")
        if (
            self.inventory_form_now_token_secret is None
            or not self.inventory_form_now_token_secret.get_secret_value()
        ):
            missing.append("MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET")
        if missing:
            raise ValueError(
                "Micromarket inventory now FieldForm settings incomplete: " + ", ".join(missing),
            )

    @property
    def is_micromarket_inventory_forms_configured(self) -> bool:
        return (
            bool(self.inventory_form_now_template_id)
            and bool(self.inventory_form_as_of_template_id)
            and self.inventory_form_now_token_secret is not None
            and bool(self.inventory_form_now_token_secret.get_secret_value())
            and self.inventory_form_as_of_token_secret is not None
            and bool(self.inventory_form_as_of_token_secret.get_secret_value())
            and bool(self.inventory_form_token_entry_id)
        )

    @property
    def has_any_micromarket_inventory_forms_env(self) -> bool:
        if bool(self.field_forms_public_base_url.strip()):
            return True
        if bool(self.inventory_form_now_template_id):
            return True
        if bool(self.inventory_form_as_of_template_id):
            return True
        if bool(self.inventory_form_token_entry_id):
            return True
        if self.inventory_form_now_token_secret is not None and bool(
            self.inventory_form_now_token_secret.get_secret_value()
        ):
            return True
        return self.inventory_form_as_of_token_secret is not None and bool(
            self.inventory_form_as_of_token_secret.get_secret_value()
        )

    @beartype
    def require_micromarket_inventory_forms(self) -> None:
        missing: list[str] = []
        if not self.inventory_form_now_template_id:
            missing.append("MICROMARKET_INVENTORY_FORM_NOW_TEMPLATE_ID")
        if not self.inventory_form_as_of_template_id:
            missing.append("MICROMARKET_INVENTORY_FORM_AS_OF_TEMPLATE_ID")
        if (
            self.inventory_form_now_token_secret is None
            or not self.inventory_form_now_token_secret.get_secret_value()
        ):
            missing.append("MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET")
        if (
            self.inventory_form_as_of_token_secret is None
            or not self.inventory_form_as_of_token_secret.get_secret_value()
        ):
            missing.append("MICROMARKET_INVENTORY_FORM_AS_OF_TOKEN_SECRET")
        if not self.inventory_form_token_entry_id:
            missing.append("MICROMARKET_INVENTORY_FORM_TOKEN_ENTRY_ID")
        if missing:
            raise ValueError(
                "Micromarket inventory Forms settings incomplete: " + ", ".join(missing),
            )

    @beartype
    def require_execute_dependencies(self) -> list[str]:
        missing: list[str] = []
        if self.main_warehouse_id is None:
            missing.append("MICROMARKET_LOADING_MAIN_WAREHOUSE_ID")
        if self.organization_id is None:
            missing.append("MICROMARKET_LOADING_ORGANIZATION_ID")
        if self.project_id is None:
            missing.append("MICROMARKET_LOADING_PROJECT_ID")
        if not self.products_path.strip():
            missing.append("MICROMARKET_LOADING_PRODUCTS_PATH")
        if not self.warehouses_path.strip():
            missing.append("MICROMARKET_LOADING_WAREHOUSES_PATH")
        return missing
