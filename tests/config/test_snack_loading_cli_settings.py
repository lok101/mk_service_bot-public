from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from src.config.snack_loading import SnackLoadingSettings


def test_snack_loading_execute_requires_main_warehouse_id() -> None:
    settings = SnackLoadingSettings()
    with pytest.raises(ValueError, match="SNACK_LOADING_MAIN_WAREHOUSE_ID"):
        settings.require_execute_ms_ids(moysklad_api_token=SecretStr("token"))


def test_snack_loading_execute_requires_all_ms_ids() -> None:
    settings = SnackLoadingSettings.model_construct(
        main_warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    with pytest.raises(ValueError, match="SNACK_LOADING_ORGANIZATION_ID"):
        settings.require_execute_ms_ids(moysklad_api_token=SecretStr("token"))


def test_snack_loading_execute_ok_when_ms_ids_complete() -> None:
    settings = SnackLoadingSettings.model_construct(
        main_warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
        organization_id=UUID("00000000-0000-4000-8000-000000000002"),
        project_id=UUID("00000000-0000-4000-8000-000000000003"),
    )
    settings.require_execute_ms_ids(moysklad_api_token=SecretStr("token"))


def test_snack_loading_execute_requires_moysklad_api_token() -> None:
    settings = SnackLoadingSettings.model_construct(
        main_warehouse_id=UUID("00000000-0000-4000-8000-000000000001"),
        organization_id=UUID("00000000-0000-4000-8000-000000000002"),
        project_id=UUID("00000000-0000-4000-8000-000000000003"),
    )
    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        settings.require_execute_ms_ids(moysklad_api_token=None)


def test_snack_loading_cli_defaults_from_spec() -> None:
    settings = SnackLoadingSettings()
    assert settings.min_move_fraction == 0.15
    assert settings.products_path == "Основной склад/СНЕК"
    assert settings.food_products_path == "Основной склад/СНЕК/Еда"
    assert settings.products_recursive is True
    assert settings.warehouses_path == "Торговые автоматы CL/СНЕК, Екатеринбург"
    assert settings.warehouses_recursive is False
    assert settings.handle_food_products is True
    assert settings.machine_interval_seconds == 10.0
    assert settings.batch_gap_seconds == 20.0
    assert settings.main_warehouse_id is None
