from __future__ import annotations

from src.application.reference_data.models import ReferenceDataSourceId
from src.config.google_sheets import GoogleSheetsSettings
from src.infrastructure.composition.factories.reference_data import (
    build_reference_data_source_map,
)


def test_source_map_includes_snack_when_configured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="ss-snack",
        snack_technician_locations_sheet_id=3,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS in m
    assert ReferenceDataSourceId.BOT_USERS in m
    assert m[ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS] == ("ss-snack", 3)


def test_source_map_omits_snack_when_unconfigured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="",
        snack_technician_locations_sheet_id=None,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS not in m


def test_source_map_includes_directory_when_configured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="",
        snack_technician_locations_sheet_id=None,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="ss-tech",
        technicians_directory_sheet_id=7,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert m[ReferenceDataSourceId.TECHNICIANS_DIRECTORY] == ("ss-tech", 7)


def test_source_map_omits_directory_when_unconfigured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="",
        snack_technician_locations_sheet_id=None,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert ReferenceDataSourceId.TECHNICIANS_DIRECTORY not in m


def test_source_map_includes_locations_directory_when_configured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="",
        snack_technician_locations_sheet_id=None,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        locations_directory_spreadsheet_id="ss-loc",
        locations_directory_sheet_id=11,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert m[ReferenceDataSourceId.LOCATIONS_DIRECTORY] == ("ss-loc", 11)


def test_source_map_omits_locations_directory_when_unconfigured() -> None:
    settings = GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="",
        snack_technician_locations_sheet_id=None,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        locations_directory_spreadsheet_id="",
        locations_directory_sheet_id=None,
        credentials_file="",
    )
    m = build_reference_data_source_map(settings)
    assert ReferenceDataSourceId.LOCATIONS_DIRECTORY not in m


def _full_park_settings() -> GoogleSheetsSettings:
    return GoogleSheetsSettings.model_construct(
        coffee_technician_locations_spreadsheet_id="ss",
        coffee_technician_locations_sheet_id=1,
        users_sheet_id=2,
        snack_technician_locations_spreadsheet_id="ss-snack",
        snack_technician_locations_sheet_id=3,
        product_catalog_spreadsheet_id="",
        product_catalog_sheet_id=None,
        technicians_directory_spreadsheet_id="",
        technicians_directory_sheet_id=None,
        locations_directory_spreadsheet_id="ss-loc",
        locations_directory_sheet_id=4,
        credentials_file="",
    )


def test_sync_source_map_omits_park_when_master_data_enabled() -> None:
    m = build_reference_data_source_map(
        _full_park_settings(),
        master_data_enabled=True,
    )
    assert ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS not in m
    assert ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS not in m
    assert ReferenceDataSourceId.LOCATIONS_DIRECTORY not in m
    assert ReferenceDataSourceId.BOT_USERS in m


def test_sync_source_map_includes_park_when_master_data_disabled() -> None:
    m = build_reference_data_source_map(
        _full_park_settings(),
        master_data_enabled=False,
    )
    assert ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS in m
    assert ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS in m
    assert ReferenceDataSourceId.LOCATIONS_DIRECTORY in m


def test_sync_source_map_omits_bot_users_when_users_enabled() -> None:
    sources = build_reference_data_source_map(
        _full_park_settings(),
        master_data_enabled=False,
        master_data_users_enabled=True,
    )
    assert ReferenceDataSourceId.BOT_USERS not in sources


def test_sync_source_map_includes_bot_users_when_users_disabled() -> None:
    sources = build_reference_data_source_map(
        _full_park_settings(),
        master_data_enabled=False,
        master_data_users_enabled=False,
    )
    assert ReferenceDataSourceId.BOT_USERS in sources
