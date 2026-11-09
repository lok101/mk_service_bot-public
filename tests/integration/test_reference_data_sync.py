from __future__ import annotations

import pytest
from pymongo.database import Database

from src.application.reference_data import ReferenceDataProvider, SyncReferenceData
from src.application.reference_data.models import ReferenceDataSourceId
from src.infrastructure.reference_data.mongo_store import (
    MongoReferenceDataSnapshotStore,
)

pytestmark = pytest.mark.integration

_SID = ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS
_HEADER = ["id локации", "имя локации", "имя техника", "id техника"]
_ROW = ["129", "Локация 1", "Иван", "tech-1"]


class _Reader:
    def read_rows(self, source_id):
        return [_HEADER, _ROW]


def test_sync_persists_and_survives_restart(mongo_database: Database) -> None:
    collection = mongo_database["reference_data_snapshots"]
    store = MongoReferenceDataSnapshotStore(_collection=collection)
    provider = ReferenceDataProvider()
    SyncReferenceData(
        reader=_Reader(),
        store=store,
        provider=provider,
        source_ids=(_SID,),
    ).sync_all()

    fresh_store = MongoReferenceDataSnapshotStore(_collection=collection)
    fresh_provider = ReferenceDataProvider()
    fresh_provider.hydrate_from_store(fresh_store)
    assert fresh_provider.coffee_locations_or_none() is not None
