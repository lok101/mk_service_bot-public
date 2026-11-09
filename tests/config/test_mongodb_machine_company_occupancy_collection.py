from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings


def test_mongodb_machine_company_occupancy_collection_default() -> None:
    settings = MongoSettings()
    assert settings.machine_company_occupancy_collection == "machine_company_occupancy"


def test_mongodb_machine_company_occupancy_collection_rejects_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_MACHINE_COMPANY_OCCUPANCY_COLLECTION", "")
    with pytest.raises(ValidationError):
        MongoSettings()
