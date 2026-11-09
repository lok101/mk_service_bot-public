from __future__ import annotations

from src.config.mongodb import MongoSettings


def test_snack_loading_mongo_collection_defaults() -> None:
    settings = MongoSettings()
    assert settings.snack_machine_stock_events_collection == "snack_machine_stock_events"
    assert settings.kit_matrix_deploy_map_collection == "kit_matrix_deploy_map"


def test_snack_sale_unresolved_alert_min_default() -> None:
    from src.config.snack_loading import SnackLoadingSettings

    assert SnackLoadingSettings().sale_unresolved_alert_min == 10
