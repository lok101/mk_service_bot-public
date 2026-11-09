from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from beartype.roar import BeartypeCallHintReturnViolation
from pymongo import MongoClient
from tests.infrastructure.test_runtime_validation import _prod_settings

from src.config.mongodb import MongoSettings
from src.infrastructure.composition.factories import build_mongo_client
from src.infrastructure.mongodb.connection import create_mongo_client, resolve_collection


def _bare_mongo_client_stub() -> MongoClient[dict[str, Any]]:
    return MongoClient.__new__(MongoClient)


def test_create_mongo_client_passes_driver_kwargs() -> None:
    settings = MongoSettings.model_construct(
        uri="mongodb://user:pass@mongo:27017/db",
        server_selection_timeout_ms=4000,
        connect_timeout_ms=3000,
        socket_timeout_ms=25000,
        max_pool_size=15,
    )
    stub = _bare_mongo_client_stub()
    with patch("src.infrastructure.mongodb.connection.MongoClient") as mongo_cls:
        mongo_cls.return_value = stub
        result = create_mongo_client(settings)
    assert result is stub
    mongo_cls.assert_called_once_with(
        "mongodb://user:pass@mongo:27017/db",
        **settings.client_driver_kwargs(),
    )


def test_create_mongo_client_raises_when_uri_unset() -> None:
    settings = MongoSettings.model_construct(uri=None)
    with pytest.raises(ValueError, match="MongoSettings.uri must be set"):
        create_mongo_client(settings)


def test_build_mongo_client_returns_none_when_uri_unset() -> None:
    settings = _prod_settings(mongodb=MongoSettings.model_construct(uri=None))
    assert build_mongo_client(settings) is None


def test_build_mongo_client_uses_create_mongo_client() -> None:
    settings = _prod_settings()
    stub = _bare_mongo_client_stub()
    with patch(
        "src.infrastructure.composition.factories.persistence.create_mongo_client",
        return_value=stub,
    ) as create_mock:
        result = build_mongo_client(settings)
    assert result is stub
    create_mock.assert_called_once_with(settings.mongodb)


def test_resolve_collection_fallback_client_uses_create_mongo_client() -> None:
    settings = MongoSettings.model_construct(
        uri="mongodb://localhost:27017",
        database="mk_service_bot",
        server_selection_timeout_ms=2000,
        connect_timeout_ms=2000,
        socket_timeout_ms=10000,
        max_pool_size=5,
    )
    collection = MagicMock()
    collection.name = "machine_events"
    database = MagicMock()
    database.__getitem__.return_value = collection
    stub = MagicMock()
    stub.__getitem__.return_value = database
    with (
        patch(
            "src.infrastructure.mongodb.connection.create_mongo_client",
            return_value=stub,
        ) as create_mock,
        pytest.raises(BeartypeCallHintReturnViolation),
    ):
        resolve_collection(
            settings,
            collection_name="machine_events",
            owner="test",
            client=None,
        )
    create_mock.assert_called_once_with(settings)
