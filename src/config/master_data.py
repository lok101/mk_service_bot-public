from __future__ import annotations

from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator

from src.config._base import ServiceSettingsBase


class MasterDataSettings(ServiceSettingsBase):
    enabled: bool = Field(default=False, validation_alias="MASTER_DATA_ENABLED")
    sheets_export_enabled: bool = Field(
        default=False,
        validation_alias="MASTER_DATA_SHEETS_EXPORT_ENABLED",
    )
    mirror_spreadsheet_id: str = Field(
        default="",
        validation_alias="MASTER_DATA_MIRROR_SPREADSHEET_ID",
    )
    mirror_locations_sheet_id: int | None = Field(
        default=None,
        validation_alias="MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID",
    )
    mirror_machines_sheet_id: int | None = Field(
        default=None,
        validation_alias="MASTER_DATA_MIRROR_MACHINES_SHEET_ID",
    )
    session_secret: SecretStr | None = Field(
        default=None,
        validation_alias="ADMIN_SESSION_SECRET",
    )
    telegram_bot_username: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_USERNAME",
    )
    dev_stub_login_enabled: bool = Field(
        default=False,
        validation_alias="ADMIN_DEV_STUB_LOGIN_ENABLED",
    )
    locations_collection: str = Field(
        default="master_locations",
        validation_alias="MONGODB_MASTER_LOCATIONS_COLLECTION",
        min_length=1,
    )
    machines_collection: str = Field(
        default="master_machines",
        validation_alias="MONGODB_MASTER_MACHINES_COLLECTION",
        min_length=1,
    )
    placements_collection: str = Field(
        default="master_placements",
        validation_alias="MONGODB_MASTER_PLACEMENTS_COLLECTION",
        min_length=1,
    )
    counters_collection: str = Field(
        default="master_data_counters",
        validation_alias="MONGODB_MASTER_DATA_COUNTERS_COLLECTION",
        min_length=1,
    )
    audit_collection: str = Field(
        default="master_data_audit",
        validation_alias="MONGODB_MASTER_DATA_AUDIT_COLLECTION",
        min_length=1,
    )
    users_enabled: bool = Field(
        default=False,
        validation_alias="MASTER_DATA_USERS_ENABLED",
    )
    system_users_collection: str = Field(
        default="master_system_users",
        validation_alias="MONGODB_MASTER_SYSTEM_USERS_COLLECTION",
        min_length=1,
    )
    technicians_enabled: bool = Field(
        default=False,
        validation_alias="MASTER_DATA_TECHNICIANS_ENABLED",
    )
    technicians_collection: str = Field(
        default="master_technicians",
        validation_alias="MONGODB_MASTER_TECHNICIANS_COLLECTION",
        min_length=1,
    )
    companies_enabled: bool = Field(
        default=False,
        validation_alias="MASTER_DATA_COMPANIES_ENABLED",
    )
    companies_collection: str = Field(
        default="master_companies",
        validation_alias="MONGODB_MASTER_COMPANIES_COLLECTION",
        min_length=1,
    )
    coffee_machine_models_collection: str = Field(
        default="master_coffee_machine_models",
        validation_alias="MONGODB_MASTER_COFFEE_MACHINE_MODELS_COLLECTION",
        min_length=1,
    )
    stand_types_collection: str = Field(
        default="master_stand_types",
        validation_alias="MONGODB_MASTER_STAND_TYPES_COLLECTION",
        min_length=1,
    )
    stand_colors_collection: str = Field(
        default="master_stand_colors",
        validation_alias="MONGODB_MASTER_STAND_COLORS_COLLECTION",
        min_length=1,
    )

    @field_validator("companies_collection")
    @classmethod
    def validate_companies_collection(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("MONGODB_MASTER_COMPANIES_COLLECTION must not be empty")
        return normalized

    @field_validator(
        "coffee_machine_models_collection",
        "stand_types_collection",
        "stand_colors_collection",
    )
    @classmethod
    def validate_equipment_collection(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("equipment catalog collection name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_enabled_secrets(self) -> Self:
        if not (
            self.enabled or self.users_enabled or self.technicians_enabled or self.companies_enabled
        ):
            return self
        secret = ""
        if self.session_secret is not None:
            secret = self.session_secret.get_secret_value().strip()
        if not secret:
            which = (
                "MASTER_DATA_ENABLED or MASTER_DATA_USERS_ENABLED or "
                "MASTER_DATA_TECHNICIANS_ENABLED or MASTER_DATA_COMPANIES_ENABLED"
            )
            raise ValueError(f"ADMIN_SESSION_SECRET must be set when {which}=true")
        username = self.telegram_bot_username.strip()
        if username.startswith("@"):
            raise ValueError("TELEGRAM_BOT_USERNAME must not start with @")
        if not self.dev_stub_login_enabled and not username:
            raise ValueError(
                "TELEGRAM_BOT_USERNAME must be set when MASTER_DATA_ENABLED or "
                "MASTER_DATA_USERS_ENABLED or MASTER_DATA_TECHNICIANS_ENABLED or "
                "MASTER_DATA_COMPANIES_ENABLED=true "
                "and ADMIN_DEV_STUB_LOGIN_ENABLED=false",
            )
        return self
