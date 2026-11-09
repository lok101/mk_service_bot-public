from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.kitvending import KitVendingSettings
from src.config.master_data import MasterDataSettings


def test_kit_platform_accounts_path_default() -> None:
    settings = KitVendingSettings()
    assert settings.accounts_path.name == "kit_platform_accounts.json"


def test_companies_collection_default() -> None:
    settings = MasterDataSettings()
    assert settings.companies_collection == "master_companies"


def test_companies_admin_enabled_default_false() -> None:
    settings = MasterDataSettings()
    assert settings.companies_enabled is False


def test_companies_collection_empty_string_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_MASTER_COMPANIES_COLLECTION", "   ")
    with pytest.raises(ValidationError):
        MasterDataSettings()
