from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings


def test_admin_nav_structure_collection_default() -> None:
    settings = MongoSettings()
    assert settings.admin_nav_structure_collection == "admin_nav_structure"


def test_admin_nav_structure_collection_rejects_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_ADMIN_NAV_STRUCTURE_COLLECTION", "")
    with pytest.raises(ValidationError):
        MongoSettings()
