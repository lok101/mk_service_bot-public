from __future__ import annotations

from datetime import UTC, datetime, timedelta

import mongomock

from src.infrastructure.external_side_effect_lease import (
    DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS,
)
from src.infrastructure.memory_side_effects import InMemoryExternalSideEffectRegistry
from src.infrastructure.mongodb.external_side_effects import MongoExternalSideEffectRegistry


def test_in_memory_external_side_effect_claim_is_unique() -> None:
    registry = InMemoryExternalSideEffectRegistry()

    first = registry.claim(
        provider="moysklad",
        operation="move",
        idempotency_key="event-1",
        external_code="mk-service-bot:event-1:move",
    )
    second = registry.claim(
        provider="moysklad",
        operation="move",
        idempotency_key="event-1",
        external_code="mk-service-bot:event-1:move",
    )

    assert first.claimed
    assert first.status == "processing"
    assert not second.claimed
    assert second.status == "processing"


def test_in_memory_external_side_effect_reclaims_failed_entry() -> None:
    registry = InMemoryExternalSideEffectRegistry()
    registry.claim(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        external_code="mk-service-bot:event-2:inventory",
    )
    registry.mark_failed(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        error_message="timeout",
    )

    claim = registry.claim(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        external_code="mk-service-bot:event-2:inventory",
    )

    assert claim.claimed
    assert claim.status == "processing"
    assert claim.previous_status == "failed"


def test_mongo_external_side_effect_claim_is_unique() -> None:
    client = mongomock.MongoClient()
    registry = MongoExternalSideEffectRegistry.from_collection(
        client["test_db"]["external_side_effects"],
    )

    first = registry.claim(
        provider="moysklad",
        operation="move",
        idempotency_key="event-1",
        external_code="mk-service-bot:event-1:move",
    )
    second = registry.claim(
        provider="moysklad",
        operation="move",
        idempotency_key="event-1",
        external_code="mk-service-bot:event-1:move",
    )

    assert first.claimed
    assert not second.claimed
    assert second.status == "processing"


def test_mongo_external_side_effect_reclaims_failed_entry() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["external_side_effects"]
    registry = MongoExternalSideEffectRegistry.from_collection(collection)
    registry.claim(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        external_code="mk-service-bot:event-2:inventory",
    )
    registry.mark_failed(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        error_message="timeout",
    )

    claim = registry.claim(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-2",
        external_code="mk-service-bot:event-2:inventory",
    )

    assert claim.claimed
    assert claim.previous_status == "failed"
    document = collection.find_one(
        {
            "provider": "moysklad",
            "operation": "inventory",
            "idempotency_key": "event-2",
        },
    )
    assert document is not None
    assert document["status"] == "processing"


def test_mongo_external_side_effect_reclaims_stale_processing_entry() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["external_side_effects"]
    registry = MongoExternalSideEffectRegistry.from_collection(collection)
    stale_updated_at = datetime.now(tz=UTC) - timedelta(
        seconds=DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS + 1,
    )
    collection.insert_one(
        {
            "provider": "moysklad",
            "operation": "move",
            "idempotency_key": "event-stale",
            "external_code": "mk-service-bot:event-stale:move",
            "status": "processing",
            "external_id": None,
            "last_error": None,
            "created_at": stale_updated_at,
            "updated_at": stale_updated_at,
        },
    )

    claim = registry.claim(
        provider="moysklad",
        operation="move",
        idempotency_key="event-stale",
        external_code="mk-service-bot:event-stale:move",
    )

    assert claim.claimed
    assert claim.status == "processing"
    assert claim.previous_status == "processing"
    document = collection.find_one({"idempotency_key": "event-stale"})
    assert document is not None
    stored_updated_at = document["updated_at"]
    assert isinstance(stored_updated_at, datetime)
    if stored_updated_at.tzinfo is None:
        stored_updated_at = stored_updated_at.replace(tzinfo=UTC)
    assert stored_updated_at > stale_updated_at


def test_in_memory_external_side_effect_reclaims_stale_processing_entry() -> None:
    registry = InMemoryExternalSideEffectRegistry()
    stale_updated_at = datetime.now(tz=UTC) - timedelta(
        seconds=DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS + 1,
    )
    registry._entries[("moysklad", "inventory", "event-stale")] = {
        "provider": "moysklad",
        "operation": "inventory",
        "idempotency_key": "event-stale",
        "external_code": "mk-service-bot:event-stale:inventory",
        "status": "processing",
        "external_id": None,
        "last_error": None,
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
    }

    claim = registry.claim(
        provider="moysklad",
        operation="inventory",
        idempotency_key="event-stale",
        external_code="mk-service-bot:event-stale:inventory",
    )

    assert claim.claimed
    assert claim.previous_status == "processing"
