from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.master_data import MachineKind, MachineStatus, MasterMachine
from src.application.visit_photo_grouping import (
    VISIT_PHOTO_GROUPING_HANDLER_ID,
    DeliveryKind,
    GroupingDelivery,
    GroupingRetryReason,
)
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.photo_batch import PhotoBatchSnapshot, PhotoRef, StoredPhotoRef
from src.infrastructure.outbox import InMemoryOutboxStore, OutboxDomainEventPublisher
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.visit_photo_grouping import (
    build_visit_photo_grouping_handler,
    register_visit_photo_grouping,
    subscribe_visit_photo_grouping,
)
from src.infrastructure.visit_photo_grouping.batch_reader import PhotoBatchGroupingReader
from src.infrastructure.visit_photo_grouping.outbox_handler import VisitPhotoGroupingOutboxHandler
from src.infrastructure.visit_photo_grouping.participation import MasterMachineReviewParticipation

_TS = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _photos_event() -> PhotosSubmitted:
    return PhotosSubmitted(
        event_id=EventId("evt-1"),
        batch_id=BatchId("batch-1"),
        technician_id=TechnicianId("t-1"),
        machine_id=MachineId("m-1"),
        photo_count=1,
        submitted_at=_TS,
        occurred_at=_TS,
    )


def _accepted_snapshot() -> PhotoBatchSnapshot:
    return PhotoBatchSnapshot(
        batch_id=BatchId("batch-1"),
        purpose="loading",
        technician_id=TechnicianId("t-1"),
        machine_id=MachineId("m-1"),
        submitted_at=_TS,
        photos=(PhotoRef(file_id="f0", file_unique_id="u0", message_id=1),),
        status="accepted",
        event_id="evt-1",
        occurred_at=_TS,
        stored_files=(
            StoredPhotoRef(
                index=0,
                storage_key="k0",
                content_type="image/jpeg",
                size_bytes=4,
                content_hash="abc",
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class _BatchLookup:
    snapshot: PhotoBatchSnapshot | None

    def get_by_batch_id(self, batch_id: BatchId) -> PhotoBatchSnapshot | None:
        return self.snapshot


@dataclass(frozen=True, slots=True)
class _MachineLookup:
    machine: MasterMachine | None

    def get(self, machine_id: MachineId) -> MasterMachine | None:
        return self.machine


@dataclass(frozen=True, slots=True)
class _Permanent:
    def execute(self, batch_id: str) -> GroupingDelivery:
        return GroupingDelivery(
            kind=DeliveryKind.PERMANENT,
            batch_id=batch_id,
            machine_id="m-1",
        )


@dataclass(frozen=True, slots=True)
class _Retry:
    def execute(self, batch_id: str) -> GroupingDelivery:
        return GroupingDelivery(
            kind=DeliveryKind.RETRY,
            batch_id=batch_id,
            machine_id="m-1",
            reason=GroupingRetryReason.BATCH_WAITING_HASHES,
        )


@dataclass(frozen=True, slots=True)
class _Success:
    def execute(self, batch_id: str) -> GroupingDelivery:
        return GroupingDelivery(
            kind=DeliveryKind.SUCCESS,
            batch_id=batch_id,
            machine_id="m-1",
        )


def test_batch_reader_copies_content_hash() -> None:
    reader = PhotoBatchGroupingReader(_BatchLookup(_accepted_snapshot()))
    batch = reader.get("batch-1")
    assert batch is not None
    assert batch.status == "accepted"
    assert batch.files[0].content_hash == "abc"
    assert batch.files[0].storage_key == "k0"
    assert batch.machine_id == "m-1"


def test_participation_reads_explicit_false() -> None:
    machine = MasterMachine(
        machine_id=MachineId("101"),
        kind=MachineKind.COFFEE,
        status=MachineStatus.ACTIVE_ON_SITE,
        label=None,
        include_in_visit_photo_review=False,
    )
    participation = MasterMachineReviewParticipation(_MachineLookup(machine))
    assert participation.include("101") is False


def test_participation_missing_machine_is_included() -> None:
    participation = MasterMachineReviewParticipation(_MachineLookup(None))
    assert participation.include("101") is True


def test_permanent_delivery_is_nonretryable_and_logs_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = VisitPhotoGroupingOutboxHandler(_Permanent())
    with pytest.raises(NonRetryableOutboxError, match="visit photo grouping refused"):
        asyncio.run(handler.process(_photos_event()))
    assert "storage_key" not in caplog.text
    assert "k0" not in caplog.text
    assert "batch-1" in caplog.text
    assert "m-1" in caplog.text


def test_retry_delivery_raises_deferred_retry() -> None:
    handler = VisitPhotoGroupingOutboxHandler(
        _Retry(),
        not_ready_retry_minutes=7,
        not_ready_max_attempts=11,
    )
    with pytest.raises(DeferredRetryOutboxError, match="batch_waiting_hashes") as raised:
        asyncio.run(handler.process(_photos_event()))
    error = raised.value
    assert error.delay == timedelta(minutes=7)
    assert error.max_attempts == 11
    assert "batch_id=batch-1" in str(error)
    assert "machine_id=m-1" in str(error)
    assert "storage_key" not in str(error)


def test_success_delivery_is_noop() -> None:
    handler = VisitPhotoGroupingOutboxHandler(_Success())
    asyncio.run(handler.process(_photos_event()))


def test_handler_ctor_defaults_match_settings() -> None:
    handler = VisitPhotoGroupingOutboxHandler(_Retry())
    with pytest.raises(DeferredRetryOutboxError) as raised:
        asyncio.run(handler.process(_photos_event()))
    assert raised.value.delay == timedelta(minutes=5)
    assert raised.value.max_attempts == 24


def test_grouping_disabled_does_not_register_handler() -> None:
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    processors = OutboxProcessorRegistry()
    register_visit_photo_grouping(
        publisher=publisher,
        processors=processors,
        enabled=False,
        handler=None,
    )
    assert VISIT_PHOTO_GROUPING_HANDLER_ID not in publisher.handler_ids_for(PhotosSubmitted)


def test_grouping_enabled_registers_handler() -> None:
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    processors = OutboxProcessorRegistry()
    register_visit_photo_grouping(
        publisher=publisher,
        processors=processors,
        enabled=True,
        handler=VisitPhotoGroupingOutboxHandler(_Permanent()),
    )
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in publisher.handler_ids_for(PhotosSubmitted)
    assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID)


def test_subscribe_only_does_not_register_processor() -> None:
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    processors = OutboxProcessorRegistry()
    subscribe_visit_photo_grouping(publisher=publisher, enabled=True)
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in publisher.handler_ids_for(PhotosSubmitted)
    assert processors.is_registered(VISIT_PHOTO_GROUPING_HANDLER_ID) is False


def test_build_handler_returns_none_when_disabled() -> None:
    assert (
        build_visit_photo_grouping_handler(
            enabled=False,
            photo_batch_store=_BatchLookup(None),
            machines=None,
            classifier=None,
            catalog=None,
            assign=None,
            missing=None,
        )
        is None
    )


def test_build_handler_enabled_without_classifier_raises() -> None:
    with pytest.raises(ValidationError, match="GroupClassifier"):
        build_visit_photo_grouping_handler(
            enabled=True,
            photo_batch_store=_BatchLookup(None),
            machines=None,
            classifier=None,
            catalog=object(),
            assign=object(),
            missing=object(),
        )
