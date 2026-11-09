from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.residual_pre_loading_purpose import residual_pre_loading_purpose_snapshot

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.technician_warehouse_loading import (
    FormSubmissionSnapshotMissingError,
    FormSubmissionSnapshotPurposeError,
    TechnicianWarehouseLoadingHandler,
)
from src.application.technician_warehouse import (
    ObserveTechnicianWarehouseLoading,
    TechnicianWarehouseExecutor,
)
from src.domain.form_submission import (
    FormAnswer,
    FormSubmissionSnapshot,
    FrozenInventoryLine,
    FrozenProductSpec,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor
from src.domain.technician_warehouse.events import TechnicianWarehouseLoadingObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_SUBMITTED_AT = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
_FORM_TOKEN_FIELD = "Код заявки."


def _revision_style_frozen_line(*, sku: str = "coffee", quantity: str = "2") -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code=sku,
            name="Кофе",
            unit=unit,
            pack_size=None,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(quantity),
    )


def _loading_frozen_line(
    *,
    sku: str = "coffee",
    packages: str = "2",
    pack_size: str = "1000",
) -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code=sku,
            name="Кофе",
            unit=unit,
            pack_size=Decimal(pack_size),
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(packages),
    )


def _loading_event(event_id: EventId) -> LoadingSubmitted:
    return LoadingSubmitted(
        event_id=event_id,
        technician_id=_TECHNICIAN_ID,
        machine_id=MachineId("vm-01"),
        submitted_at=_SUBMITTED_AT,
        occurred_at=_SUBMITTED_AT,
        form_id="form-loading",
        form_token="token-loading",
    )


_DEFAULT_LOADING_EVENT_ID = EventId("event-loading")


def _accepted_loading_snapshot(
    store: InMemoryFormSubmissionStore,
    *,
    lines: tuple[FrozenInventoryLine, ...],
    event_id: EventId = _DEFAULT_LOADING_EVENT_ID,
) -> FormSubmissionSnapshot:
    answers = (
        FormAnswer(title=_FORM_TOKEN_FIELD, value="token-loading"),
        FormAnswer(title="Кофе", value="2"),
    )
    pending = store.save_pending(
        form_token="token-loading",
        form_id="form-loading",
        purpose="loading",
        technician_id=_TECHNICIAN_ID,
        machine_id=MachineId("vm-01"),
        submitted_at=_SUBMITTED_AT,
        answers=answers,
        validated_lines=lines,
    )
    return store.mark_accepted(
        pending.submission_id,
        event_id=event_id.value,
        occurred_at=_SUBMITTED_AT,
    )


def _repository() -> InMemoryTechnicianWarehouseRepository:
    return InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )


def _handler(
    *,
    store: InMemoryFormSubmissionStore | None = None,
    repository: InMemoryTechnicianWarehouseRepository | None = None,
) -> TechnicianWarehouseLoadingHandler:
    store = store or InMemoryFormSubmissionStore()
    repository = repository or _repository()
    use_case = ObserveTechnicianWarehouseLoading(
        executor=TechnicianWarehouseExecutor(repository=repository),
    )
    return TechnicianWarehouseLoadingHandler(
        form_submission_store=store,
        observe_loading=use_case,
    )


def _accepted_loading_case() -> tuple[
    InMemoryFormSubmissionStore,
    InMemoryTechnicianWarehouseRepository,
    LoadingSubmitted,
    TechnicianWarehouseLoadingHandler,
]:
    store = InMemoryFormSubmissionStore()
    repository = _repository()
    event = _loading_event(EventId("event-loading"))
    _accepted_loading_snapshot(
        store,
        lines=(_loading_frozen_line(),),
        event_id=event.event_id,
    )
    return store, repository, event, _handler(store=store, repository=repository)


def _handler_with_revision_snapshot() -> tuple[TechnicianWarehouseLoadingHandler, LoadingSubmitted]:
    store = InMemoryFormSubmissionStore()
    answers = (FormAnswer(title=_FORM_TOKEN_FIELD, value="token-rev"),)
    pending = store.save_pending(
        form_token="token-rev",
        form_id="form-rev",
        purpose="revision",
        technician_id=_TECHNICIAN_ID,
        machine_id=MachineId("vm-01"),
        submitted_at=_SUBMITTED_AT,
        answers=answers,
        validated_lines=(_loading_frozen_line(),),
    )
    store.mark_accepted(
        pending.submission_id,
        event_id="event-rev",
        occurred_at=_SUBMITTED_AT,
    )
    event = _loading_event(EventId("event-rev"))
    return _handler(store=store), event


def _loading_events(
    repository: InMemoryTechnicianWarehouseRepository,
) -> list[TechnicianWarehouseLoadingObserved]:
    events = repository.event_store.get_events_for_technician(_TECHNICIAN_ID)
    return [event for event in events if isinstance(event, TechnicianWarehouseLoadingObserved)]


def test_loading_handler_appends_base_quantity_expense() -> None:
    store = InMemoryFormSubmissionStore()
    snapshot = _accepted_loading_snapshot(
        store,
        lines=(_loading_frozen_line(),),
    )
    repository = _repository()
    handler = _handler(store=store, repository=repository)
    asyncio.run(handler.process(_loading_event(EventId(snapshot.event_id or "event-loading"))))
    loading_events = _loading_events(repository)
    assert len(loading_events) == 1
    assert loading_events[0].lines == (
        TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("2000")),
    )


def test_loading_handler_retry_is_idempotent_by_event_id() -> None:
    store, repository, event, handler = _accepted_loading_case()
    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))
    assert len(_loading_events(repository)) == 1


def test_loading_handler_skips_lines_without_pack_size() -> None:
    store = InMemoryFormSubmissionStore()
    normal_line = _loading_frozen_line()
    unnormalizable_line = _revision_style_frozen_line()
    _accepted_loading_snapshot(
        store,
        lines=(normal_line, unnormalizable_line),
    )
    repository = _repository()
    handler = _handler(store=store, repository=repository)
    asyncio.run(handler.process(_loading_event(EventId("event-loading"))))
    loading_events = _loading_events(repository)
    assert len(loading_events) == 1
    assert loading_events[0].lines == (
        TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("2000")),
    )


def test_loading_handler_completes_without_event_when_all_lines_unnormalizable() -> None:
    store = InMemoryFormSubmissionStore()
    _accepted_loading_snapshot(
        store,
        lines=(_revision_style_frozen_line(),),
    )
    repository = _repository()
    handler = _handler(store=store, repository=repository)
    asyncio.run(handler.process(_loading_event(EventId("event-loading"))))
    assert len(_loading_events(repository)) == 0


def test_loading_handler_missing_snapshot_raises_retryable_error() -> None:
    handler = _handler(store=InMemoryFormSubmissionStore())
    with pytest.raises(FormSubmissionSnapshotMissingError) as exc_info:
        asyncio.run(handler.process(_loading_event(EventId("missing"))))
    assert not isinstance(exc_info.value, NonRetryableOutboxError)


def test_loading_handler_rejects_non_loading_snapshot_as_non_retryable() -> None:
    handler, event = _handler_with_revision_snapshot()
    with pytest.raises(FormSubmissionSnapshotPurposeError) as exc_info:
        asyncio.run(handler.process(event))
    assert isinstance(exc_info.value, NonRetryableOutboxError)
    assert exc_info.value.purpose == "revision"
    assert exc_info.value.expected == "loading"


def test_warehouse_loading_handler_rejects_pre_loading_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryFormSubmissionStore()
    event = _loading_event(EventId("evt-pre-wh"))
    residual = residual_pre_loading_purpose_snapshot(
        validated_lines=(_loading_frozen_line(),),
    )
    monkeypatch.setattr(store, "get_by_event_id", lambda _event_id: residual)
    handler = _handler(store=store)
    with pytest.raises(FormSubmissionSnapshotPurposeError) as exc_info:
        asyncio.run(handler.process(event))
    assert isinstance(exc_info.value, NonRetryableOutboxError)
    assert exc_info.value.purpose == "pre_loading"
    assert exc_info.value.expected == "loading"


def test_warehouse_loading_handler_rejects_unknown_purpose() -> None:
    store = InMemoryFormSubmissionStore()
    answers = (FormAnswer(title=_FORM_TOKEN_FIELD, value="token-loading"),)
    pending = store.save_pending(
        form_token="token-loading",
        form_id="form-rev",
        purpose="revision",
        technician_id=_TECHNICIAN_ID,
        machine_id=MachineId("vm-01"),
        submitted_at=_SUBMITTED_AT,
        answers=answers,
        validated_lines=(_loading_frozen_line(),),
    )
    store.mark_accepted(
        pending.submission_id,
        event_id="evt-pre-bad",
        occurred_at=_SUBMITTED_AT,
    )
    handler = _handler(store=store)
    with pytest.raises(FormSubmissionSnapshotPurposeError):
        asyncio.run(handler.process(_loading_event(EventId("evt-pre-bad"))))
