from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

import pytest

from src.application.form_submissions.accept_flow import (
    FormSubmissionValidationError,
)
from src.application.technician_warehouse.accept_inventory import (
    AcceptTechnicianWarehouseInventoryService,
)
from src.application.technician_warehouse.errors import TechnicianWarehouseConcurrencyError
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.ports import TechnicianWarehouseCommandExecutor
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.ids import TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.stubs import MappingProductCatalogResolver
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_FORM_TOKEN_FIELD = "Код заявки."
_TECHNICIAN_ID = TechnicianId("tech-1")
_NOW = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)

T = TypeVar("T")


def _warehouse_payload() -> TechnicianWarehouseInventoryTokenPayload:
    return TechnicianWarehouseInventoryTokenPayload(
        technician_id=_TECHNICIAN_ID,
        issued_at=_NOW,
        nonce="warehouse-1",
    )


def _valid_revision_stock_answers(token: str) -> tuple[FormAnswer, ...]:
    return (
        FormAnswer(title=_FORM_TOKEN_FIELD, value=token),
        FormAnswer(title="Кофе", value="6"),
    )


def _answers(*, coffee: str) -> tuple[FormAnswer, ...]:
    return (
        FormAnswer(title=_FORM_TOKEN_FIELD, value="token-1"),
        FormAnswer(title="Кофе", value=coffee),
    )


@dataclass(slots=True)
class _StubExecutor:
    handler: Callable[[TechnicianId, Callable[[TechnicianWarehouse], T]], T]

    def execute(
        self,
        technician_id: TechnicianId,
        command: Callable[[TechnicianWarehouse], T],
    ) -> T:
        return self.handler(technician_id, command)


def _conflict_executor() -> tuple[
    TechnicianWarehouseCommandExecutor, InMemoryTechnicianWarehouseRepository
]:
    event_store = InMemoryTechnicianWarehouseEventStore()
    repository = InMemoryTechnicianWarehouseRepository(event_store=event_store)

    def _always_conflict(
        technician_id: TechnicianId,
        command: Callable[[TechnicianWarehouse], T],
    ) -> T:
        raise TechnicianWarehouseConcurrencyError(technician_id=technician_id)

    return _StubExecutor(handler=_always_conflict), repository


def _service(
    *,
    with_baseline: bool = False,
    always_conflicts: bool = False,
) -> tuple[
    AcceptTechnicianWarehouseInventoryService,
    InMemoryFormSubmissionStore,
    InMemoryTechnicianWarehouseRepository,
]:
    store = InMemoryFormSubmissionStore()
    event_store = InMemoryTechnicianWarehouseEventStore()
    repository = InMemoryTechnicianWarehouseRepository(event_store=event_store)
    if always_conflicts:
        executor, repository = _conflict_executor()
    else:
        executor = TechnicianWarehouseExecutor(repository=repository)
        if with_baseline:
            executor.execute(
                _TECHNICIAN_ID,
                lambda warehouse: warehouse.count_inventory(
                    inventory_id="baseline-1",
                    form_token="baseline-token",
                    counted_at=_NOW,
                    actual_by_sku={},
                    baseline=False,
                ),
            )
    service = AcceptTechnicianWarehouseInventoryService(
        form_submission_store=store,
        product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD,
        executor=executor,
    )
    return service, store, repository


def _accept_valid(
    service: AcceptTechnicianWarehouseInventoryService,
    *,
    token: str = "token-1",
):
    return service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token=token,
        token_payload=_warehouse_payload(),
        answers=_valid_revision_stock_answers(token),
    )


def _accept(
    service: AcceptTechnicianWarehouseInventoryService,
    *,
    answers: tuple[FormAnswer, ...],
):
    return service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=answers,
    )


def test_accept_persists_snapshot_registers_inventory_and_marks_accepted() -> None:
    service, store, repository = _service()
    event = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=_valid_revision_stock_answers("token-1"),
    )
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status == "accepted"
    assert snapshot.machine_id is None
    assert snapshot.revision_id == event.inventory_id
    assert event.baseline is False
    assert repository.get(_TECHNICIAN_ID).latest_inventory_id == event.inventory_id


def test_accept_first_inventory_sets_baseline_false() -> None:
    # happy: first form inventory in empty stream
    service, store, _repository = _service(with_baseline=False)
    event = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=_valid_revision_stock_answers("token-1"),
    )
    assert event.baseline is False
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None
    assert snapshot.warehouse_inventory_baseline is False


def test_accept_ignores_snapshot_baseline_true_on_new_count_path() -> None:
    # edge: new write path always False; replay returns same event.baseline False
    service, _store, _repository = _service(with_baseline=False)
    first = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=_valid_revision_stock_answers("token-1"),
    )
    second = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=_valid_revision_stock_answers("token-1"),
    )
    assert first.baseline is False
    assert second.baseline is False
    assert first.event_id == second.event_id


def test_accepted_replay_restores_baseline_flag() -> None:
    service, store, repository = _service()
    first = _accept_valid(service, token="token-1")
    assert first.baseline is False
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None
    assert snapshot.warehouse_inventory_baseline is False
    second = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=(),
    )
    assert second.event_id == first.event_id
    assert second.baseline is False
    assert len(repository.event_store.get_events_for_technician(_TECHNICIAN_ID)) == 1


def test_accepted_replay_returns_cached_event_without_revalidation() -> None:
    service, store, repository = _service()
    first = _accept_valid(service, token="token-1")
    second = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=(),
    )
    assert second.event_id == first.event_id
    assert len(repository.event_store.get_events_for_technician(_TECHNICIAN_ID)) == 1


def test_invalid_quantities_mark_pending_snapshot_rejected() -> None:
    service, store, _repository = _service()
    with pytest.raises(FormSubmissionValidationError):
        _accept(service, answers=_answers(coffee="-1"))
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status == "rejected"
    assert snapshot.rejection_reason is not None
    assert snapshot.rejection_reason.strip()


def test_concurrency_error_is_propagated_without_false_accept() -> None:
    service, store, _repository = _service(always_conflicts=True)
    with pytest.raises(TechnicianWarehouseConcurrencyError):
        _accept_valid(service, token="token-1")
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status != "accepted"


def test_non_baseline_inventory_after_prior_count() -> None:
    service, _store, _repository = _service(with_baseline=True)
    event = _accept_valid(service, token="token-2")
    assert event.baseline is False


def test_accept_warehouse_stores_packages_in_snapshot_and_base_in_event() -> None:
    service, store, repository = _service()
    event = _accept_valid(service, token="token-1")
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None
    assert snapshot.validated_lines[0].quantity == Decimal("6")  # packages
    assert event.lines == (("coffee-1", Decimal("120")),)  # 6 * pack_size 20
    stored = repository.event_store.get_events_for_technician(_TECHNICIAN_ID)
    assert stored[-1].lines == (("coffee-1", Decimal("120")),)


def test_accept_warehouse_idempotent_replay_lines_are_base_units() -> None:
    service, _store, _repository = _service()
    first = _accept_valid(service, token="token-1")
    second = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-1",
        token_payload=_warehouse_payload(),
        answers=(),
    )
    assert second.lines == first.lines
    assert second.lines == (("coffee-1", Decimal("120")),)


def test_accept_warehouse_rejects_fractional_packages() -> None:
    service, store, _repository = _service()
    with pytest.raises(FormSubmissionValidationError):
        _accept(service, answers=_answers(coffee="1.5"))
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status == "rejected"


def test_accept_warehouse_idempotent_replay_sorts_multi_sku_lines() -> None:
    service = AcceptTechnicianWarehouseInventoryService(
        form_submission_store=InMemoryFormSubmissionStore(),
        product_code_resolver=MappingProductCatalogResolver(
            {"Кофе": "coffee-1", "Вода": "water-1"},
        ),
        form_token_field_name=_FORM_TOKEN_FIELD,
        executor=TechnicianWarehouseExecutor(
            repository=InMemoryTechnicianWarehouseRepository(
                event_store=InMemoryTechnicianWarehouseEventStore(),
            ),
        ),
    )
    answers = (
        FormAnswer(title=_FORM_TOKEN_FIELD, value="token-multi"),
        FormAnswer(title="Вода", value="2"),
        FormAnswer(title="Кофе", value="3"),
    )
    first = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-multi",
        token_payload=_warehouse_payload(),
        answers=answers,
    )
    second = service.execute(
        form_id="form-1",
        submitted_at=_NOW,
        form_token="token-multi",
        token_payload=_warehouse_payload(),
        answers=(),
    )
    assert first.lines == (
        ("coffee-1", Decimal("60")),
        ("water-1", Decimal("40")),
    )
    assert second.lines == first.lines


def test_accept_warehouse_rejects_missing_pack_size() -> None:
    store = InMemoryFormSubmissionStore()
    service = AcceptTechnicianWarehouseInventoryService(
        form_submission_store=store,
        product_code_resolver=MappingProductCatalogResolver(
            {"Кофе": "coffee-1"},
            pack_size=Decimal("0"),
        ),
        form_token_field_name=_FORM_TOKEN_FIELD,
        executor=TechnicianWarehouseExecutor(
            repository=InMemoryTechnicianWarehouseRepository(
                event_store=InMemoryTechnicianWarehouseEventStore(),
            ),
        ),
    )
    with pytest.raises(FormSubmissionValidationError, match="[Pp]ack size"):
        _accept(service, answers=_answers(coffee="2"))
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status == "rejected"


def test_accept_warehouse_accepts_zero_packages_as_base_zero() -> None:
    service, store, _repository = _service()
    event = _accept(service, answers=_answers(coffee="0"))
    assert ("coffee-1", Decimal("0")) in event.lines
    snapshot = store.get_by_form_token("token-1", "technician_warehouse_inventory")
    assert snapshot is not None and snapshot.status == "accepted"
    assert snapshot.validated_lines[0].quantity == Decimal("0")


def test_accept_warehouse_field_form_rejects_empty_answers_when_allow_empty_false() -> None:
    """error: FieldForm path forces allow_empty=False → empty body rejected."""
    store = InMemoryFormSubmissionStore()
    service = AcceptTechnicianWarehouseInventoryService(
        form_submission_store=store,
        product_code_resolver=MappingProductCatalogResolver({"Кофе": "coffee-1"}),
        form_token_field_name=_FORM_TOKEN_FIELD,
        executor=TechnicianWarehouseExecutor(
            repository=InMemoryTechnicianWarehouseRepository(
                event_store=InMemoryTechnicianWarehouseEventStore(),
            ),
        ),
        allow_empty=False,
    )
    with pytest.raises(FormSubmissionValidationError):
        _accept(
            service,
            answers=(FormAnswer(title=_FORM_TOKEN_FIELD, value="token-1"),),
        )
