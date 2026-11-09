from __future__ import annotations

from src.config.master_data import MasterDataSettings


def test_mongo_master_data_stores_uses_config_collection_names() -> None:
    settings = MasterDataSettings()
    assert settings.machines_collection == "master_machines"
    assert settings.locations_collection == "master_locations"
    assert settings.placements_collection == "master_placements"
    assert settings.audit_collection == "master_data_audit"
    assert settings.companies_collection == "master_companies"
