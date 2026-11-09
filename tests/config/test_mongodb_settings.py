from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings


def test_mongo_settings_default_driver_kwargs_match_healthcheck_window() -> None:
    settings = MongoSettings.model_construct(uri="mongodb://localhost:27017")
    assert settings.client_driver_kwargs() == {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 5000,
        "socketTimeoutMS": 30000,
        "maxPoolSize": 20,
    }


def test_mongo_settings_custom_driver_kwargs() -> None:
    settings = MongoSettings.model_construct(
        uri="mongodb://localhost:27017",
        server_selection_timeout_ms=3000,
        connect_timeout_ms=2000,
        socket_timeout_ms=15000,
        max_pool_size=10,
    )
    assert settings.client_driver_kwargs() == {
        "serverSelectionTimeoutMS": 3000,
        "connectTimeoutMS": 2000,
        "socketTimeoutMS": 15000,
        "maxPoolSize": 10,
    }


def test_mongo_settings_rejects_server_selection_timeout_above_healthcheck_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "6000")
    with pytest.raises(ValidationError):
        MongoSettings()


def test_mongo_settings_rejects_connect_timeout_above_healthcheck_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONGODB_CONNECT_TIMEOUT_MS", "6000")
    with pytest.raises(ValidationError):
        MongoSettings()
