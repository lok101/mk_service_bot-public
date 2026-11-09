from __future__ import annotations

import pytest
from tests.infrastructure.composition.test_location_roster_factory import (
    _stub_required_app_env,
)

from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.infrastructure.composition.factories.location_roster import (
    build_location_roster_draft_store,
)


def test_factory_draft_memory_without_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    store = build_location_roster_draft_store(settings, client=None)
    assert isinstance(store, InMemoryLocationRosterDraftStore)
