from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings


def test_mongodb_reconciliation_drafts_collection_default() -> None:
    settings = MongoSettings()
    assert settings.reconciliation_drafts_collection == "reconciliation_drafts"


def test_mongodb_reconciliation_drafts_collection_rejects_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_RECONCILIATION_DRAFTS_COLLECTION", "")
    with pytest.raises(ValidationError):
        MongoSettings()
