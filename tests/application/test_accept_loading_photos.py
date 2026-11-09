from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.services import RegisterLoadingPhotosService
from src.application.machine_operations.use_cases import (
    LoadingPhotosBlocked,
    SubmitLoadingPhotosCommand,
)
from src.application.photo_batches.accept import AcceptLoadingPhotosService
from src.application.photo_batches.errors import PhotoBatchRejectedError
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations import CompleteRevision, LoadingSubmitted, SubmitLoading
from src.domain.machine_operations.events import PhotosSubmitted
from src.domain.models import RevisionSource
from src.domain.photo_batch import PhotoRef
from src.domain.results import (
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON,
    LoadingPhotosNotAllowed,
    loading_photos_excess_count_reason,
)
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot
from src.infrastructure.events import SyncDomainEventPublisher
from src.infrastructure.machine_operations.technician_last_maintenance_memory import (
    InMemoryTechnicianLastMaintenanceProjection,
)
from src.infrastructure.memory import EventSourcedMachineOperationsRepository, InMemoryEventStore
from src.infrastructure.photo_batches.memory import InMemoryPhotoBatchStore

_MACHINE_ID = MachineId("vm-photos")
_TECH = TechnicianId("tech-photos")
_BATCH_ID = BatchId("batch-photos-1")
_BATCH_ID_2 = BatchId("batch-photos-2")
_SUBMITTED_AT = datetime(2026, 5, 20, 11, 0, tzinfo=UTC)
_REVISION_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_PHOTO_1 = PhotoRef(
    file_id="file-1",
    file_unique_id="unique-1",
    message_id=1,
)
_PHOTO_2 = PhotoRef(
    file_id="file-2",
    file_unique_id="unique-2",
    message_id=2,
)
_PHOTO_3 = PhotoRef(
    file_id="file-3",
    file_unique_id="unique-3",
    message_id=3,
)


@dataclass(frozen=True, slots=True)
class _FixedKindLookup:
    kind: str | None

    def kind_of(self, machine_code: str) -> str | None:
        return self.kind


def _executor_with_revision() -> tuple[
    MachineOperationsExecutor, EventSourcedMachineOperationsRepository
]:
    publisher = SyncDomainEventPublisher()
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    executor = MachineOperationsExecutor(repository=repository, publisher=publisher)
    loading = executor.execute(
        _MACHINE_ID,
        lambda aggregate: aggregate.submit_loading(
            SubmitLoading(
                technician_id=_TECH,
                submitted_at=_REVISION_AT - timedelta(minutes=1),
                form_id="form-loading",
                form_token="load-before-token-rev",
            ),
        ),
    )
    assert isinstance(loading, LoadingSubmitted)
    executor.execute(
        _MACHINE_ID,
        lambda aggregate: aggregate.complete_revision(
            CompleteRevision(
                technician_id=_TECH,
                completed_at=_REVISION_AT,
                source=RevisionSource.GOOGLE_FORM,
                form_id="form-rev",
                form_token="token-rev",
            ),
        ),
    )
    return executor, repository


def _accept_service(
    executor: MachineOperationsExecutor,
    repository: EventSourcedMachineOperationsRepository,
    *,
    min_count: int = 2,
    max_count: int = 10,
    cooldown_minutes: int = 0,
    machine_kind_lookup: _FixedKindLookup | None = None,
) -> AcceptLoadingPhotosService:
    projection = InMemoryTechnicianLastMaintenanceProjection()
    return AcceptLoadingPhotosService(
        photo_batch_store=InMemoryPhotoBatchStore(),
        register_loading_photos=RegisterLoadingPhotosService(
            executor=executor,
            machine_operations=repository,
            last_maintenance_reader=projection,
            maintenance_cooldown_minutes=cooldown_minutes,
        ),
        loading_photos_min_count=min_count,
        loading_photos_max_count=max_count,
        machine_kind_lookup=machine_kind_lookup,
    )


def test_accept_loading_photos_micromarket_requires_exact_two() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(
        executor,
        repository,
        min_count=2,
        max_count=10,
        machine_kind_lookup=_FixedKindLookup("micro_market"),
    )

    result = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )

    assert isinstance(result, PhotosSubmitted)
    assert result.photo_count == 2


def test_accept_loading_photos_micromarket_rejects_insufficient_one() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(
        executor,
        repository,
        min_count=2,
        max_count=10,
        machine_kind_lookup=_FixedKindLookup("micro_market"),
    )

    with pytest.raises(
        PhotoBatchRejectedError,
        match=LOADING_PHOTOS_INSUFFICIENT_COUNT_REASON,
    ):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1,),
        )


def test_accept_loading_photos_micromarket_rejects_excess_three() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(
        executor,
        repository,
        min_count=2,
        max_count=10,
        machine_kind_lookup=_FixedKindLookup("micro_market"),
    )

    with pytest.raises(
        PhotoBatchRejectedError,
        match=loading_photos_excess_count_reason(2),
    ):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2, _PHOTO_3),
        )

    snapshot = service.photo_batch_store.get_by_batch_id(_BATCH_ID)
    assert snapshot is None


def test_accept_loading_photos_unknown_kind_uses_coffee_env_limits() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(
        executor,
        repository,
        min_count=2,
        max_count=10,
        machine_kind_lookup=_FixedKindLookup(None),
    )

    result = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2, _PHOTO_3),
    )

    assert isinstance(result, PhotosSubmitted)
    assert result.photo_count == 3


def test_accept_loading_photos_coffee_kind_uses_env_limits() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(
        executor,
        repository,
        min_count=2,
        max_count=10,
        machine_kind_lookup=_FixedKindLookup("coffee"),
    )

    result = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2, _PHOTO_3),
    )

    assert isinstance(result, PhotosSubmitted)
    assert result.photo_count == 3


def test_accept_loading_photos_success() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(executor, repository)

    result = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )

    assert isinstance(result, PhotosSubmitted)
    assert result.batch_id == _BATCH_ID
    snapshot = service.photo_batch_store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.status == "accepted"
    assert snapshot.event_id == result.event_id.value


def test_accept_loading_photos_rejects_when_exceeds_max_count() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(executor, repository, max_count=10)
    photos = tuple(
        PhotoRef(
            file_id=f"file-{index}",
            file_unique_id=f"unique-{index}",
            message_id=index,
        )
        for index in range(11)
    )

    with pytest.raises(PhotoBatchRejectedError, match="Максимум 10 фотографий"):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=photos,
        )

    snapshot = service.photo_batch_store.get_by_batch_id(_BATCH_ID)
    assert snapshot is None


def test_accept_loading_photos_rejected_without_revision() -> None:
    publisher = SyncDomainEventPublisher()
    repository = EventSourcedMachineOperationsRepository(
        event_store=InMemoryEventStore(),
    )
    executor = MachineOperationsExecutor(repository=repository, publisher=publisher)
    service = _accept_service(executor, repository)

    with pytest.raises(PhotoBatchRejectedError):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )

    snapshot = service.photo_batch_store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.status == "rejected"


def test_accept_loading_photos_insufficient_count() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(executor, repository, min_count=2)

    with pytest.raises(PhotoBatchRejectedError):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1,),
        )


def test_accept_loading_photos_rejected_when_already_submitted_today() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(executor, repository)

    first = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )
    assert isinstance(first, PhotosSubmitted)

    with pytest.raises(
        PhotoBatchRejectedError,
        match=LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    ):
        service.execute(
            batch_id=_BATCH_ID_2,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )

    snapshot = service.photo_batch_store.get_by_batch_id(_BATCH_ID_2)
    assert snapshot is not None
    assert snapshot.status == "rejected"


def test_accept_loading_photos_idempotent_retry() -> None:
    executor, repository = _executor_with_revision()
    service = _accept_service(executor, repository)

    first = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )
    second = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )

    assert isinstance(first, PhotosSubmitted)
    assert second.event_id == first.event_id


def test_accept_loading_photos_rejects_on_maintenance_cooldown() -> None:
    executor, repository = _executor_with_revision()
    projection = InMemoryTechnicianLastMaintenanceProjection()
    projection.upsert(
        TechnicianLastMaintenanceSnapshot(
            technician_id=_TECH,
            machine_id=MachineId("vm-other"),
            completed_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
        ),
    )
    service = AcceptLoadingPhotosService(
        photo_batch_store=InMemoryPhotoBatchStore(),
        register_loading_photos=RegisterLoadingPhotosService(
            executor=executor,
            machine_operations=repository,
            last_maintenance_reader=projection,
            maintenance_cooldown_minutes=20,
        ),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
    )

    with pytest.raises(PhotoBatchRejectedError, match="менее 20 мин"):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=datetime(2026, 5, 20, 10, 5, tzinfo=UTC),
            photos=(_PHOTO_1, _PHOTO_2),
        )


@dataclass
class _RejectThenAcceptPhotosRegister:
    call_count: int = 0

    def execute(
        self,
        command: SubmitLoadingPhotosCommand,
    ) -> PhotosSubmitted | LoadingPhotosNotAllowed:
        self.call_count += 1
        if self.call_count == 1:
            return LoadingPhotosNotAllowed(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
                reason="photos not allowed",
            )
        return PhotosSubmitted(
            event_id=EventId("event-photos-retry"),
            batch_id=command.batch_id,
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            photo_count=len(command.photos),
            submitted_at=command.submitted_at,
            occurred_at=_SUBMITTED_AT,
        )


def test_accept_loading_photos_rejected_then_accepted_on_retry() -> None:
    store = InMemoryPhotoBatchStore()
    service = AcceptLoadingPhotosService(
        photo_batch_store=store,
        register_loading_photos=_RejectThenAcceptPhotosRegister(),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
    )

    with pytest.raises(PhotoBatchRejectedError, match="photos not allowed"):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )

    result = service.execute(
        batch_id=_BATCH_ID,
        technician_id=_TECH,
        machine_id=_MACHINE_ID,
        submitted_at=_SUBMITTED_AT,
        photos=(_PHOTO_1, _PHOTO_2),
    )

    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert isinstance(result, PhotosSubmitted)
    assert snapshot is not None
    assert snapshot.status == "accepted"


_OPEN_BLOCK_REASON = "Сначала пересчёт микромаркета."


@dataclass
class _BlockedPhotosRegister:
    def execute(
        self,
        command: SubmitLoadingPhotosCommand,
    ) -> LoadingPhotosBlocked:
        return LoadingPhotosBlocked(
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            reason=_OPEN_BLOCK_REASON,
        )


def test_accept_loading_photos_rejects_when_loading_photos_blocked() -> None:
    store = InMemoryPhotoBatchStore()
    service = AcceptLoadingPhotosService(
        photo_batch_store=store,
        register_loading_photos=_BlockedPhotosRegister(),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
    )

    with pytest.raises(PhotoBatchRejectedError, match=_OPEN_BLOCK_REASON):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )

    snapshot = store.get_by_batch_id(_BATCH_ID)
    assert snapshot is not None
    assert snapshot.status == "rejected"
    assert snapshot.rejection_reason == _OPEN_BLOCK_REASON


class _MissProfileLookup:
    def cue_for(self, machine_code: str) -> None:
        return None


def test_accept_loading_photos_rejects_snack_even_when_not_strict() -> None:
    service = AcceptLoadingPhotosService(
        photo_batch_store=InMemoryPhotoBatchStore(),
        register_loading_photos=_BlockedPhotosRegister(),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
        machine_kind_lookup=_FixedKindLookup("snack"),
        profile_lookup=_MissProfileLookup(),
        profile_strict=False,
    )
    with pytest.raises(PhotoBatchRejectedError, match="профиль фото"):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )


def test_accept_loading_photos_rejects_strict_profile_miss() -> None:
    executor, repository = _executor_with_revision()
    service = AcceptLoadingPhotosService(
        photo_batch_store=InMemoryPhotoBatchStore(),
        register_loading_photos=RegisterLoadingPhotosService(
            executor=executor,
            machine_operations=repository,
            last_maintenance_reader=InMemoryTechnicianLastMaintenanceProjection(),
            maintenance_cooldown_minutes=0,
        ),
        loading_photos_min_count=2,
        loading_photos_max_count=10,
        machine_kind_lookup=_FixedKindLookup("coffee"),
        profile_lookup=_MissProfileLookup(),
        profile_strict=True,
    )
    with pytest.raises(PhotoBatchRejectedError, match="профиль фото"):
        service.execute(
            batch_id=_BATCH_ID,
            technician_id=_TECH,
            machine_id=_MACHINE_ID,
            submitted_at=_SUBMITTED_AT,
            photos=(_PHOTO_1, _PHOTO_2),
        )
