from __future__ import annotations

import mongomock

from src.application.shared.admin_nav import default_admin_nav_structure
from src.infrastructure.mongodb.admin_nav_structure import MongoAdminNavStructureStore


def test_mongo_nav_structure_round_trip() -> None:
    collection = mongomock.MongoClient().db.admin_nav_structure
    store = MongoAdminNavStructureStore(collection)
    structure = default_admin_nav_structure()
    store.save(structure)
    assert store.get() == structure
    raw = collection.find_one({"_id": "default"})
    assert raw is not None
    assert isinstance(raw["nodes"], list)
    assert "updated_at" in raw
