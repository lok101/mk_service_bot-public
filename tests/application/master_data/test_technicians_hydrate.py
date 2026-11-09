from __future__ import annotations

import pytest

from src.application.master_data import (
    InMemoryTechnicianStore,
    Technician,
    hydrate_technicians_directory,
)
from src.application.reference_data.errors import ReferenceDataUnavailable
from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.config.google_sheets import GoogleSheetsSettings
from src.domain.ids import TechnicianId
from src.infrastructure.composition.factories.reference_data import (
    build_reference_data_source_map,
)


def test_hydrate_empty_store_leaves_directory_unavailable() -> None:
    store = InMemoryTechnicianStore()
    provider = ReferenceDataProvider()
    hydrate_technicians_directory(provider, store)
    with pytest.raises(ReferenceDataUnavailable):
        provider.technicians_directory()


def test_provider_reads_technicians_from_store_when_enabled() -> None:
    store = InMemoryTechnicianStore()
    store.upsert(Technician(TechnicianId("10003"), "╨Ф╨░╨╜╨╕╨╗", True))
    provider = ReferenceDataProvider()
    hydrate_technicians_directory(provider, store)
    assert provider.technicians_directory().names_by_id[TechnicianId("10003")] == "╨Ф╨░╨╜╨╕╨╗"


def test_hydrate_includes_inactive_names() -> None:
    store = InMemoryTechnicianStore()
    store.upsert(Technician(TechnicianId("9"), "Old", False))
    provider = ReferenceDataProvider()
    hydrate_technicians_directory(provider, store)
    assert provider.technicians_directory().names_by_id[TechnicianId("9")] == "Old"


def test_sync_source_map_omits_technicians_directory_when_enabled() -> None:
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
    sources = build_reference_data_source_map(
        settings,
        master_data_enabled=False,
        master_data_users_enabled=False,
        master_data_technicians_enabled=True,
    )
    assert ReferenceDataSourceId.TECHNICIANS_DIRECTORY not in sources
