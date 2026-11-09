from __future__ import annotations

from uuid import UUID

from beartype import beartype
from pydantic import Field, SecretStr

from src.config._base import ServiceSettingsBase


class SnackLoadingSettings(ServiceSettingsBase):
    sale_unresolved_alert_min: int = Field(
        default=10,
        validation_alias="SNACK_SALE_UNRESOLVED_ALERT_MIN",
        ge=1,
    )
    inventory_form_now_template_id: str | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_NOW_TEMPLATE_ID",
    )
    inventory_form_as_of_template_id: str | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_AS_OF_TEMPLATE_ID",
    )
    inventory_form_now_token_secret: SecretStr | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_NOW_TOKEN_SECRET",
    )
    inventory_form_as_of_token_secret: SecretStr | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_AS_OF_TOKEN_SECRET",
    )
    inventory_form_token_entry_id: str | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_TOKEN_ENTRY_ID",
    )
    inventory_form_copy_folder_id: str | None = Field(
        default=None,
        validation_alias="SNACK_INVENTORY_FORM_COPY_FOLDER_ID",
    )
    main_warehouse_id: UUID | None = Field(
        default=None,
        validation_alias="SNACK_LOADING_MAIN_WAREHOUSE_ID",
    )
    organization_id: UUID | None = Field(
        default=None,
        validation_alias="SNACK_LOADING_ORGANIZATION_ID",
    )
    project_id: UUID | None = Field(
        default=None,
        validation_alias="SNACK_LOADING_PROJECT_ID",
    )
    min_move_fraction: float = Field(
        default=0.15,
        validation_alias="SNACK_LOADING_MIN_MOVE_FRACTION",
        ge=0.0,
    )
    products_path: str = Field(
        default="Основной склад/СНЕК",
        validation_alias="SNACK_LOADING_PRODUCTS_PATH",
    )
    food_products_path: str = Field(
        default="Основной склад/СНЕК/Еда",
        validation_alias="SNACK_LOADING_FOOD_PRODUCTS_PATH",
    )
    products_recursive: bool = Field(
        default=True,
        validation_alias="SNACK_LOADING_PRODUCTS_RECURSIVE",
    )
    warehouses_path: str = Field(
        default="Торговые автоматы CL/СНЕК, Екатеринбург",
        validation_alias="SNACK_LOADING_WAREHOUSES_PATH",
    )
    warehouses_recursive: bool = Field(
        default=False,
        validation_alias="SNACK_LOADING_WAREHOUSES_RECURSIVE",
    )
    handle_food_products: bool = Field(
        default=True,
        validation_alias="SNACK_LOADING_HANDLE_FOOD_PRODUCTS",
    )
    machine_interval_seconds: float = Field(
        default=10.0,
        validation_alias="SNACK_LOADING_MACHINE_INTERVAL_SECONDS",
        ge=0.0,
    )
    batch_gap_seconds: float = Field(
        default=20.0,
        validation_alias="SNACK_LOADING_BATCH_GAP_SECONDS",
        ge=0.0,
    )

    @property
    def is_snack_inventory_forms_configured(self) -> bool:
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
    def has_any_snack_inventory_forms_env(self) -> bool:
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
    def require_snack_inventory_forms(self) -> None:
        missing: list[str] = []
        if not self.inventory_form_now_template_id:
            missing.append("SNACK_INVENTORY_FORM_NOW_TEMPLATE_ID")
        if not self.inventory_form_as_of_template_id:
            missing.append("SNACK_INVENTORY_FORM_AS_OF_TEMPLATE_ID")
        if (
            self.inventory_form_now_token_secret is None
            or not self.inventory_form_now_token_secret.get_secret_value()
        ):
            missing.append("SNACK_INVENTORY_FORM_NOW_TOKEN_SECRET")
        if (
            self.inventory_form_as_of_token_secret is None
            or not self.inventory_form_as_of_token_secret.get_secret_value()
        ):
            missing.append("SNACK_INVENTORY_FORM_AS_OF_TOKEN_SECRET")
        if not self.inventory_form_token_entry_id:
            missing.append("SNACK_INVENTORY_FORM_TOKEN_ENTRY_ID")
        if missing:
            raise ValueError(
                "Snack inventory Forms settings incomplete: " + ", ".join(missing),
            )

    @beartype
    def require_execute_ms_ids(self, *, moysklad_api_token: SecretStr | None) -> None:
        missing: list[str] = []
        if self.main_warehouse_id is None:
            missing.append("SNACK_LOADING_MAIN_WAREHOUSE_ID")
        if self.organization_id is None:
            missing.append("SNACK_LOADING_ORGANIZATION_ID")
        if self.project_id is None:
            missing.append("SNACK_LOADING_PROJECT_ID")
        if moysklad_api_token is None or not moysklad_api_token.get_secret_value().strip():
            missing.append("MOYSKLAD_API_TOKEN")
        if missing:
            raise ValueError(
                "Snack loading execute settings incomplete: " + ", ".join(missing),
            )
