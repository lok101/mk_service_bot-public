from __future__ import annotations

from pydantic import Field, SecretStr

from src.config._base import ServiceSettingsBase


class GoogleFormsSettings(ServiceSettingsBase):
    webhook_secret: SecretStr = Field(
        validation_alias="GOOGLE_FORMS_WEBHOOK_SECRET",
    )
    revision_form_token_secret: SecretStr = Field(
        validation_alias="REVISION_FORM_TOKEN_SECRET",
    )
    loading_form_token_secret: SecretStr = Field(
        validation_alias="LOADING_FORM_TOKEN_SECRET",
    )
    revision_form_url: str = Field(
        validation_alias="REVISION_FORM_URL",
    )
    loading_form_url: str = Field(
        validation_alias="LOADING_FORM_URL",
    )
    revision_form_token_entry_id: str = Field(
        validation_alias="REVISION_FORM_TOKEN_ENTRY_ID",
    )
    loading_form_token_entry_id: str = Field(
        validation_alias="LOADING_FORM_TOKEN_ENTRY_ID",
    )
    technician_warehouse_inventory_form_url: str = Field(
        default="",
        validation_alias="TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
    )
    technician_warehouse_inventory_form_token_secret: SecretStr = Field(
        validation_alias="TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
    )
    technician_warehouse_inventory_form_token_entry_id: str = Field(
        default="",
        validation_alias="TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
    )
    token_field_name: str = Field(
        validation_alias="GOOGLE_FORM_TOKEN_FIELD_NAME",
    )
    form_token_ttl_hours: float = Field(
        default=24.0,
        validation_alias="FORM_TOKEN_TTL_HOURS",
        gt=0,
    )
    webhook_signature_max_age_seconds: int = Field(
        default=300,
        validation_alias="GOOGLE_FORMS_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS",
        gt=0,
    )
    webhook_max_body_bytes: int = Field(
        default=3_000_000,
        validation_alias="GOOGLE_FORMS_WEBHOOK_MAX_BODY_BYTES",
        gt=0,
    )
    webhook_rate_limit_per_minute: int = Field(
        default=60,
        validation_alias="GOOGLE_FORMS_WEBHOOK_RATE_LIMIT",
        ge=0,
    )
    user_oauth_credentials_file: str = Field(
        default="",
        validation_alias="GOOGLE_FORMS_USER_OAUTH_CREDENTIALS_FILE",
    )
    inventory_form_qty_max: int = Field(
        default=99,
        validation_alias="INVENTORY_FORM_QTY_MAX",
        ge=0,
    )
