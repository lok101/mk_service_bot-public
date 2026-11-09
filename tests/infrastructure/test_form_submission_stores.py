from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock
import pytest

from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
    FrozenProductSpec,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.mongodb.form_submissions import MongoFormSubmissionStore
from src.infrastructure.testing.stubs import (
    MappingProductCatalogResolver,
    build_test_frozen_inventory_lines,
)

_FORM_TOKEN_FIELD_NAME = "Код заявки."
_NOW = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_TECHNICIAN_ID = TechnicianId("tech-1")


def _memory_store() -> InMemoryFormSubmissionStore:
    return InMemoryFormSubmissionStore()


def _mongo_store() -> MongoFormSubmissionStore:
    collection = mongomock.MongoClient()["test_db"]["form_submissions"]
    return MongoFormSubmissionStore.from_collection(collection)


def _save_warehouse_pending(
    store: InMemoryFormSubmissionStore | MongoFormSubmissionStore,
) -> FormSubmissionSnapshot:
    return store.save_pending(
        form_token="warehouse-token",
        form_id="form-1",
        purpose="technician_warehouse_inventory",
        technician_id=_TECHNICIAN_ID,
        machine_id=None,
        submitted_at=_NOW,
        answers=(FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="warehouse-token"),),
        validated_lines=(),
    )


def _sample_validated_lines(
    answers: tuple[FormAnswer, ...],
    *,
    mode_purpose: str = "loading",
) -> tuple[FrozenInventoryLine, ...]:
    return build_test_frozen_inventory_lines(
        answers,
        MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD_NAME,
        mode_purpose=mode_purpose,
    )


def _sample_answers(*, coffee_value: str = "1") -> tuple[FormAnswer, ...]:
    return (
        FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="token-1"),
        FormAnswer(title="Кофе", value=coffee_value),
    )


def test_in_memory_form_submission_store_persists_occurred_at() -> None:
    store = InMemoryFormSubmissionStore()
    submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    occurred_at = datetime(2026, 5, 20, 10, 5, tzinfo=UTC)
    answers = _sample_answers()
    snapshot = store.save_pending(
        form_token="token-1",
        form_id="form-1",
        purpose="loading",
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        submitted_at=submitted_at,
        answers=answers,
        validated_lines=_sample_validated_lines(answers),
    )

    accepted = store.mark_accepted(
        snapshot.submission_id,
        event_id="event-1",
        occurred_at=occurred_at,
    )

    assert accepted.status == "accepted"
    assert accepted.event_id == "event-1"
    assert accepted.occurred_at == occurred_at
    assert len(accepted.validated_lines) == 1


def test_mongo_form_submission_store_persists_validated_lines() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["form_submissions"]
    store = MongoFormSubmissionStore.from_collection(collection)
    submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    answers = _sample_answers(coffee_value="2")
    validated_lines = _sample_validated_lines(answers, mode_purpose="revision")
    snapshot = store.save_pending(
        form_token="token-2",
        form_id="form-2",
        purpose="revision",
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        submitted_at=submitted_at,
        answers=answers,
        validated_lines=validated_lines,
    )

    loaded = store.get_by_form_token("token-2", "revision")

    assert loaded is not None
    assert len(loaded.validated_lines) == 1
    line = loaded.validated_lines[0]
    assert line.form_title == "Кофе"
    assert line.quantity == Decimal("2")
    assert line.product_spec.product_code == "coffee-1"
    assert snapshot.submission_id == loaded.submission_id


def test_mongo_form_submission_store_persists_occurred_at() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["form_submissions"]
    store = MongoFormSubmissionStore.from_collection(collection)
    submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    occurred_at = datetime(2026, 5, 20, 10, 7, tzinfo=UTC)
    answers = (FormAnswer(title="Кофе", value="2"),)
    validated_lines = (
        FrozenInventoryLine(
            form_title="Кофе",
            product_spec=FrozenProductSpec(
                product_code="coffee-1",
                name="Кофе",
                unit=ProductUnit.GRAM,
                pack_size=Decimal("20"),
                moysklad_quantity_factor=default_moysklad_quantity_factor(ProductUnit.GRAM),
            ),
            quantity=Decimal("2"),
        ),
    )
    snapshot = store.save_pending(
        form_token="token-2",
        form_id="form-2",
        purpose="revision",
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        submitted_at=submitted_at,
        answers=answers,
        validated_lines=validated_lines,
    )

    store.mark_accepted(
        snapshot.submission_id,
        event_id="event-2",
        occurred_at=occurred_at,
        revision_id="rev-2",
    )
    loaded = store.get_by_event_id("event-2")

    assert loaded is not None
    assert loaded.status == "accepted"
    assert loaded.occurred_at == occurred_at.replace(tzinfo=None)
    assert loaded.revision_id == "rev-2"


def _rejected_submission_args(
    *,
    form_token: str,
    answers: tuple[FormAnswer, ...],
    submitted_at: datetime,
    validated_lines: tuple[FrozenInventoryLine, ...],
) -> dict[str, object]:
    return {
        "form_token": form_token,
        "form_id": "form-retry",
        "purpose": "loading",
        "technician_id": TechnicianId("tech-a"),
        "machine_id": MachineId("vm-01"),
        "submitted_at": submitted_at,
        "answers": answers,
        "validated_lines": validated_lines,
    }


def test_in_memory_form_submission_store_updates_answers_on_rejected_retry() -> None:
    store = InMemoryFormSubmissionStore()
    first_submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    second_submitted_at = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)
    first_answers = _sample_answers(coffee_value="1")
    second_answers = _sample_answers(coffee_value="5")

    snapshot = store.save_pending(
        **_rejected_submission_args(
            form_token="token-retry",
            answers=first_answers,
            submitted_at=first_submitted_at,
            validated_lines=_sample_validated_lines(first_answers),
        ),
    )
    store.mark_rejected(snapshot.submission_id, reason="loading not allowed")

    retried = store.save_pending(
        **_rejected_submission_args(
            form_token="token-retry",
            answers=second_answers,
            submitted_at=second_submitted_at,
            validated_lines=_sample_validated_lines(second_answers),
        ),
    )

    assert retried.submission_id == snapshot.submission_id
    assert retried.status == "pending"
    assert retried.answers == second_answers
    assert retried.validated_lines[0].quantity == Decimal("5")
    assert retried.submitted_at == second_submitted_at
    assert retried.rejection_reason is None


def test_in_memory_form_submission_store_updates_answers_on_pending_retry() -> None:
    store = InMemoryFormSubmissionStore()
    first_submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    second_submitted_at = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)
    first_answers = _sample_answers(coffee_value="1")
    second_answers = _sample_answers(coffee_value="7")

    snapshot = store.save_pending(
        **_rejected_submission_args(
            form_token="token-pending",
            answers=first_answers,
            submitted_at=first_submitted_at,
            validated_lines=_sample_validated_lines(first_answers),
        ),
    )

    retried = store.save_pending(
        **_rejected_submission_args(
            form_token="token-pending",
            answers=second_answers,
            submitted_at=second_submitted_at,
            validated_lines=_sample_validated_lines(second_answers),
        ),
    )

    assert retried.submission_id == snapshot.submission_id
    assert retried.status == "pending"
    assert retried.answers == second_answers
    assert retried.validated_lines[0].quantity == Decimal("7")
    assert retried.submitted_at == second_submitted_at


def test_mongo_form_submission_store_updates_answers_on_pending_retry() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["form_submissions"]
    store = MongoFormSubmissionStore.from_collection(collection)
    first_submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    second_submitted_at = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)
    first_answers = _sample_answers(coffee_value="1")
    second_answers = _sample_answers(coffee_value="7")

    snapshot = store.save_pending(
        **_rejected_submission_args(
            form_token="token-pending-mongo",
            answers=first_answers,
            submitted_at=first_submitted_at,
            validated_lines=_sample_validated_lines(first_answers),
        ),
    )

    retried = store.save_pending(
        **_rejected_submission_args(
            form_token="token-pending-mongo",
            answers=second_answers,
            submitted_at=second_submitted_at,
            validated_lines=_sample_validated_lines(second_answers),
        ),
    )

    loaded = store.get_by_form_token("token-pending-mongo", "loading")

    assert loaded is not None
    assert retried.submission_id == snapshot.submission_id
    assert loaded.status == "pending"
    assert loaded.answers == second_answers
    assert loaded.validated_lines[0].quantity == Decimal("7")
    assert loaded.submitted_at == second_submitted_at.replace(tzinfo=None)


def test_mongo_form_submission_store_updates_answers_on_rejected_retry() -> None:
    client = mongomock.MongoClient()
    collection = client["test_db"]["form_submissions"]
    store = MongoFormSubmissionStore.from_collection(collection)
    first_submitted_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    second_submitted_at = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)
    first_answers = _sample_answers(coffee_value="1")
    second_answers = _sample_answers(coffee_value="5")

    snapshot = store.save_pending(
        **_rejected_submission_args(
            form_token="token-retry-mongo",
            answers=first_answers,
            submitted_at=first_submitted_at,
            validated_lines=_sample_validated_lines(first_answers),
        ),
    )
    store.mark_rejected(snapshot.submission_id, reason="loading not allowed")

    retried = store.save_pending(
        **_rejected_submission_args(
            form_token="token-retry-mongo",
            answers=second_answers,
            submitted_at=second_submitted_at,
            validated_lines=_sample_validated_lines(second_answers),
        ),
    )

    loaded = store.get_by_form_token("token-retry-mongo", "loading")

    assert loaded is not None
    assert retried.submission_id == snapshot.submission_id
    assert loaded.status == "pending"
    assert loaded.answers == second_answers
    assert loaded.validated_lines[0].quantity == Decimal("5")
    assert loaded.submitted_at == second_submitted_at.replace(tzinfo=None)
    assert loaded.rejection_reason is None


@pytest.mark.parametrize("store_factory", [_memory_store, _mongo_store])
def test_warehouse_submission_persists_without_machine_id(store_factory) -> None:
    store = store_factory()
    snapshot = store.save_pending(
        form_token="warehouse-token",
        form_id="form-1",
        purpose="technician_warehouse_inventory",
        technician_id=TechnicianId("tech-1"),
        machine_id=None,
        submitted_at=_NOW,
        answers=(FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="warehouse-token"),),
        validated_lines=(),
    )
    assert snapshot.machine_id is None
    assert snapshot.purpose == "technician_warehouse_inventory"


@pytest.mark.parametrize("store_factory", [_memory_store, _mongo_store])
def test_warehouse_submission_unique_by_token_and_purpose(store_factory) -> None:
    store = store_factory()
    first = _save_warehouse_pending(store)
    second = _save_warehouse_pending(store)
    assert second.submission_id == first.submission_id


@pytest.mark.parametrize("store_factory", [_memory_store, _mongo_store])
def test_revision_snapshot_still_requires_machine_id(store_factory) -> None:
    store = store_factory()
    with pytest.raises(ValueError, match="machine_id"):
        store.save_pending(
            form_token="token-rev",
            form_id="form-1",
            purpose="revision",
            technician_id=_TECHNICIAN_ID,
            machine_id=None,
            submitted_at=_NOW,
            answers=(FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="token-rev"),),
            validated_lines=(),
        )


@pytest.mark.parametrize("store_factory", [_memory_store, _mongo_store])
def test_warehouse_accepted_persists_baseline_flag(store_factory) -> None:
    store = store_factory()
    pending = _save_warehouse_pending(store)
    accepted = store.mark_accepted(
        pending.submission_id,
        event_id="event-1",
        occurred_at=_NOW,
        revision_id="inventory-1",
        warehouse_inventory_baseline=True,
    )
    loaded = store.get_by_form_token("warehouse-token", "technician_warehouse_inventory")
    assert accepted.warehouse_inventory_baseline is True
    assert loaded is not None
    assert loaded.warehouse_inventory_baseline is True
    assert loaded.status == "accepted"


def test_mongo_pending_omits_event_id_so_sparse_unique_allows_second_pending() -> None:
    """Regression: event_id:null breaks unique sparse index (only one pending in DB)."""
    client = mongomock.MongoClient()
    collection = client["test_db"]["form_submissions"]
    store = MongoFormSubmissionStore.from_collection(collection)
    answers_a = (
        FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="token-a"),
        FormAnswer(title="Кофе", value="1"),
    )
    answers_b = (
        FormAnswer(title=_FORM_TOKEN_FIELD_NAME, value="token-b"),
        FormAnswer(title="Кофе", value="2"),
    )

    first = store.save_pending(
        form_token="token-a",
        form_id="form-1",
        purpose="loading",
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        submitted_at=_NOW,
        answers=answers_a,
        validated_lines=_sample_validated_lines(answers_a),
    )
    second = store.save_pending(
        form_token="token-b",
        form_id="form-1",
        purpose="loading",
        technician_id=TechnicianId("tech-b"),
        machine_id=MachineId("vm-02"),
        submitted_at=_NOW,
        answers=answers_b,
        validated_lines=_sample_validated_lines(answers_b),
    )

    assert first.submission_id != second.submission_id
    for submission_id in (first.submission_id, second.submission_id):
        document = collection.find_one({"submission_id": submission_id})
        assert document is not None
        assert "event_id" not in document

    accepted = store.mark_accepted(
        first.submission_id,
        event_id="event-accepted-1",
        occurred_at=_NOW,
    )
    accepted_doc = collection.find_one({"submission_id": first.submission_id})
    assert accepted.event_id == "event-accepted-1"
    assert accepted_doc is not None
    assert accepted_doc["event_id"] == "event-accepted-1"
