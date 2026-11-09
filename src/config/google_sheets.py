from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.config._base import ServiceSettingsBase


class GoogleSheetsSettings(ServiceSettingsBase):
    credentials_file: str = Field(
        default="",
        validation_alias="GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE",
    )
    product_catalog_spreadsheet_id: str = Field(
        default="",
        validation_alias="PRODUCT_CATALOG_SPREADSHEET_ID",
    )
    product_catalog_sheet_id: int | None = Field(
        default=None,
        validation_alias="PRODUCT_CATALOG_SHEET_ID",
    )
    coffee_technician_locations_spreadsheet_id: str = Field(
        default="",
        validation_alias="COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID",
    )
    coffee_technician_locations_sheet_id: int | None = Field(
        default=None,
        validation_alias="COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID",
    )
    users_sheet_id: int | None = Field(
        default=None,
        validation_alias="USERS_SHEET_ID",
    )
    snack_technician_locations_spreadsheet_id: str = Field(
        default="",
        validation_alias="SNACK_TECHNICIAN_LOCATIONS_SPREADSHEET_ID",
    )
    snack_technician_locations_sheet_id: int | None = Field(
        default=None,
        validation_alias="SNACK_TECHNICIAN_LOCATIONS_SHEET_ID",
    )
    technicians_directory_spreadsheet_id: str = Field(
        default="",
        validation_alias="TECHNICIANS_DIRECTORY_SPREADSHEET_ID",
    )
    technicians_directory_sheet_id: int | None = Field(
        default=None,
        validation_alias="TECHNICIANS_DIRECTORY_SHEET_ID",
    )
    locations_directory_spreadsheet_id: str = Field(
        default="",
        validation_alias="LOCATIONS_DIRECTORY_SPREADSHEET_ID",
    )
    locations_directory_sheet_id: int | None = Field(
        default=None,
        validation_alias="LOCATIONS_DIRECTORY_SHEET_ID",
    )
    rate_limit_requests_per_window: int = Field(
        default=50,
        validation_alias="GOOGLE_SHEETS_RATE_LIMIT_REQUESTS_PER_WINDOW",
        ge=1,
    )
    rate_limit_window_seconds: float = Field(
        default=60.0,
        validation_alias="GOOGLE_SHEETS_RATE_LIMIT_WINDOW_SECONDS",
        gt=0,
    )
    rate_limit_backoff_seconds: float = Field(
        default=60.0,
        validation_alias="GOOGLE_SHEETS_RATE_LIMIT_BACKOFF_SECONDS",
        gt=0,
    )

    @field_validator(
        "product_catalog_sheet_id",
        "coffee_technician_locations_sheet_id",
        "users_sheet_id",
        "snack_technician_locations_sheet_id",
        "technicians_directory_sheet_id",
        "locations_directory_sheet_id",
        mode="before",
    )
    @classmethod
    def empty_sheet_id_is_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @model_validator(mode="after")
    def validate_product_catalog_pair(self) -> GoogleSheetsSettings:
        has_spreadsheet = bool(self.product_catalog_spreadsheet_id.strip())
        has_sheet = self.product_catalog_sheet_id is not None

        if has_spreadsheet != has_sheet:
            raise ValueError(
                "PRODUCT_CATALOG_SPREADSHEET_ID and PRODUCT_CATALOG_SHEET_ID "
                "must both be set or both be omitted",
            )

        return self

    @model_validator(mode="after")
    def validate_coffee_technician_locations_group(self) -> GoogleSheetsSettings:
        has_spreadsheet = bool(self.coffee_technician_locations_spreadsheet_id.strip())
        has_locations_sheet = self.coffee_technician_locations_sheet_id is not None
        has_users_sheet = self.users_sheet_id is not None

        if has_spreadsheet != has_locations_sheet or has_spreadsheet != has_users_sheet:
            raise ValueError(
                "COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID, "
                "COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID, "
                "and USERS_SHEET_ID must all be set or all be omitted",
            )

        return self

    @model_validator(mode="after")
    def validate_snack_technician_locations_pair(self) -> GoogleSheetsSettings:
        has_spreadsheet = bool(self.snack_technician_locations_spreadsheet_id.strip())
        has_sheet = self.snack_technician_locations_sheet_id is not None

        if has_spreadsheet != has_sheet:
            raise ValueError(
                "SNACK_TECHNICIAN_LOCATIONS_SPREADSHEET_ID and "
                "SNACK_TECHNICIAN_LOCATIONS_SHEET_ID "
                "must both be set or both be omitted",
            )

        return self

    @model_validator(mode="after")
    def validate_technicians_directory_pair(self) -> GoogleSheetsSettings:
        has_spreadsheet = bool(self.technicians_directory_spreadsheet_id.strip())
        has_sheet = self.technicians_directory_sheet_id is not None
        if has_spreadsheet != has_sheet:
            raise ValueError(
                "TECHNICIANS_DIRECTORY_SPREADSHEET_ID and "
                "TECHNICIANS_DIRECTORY_SHEET_ID "
                "must both be set or both be omitted",
            )
        return self

    @model_validator(mode="after")
    def validate_locations_directory_pair(self) -> GoogleSheetsSettings:
        has_spreadsheet = bool(self.locations_directory_spreadsheet_id.strip())
        has_sheet = self.locations_directory_sheet_id is not None
        if has_spreadsheet != has_sheet:
            raise ValueError(
                "LOCATIONS_DIRECTORY_SPREADSHEET_ID and "
                "LOCATIONS_DIRECTORY_SHEET_ID "
                "must both be set or both be omitted",
            )
        return self

    @property
    def is_product_catalog_configured(self) -> bool:
        return bool(self.product_catalog_spreadsheet_id.strip())

    @property
    def is_coffee_technician_locations_configured(self) -> bool:
        return bool(self.coffee_technician_locations_spreadsheet_id.strip())

    @property
    def is_snack_technician_locations_configured(self) -> bool:
        return bool(self.snack_technician_locations_spreadsheet_id.strip())

    @property
    def is_technicians_directory_configured(self) -> bool:
        return bool(self.technicians_directory_spreadsheet_id.strip())

    @property
    def is_locations_directory_configured(self) -> bool:
        return bool(self.locations_directory_spreadsheet_id.strip())
