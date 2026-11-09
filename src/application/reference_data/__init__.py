from __future__ import annotations

from src.application.reference_data.clear_location_roster_technician import (
    clear_location_roster_technician,
)
from src.application.reference_data.errors import ReferenceDataUnavailable
from src.application.reference_data.location_roster import (
    ImportLocationRosterFromSheets,
    LocationRosterConflict,
    LocationRosterEntry,
    LocationRosterInvalid,
    LocationRosterPatch,
    SaveLocationRoster,
)
from src.application.reference_data.location_roster_draft import (
    ApplyLocationRosterDraft,
    ApplyLocationRosterDraftResult,
    BootstrapLocationRosterDraft,
    ResetLocationRosterDraft,
    UpsertLocationRosterDraft,
)
from src.application.reference_data.location_roster_draft_compare import roster_draft_is_dirty
from src.application.reference_data.migrate_coffee_locations import (
    migrate_technician_locations_to_coffee,
)
from src.application.reference_data.migrate_product_vitrine import (
    migrate_sheets_product_catalog_to_vitrine,
)
from src.application.reference_data.models import (
    APP_REFERENCE_DATA_SOURCE_IDS,
    ReferenceDataSnapshot,
    ReferenceDataSourceId,
    ReferenceDataSyncError,
    compute_content_hash,
)
from src.application.reference_data.ms_product_catalog import MsEntityKind
from src.application.reference_data.ports import (
    LocationRosterDraftStore,
    LocationRosterStore,
    ReferenceDataSnapshotStore,
    ReferenceDataSourceReader,
)
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.reference_data.staleness import evaluate_staleness
from src.application.reference_data.sync import SyncReferenceData

__all__ = [
    "APP_REFERENCE_DATA_SOURCE_IDS",
    "ApplyLocationRosterDraft",
    "ApplyLocationRosterDraftResult",
    "BootstrapLocationRosterDraft",
    "ImportLocationRosterFromSheets",
    "LocationRosterConflict",
    "LocationRosterDraftStore",
    "LocationRosterEntry",
    "LocationRosterInvalid",
    "LocationRosterPatch",
    "LocationRosterStore",
    "MsEntityKind",
    "ReferenceDataProvider",
    "ReferenceDataSnapshot",
    "ReferenceDataSnapshotStore",
    "ReferenceDataSourceId",
    "ReferenceDataSourceReader",
    "ReferenceDataSyncError",
    "ReferenceDataUnavailable",
    "ResetLocationRosterDraft",
    "SaveLocationRoster",
    "SyncReferenceData",
    "UpsertLocationRosterDraft",
    "clear_location_roster_technician",
    "compute_content_hash",
    "evaluate_staleness",
    "migrate_sheets_product_catalog_to_vitrine",
    "migrate_technician_locations_to_coffee",
    "roster_draft_is_dirty",
]
