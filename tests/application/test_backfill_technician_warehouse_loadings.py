from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.residual_pre_loading_purpose import residual_pre_loading_purpose_snapshot

from src.application.technician_warehouse.backfill_loadings import (
    BackfillTechnicianWarehouseLoadings,
    BackfillWarehouseLoadingsAborted,
    BackfillWarehouseLoadingsReport,
)
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.observe_loading import ObserveTechnicianWarehouseLoading
from src.application.technician_warehouse.ports import LoadingSubmittedRef
from src.domain.form_submission import FormAnswer, FrozenInventoryLine, FrozenProductSpec
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor
from src.domain.technician_warehouse import TransferDirection
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECH = TechnicianId("tech-1")
_TECH_B = TechnicianId("tech-2")
_MACHINE = MachineId("vm-01")
_T0 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
_T2 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_FORM_TOKEN_FIELD = "Код заявки."


@dataclass
class _FakeSource:
    submitted: list[LoadingSubmittedRef] = field(default_factory=list)
    observed_ids: frozenset[str] = field(default_factory=frozenset)

    def list_loading_submitted(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> tuple[LoadingSubmittedRef, ...]:
        items = self.submitted
        if technician_id is not None:
            items = [item for item in items if item.technician_id == technician_id]
        return tuple(sorted(items, key=lambda item: item.submitted_at))

    def list_observed_source_event_ids(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> frozenset[str]:
        _ = technician_id
        return self.observed_ids


def _loading_line(*, packages: str = "2", pack_size: str | None = "1000") -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee",
            name="Кофе",
            unit=unit,
            pack_size=None if pack_size is None else Decimal(pack_size),
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(packages),
    )


def _save_loading_snapshot(
    store: InMemoryFormSubmissionStore,
    *,
    event_id: str,
    lines: tuple[FrozenInventoryLine, ...],
    purpose: str = "loading",
    technician_id: TechnicianId = _TECH,
) -> None:
    answers = (
        FormAnswer(title=_FORM_TOKEN_FIELD, value=f"token-{event_id}"),
        FormAnswer(title="Кофе", value="2"),
    )
    pending = store.save_pending(
        form_token=f"token-{event_id}",
        form_id="form-loading",
        purpose=purpose,  # type: ignore[arg-type]
        technician_id=technician_id,
        machine_id=_MACHINE,
        submitted_at=_T0,
        answers=answers,
        validated_lines=lines,
    )
    store.mark_accepted(
        pending.submission_id,
        event_id=event_id,
        occurred_at=_T0,
    )


def _ref(
    event_id: str,
    *,
    technician_id: TechnicianId = _TECH,
    submitted_at: datetime = _T0,
) -> LoadingSubmittedRef:
    return LoadingSubmittedRef(
        event_id=event_id,
        technician_id=technician_id,
        machine_id=_MACHINE,
        submitted_at=submitted_at,
    )


def _uc(
    *,
    source: _FakeSource,
    store: InMemoryFormSubmissionStore | None = None,
    repo: InMemoryTechnicianWarehouseRepository | None = None,
) -> tuple[
    BackfillTechnicianWarehouseLoadings,
    InMemoryFormSubmissionStore,
    InMemoryTechnicianWarehouseRepository,
]:
    form_store = store or InMemoryFormSubmissionStore()
    event_store = InMemoryTechnicianWarehouseEventStore()
    repository = repo or InMemoryTechnicianWarehouseRepository(event_store=event_store)
    executor = TechnicianWarehouseExecutor(repository=repository, publisher=None)
    observe = ObserveTechnicianWarehouseLoading(executor=executor)
    return (
        BackfillTechnicianWarehouseLoadings(
            source=source,
            form_submission_store=form_store,
            observe_loading=observe,
            repository=repository,
        ),
        form_store,
        repository,
    )


def _close_warehouse(
    repo: InMemoryTechnicianWarehouseRepository,
    technician_id: TechnicianId,
) -> None:
    warehouse = repo.get(technician_id)
    warehouse.count_inventory(
        inventory_id="inv-b",
        form_token="tok-b",
        counted_at=_T0,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    transfer = TechnicianWarehouseTransferObserved(
        event_id=EventId(f"tr-{technician_id.value}"),
        technician_id=technician_id,
        occurred_at=_T1,
        external_document_id=f"ret-{technician_id.value}",
        moment=_T1,
        updated_at=_T1,
        observed_at=_T1,
        content_hash=f"hash-{technician_id.value}",
        direction=TransferDirection.SUPPLY_RETURN,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("10")),),
    )
    warehouse.observe_transfer(transfer)
    warehouse.close_exit(
        closed_at=_T2,
        return_external_document_id=transfer.external_document_id,
        return_content_hash=transfer.content_hash,
    )
    events = warehouse.collect_events()
    repo.event_store.append(technician_id, expected_version=0, events=events)


def test_backfill_confirm_observes_candidate_and_is_idempotent() -> None:
    source = _FakeSource(submitted=[_ref("evt-1")])
    uc, store, repo = _uc(source=source)
    _save_loading_snapshot(store, event_id="evt-1", lines=(_loading_line(),))

    report = uc.execute(technician_id=_TECH, confirm=True)
    assert report == BackfillWarehouseLoadingsReport(
        candidates=1,
        would_fail_closed=0,
        observed=1,
        skipped_missing_snapshot=0,
        skipped_wrong_purpose=0,
        skipped_empty_lines=0,
        skipped_already=0,
        sample_event_ids=("evt-1",),
        sample_would_fail_closed_event_ids=(),
    )
    loadings = [
        event
        for event in repo.event_store.get_events_for_technician(_TECH)
        if isinstance(event, TechnicianWarehouseLoadingObserved)
    ]
    assert len(loadings) == 1
    assert loadings[0].source_event_id == "evt-1"

    source.observed_ids = frozenset({"evt-1"})
    second = uc.execute(technician_id=_TECH, confirm=True)
    assert second.candidates == 0
    assert second.observed == 0
    assert (
        len(
            [
                event
                for event in repo.event_store.get_events_for_technician(_TECH)
                if isinstance(event, TechnicianWarehouseLoadingObserved)
            ]
        )
        == 1
    )


def test_backfill_confirm_skips_pre_loading_as_wrong_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _FakeSource(submitted=[_ref("evt-pre-1")])
    uc, store, repo = _uc(source=source)
    residual = residual_pre_loading_purpose_snapshot(
        validated_lines=(_loading_line(),),
    )
    monkeypatch.setattr(store, "get_by_event_id", lambda _event_id: residual)

    report = uc.execute(technician_id=_TECH, confirm=True)
    assert report.observed == 0
    assert report.skipped_wrong_purpose == 1
    assert not any(
        isinstance(event, TechnicianWarehouseLoadingObserved)
        for event in repo.event_store.get_events_for_technician(_TECH)
    )


def test_backfill_dry_run_counts_would_fail_closed_without_writes() -> None:
    source = _FakeSource(
        submitted=[_ref("evt-closed"), _ref("evt-open", submitted_at=_T1)],
    )
    uc, store, repo = _uc(source=source)
    _save_loading_snapshot(store, event_id="evt-closed", lines=(_loading_line(),))
    _save_loading_snapshot(store, event_id="evt-open", lines=(_loading_line(),))
    _close_warehouse(repo, _TECH)

    report = uc.execute(technician_id=_TECH, confirm=False)
    assert report.candidates == 2
    assert report.would_fail_closed == 2
    assert report.observed == 0
    assert report.sample_event_ids == ("evt-closed", "evt-open")
    assert report.sample_would_fail_closed_event_ids == ("evt-closed", "evt-open")
    assert not any(
        isinstance(event, TechnicianWarehouseLoadingObserved)
        for event in repo.event_store.get_events_for_technician(_TECH)
    )


def test_backfill_confirm_skips_missing_wrong_purpose_empty_lines() -> None:
    source = _FakeSource(
        submitted=[
            _ref("evt-missing"),
            _ref("evt-wrong", submitted_at=_T1),
            _ref("evt-empty", submitted_at=_T2),
        ],
    )
    uc, store, repo = _uc(source=source)
    _save_loading_snapshot(
        store,
        event_id="evt-wrong",
        lines=(_loading_line(),),
        purpose="revision",
    )
    _save_loading_snapshot(
        store,
        event_id="evt-empty",
        lines=(_loading_line(pack_size=None),),
    )

    report = uc.execute(technician_id=_TECH, confirm=True)
    assert report.candidates == 3
    assert report.observed == 0
    assert report.skipped_missing_snapshot == 1
    assert report.skipped_wrong_purpose == 1
    assert report.skipped_empty_lines == 1
    assert not any(
        isinstance(event, TechnicianWarehouseLoadingObserved)
        for event in repo.event_store.get_events_for_technician(_TECH)
    )


def test_backfill_confirm_aborts_on_closed_mid_batch_keeps_partial() -> None:
    source = _FakeSource(
        submitted=[
            _ref("evt-ok", technician_id=_TECH, submitted_at=_T0),
            _ref("evt-closed", technician_id=_TECH_B, submitted_at=_T1),
            _ref("evt-later", technician_id=_TECH_B, submitted_at=_T2),
        ],
    )
    event_store = InMemoryTechnicianWarehouseEventStore()
    repo = InMemoryTechnicianWarehouseRepository(event_store=event_store)
    store = InMemoryFormSubmissionStore()
    _save_loading_snapshot(
        store,
        event_id="evt-ok",
        lines=(_loading_line(),),
        technician_id=_TECH,
    )
    _save_loading_snapshot(
        store,
        event_id="evt-closed",
        lines=(_loading_line(),),
        technician_id=_TECH_B,
    )
    _save_loading_snapshot(
        store,
        event_id="evt-later",
        lines=(_loading_line(),),
        technician_id=_TECH_B,
    )
    _close_warehouse(repo, _TECH_B)
    uc, _, _ = _uc(source=source, store=store, repo=repo)

    with pytest.raises(BackfillWarehouseLoadingsAborted) as raised:
        uc.execute(technician_id=None, confirm=True)

    assert raised.value.technician_id == _TECH_B
    assert raised.value.event_id == "evt-closed"
    observed = [
        event
        for event in repo.event_store.get_events_for_technician(_TECH)
        if isinstance(event, TechnicianWarehouseLoadingObserved)
    ]
    assert len(observed) == 1
    assert observed[0].source_event_id == "evt-ok"
    assert not any(
        isinstance(event, TechnicianWarehouseLoadingObserved)
        for event in repo.event_store.get_events_for_technician(_TECH_B)
    )


def test_backfill_confirm_counts_skipped_already_when_observe_returns_none_for_duplicate() -> None:
    source = _FakeSource(submitted=[_ref("evt-1")])
    uc, store, repo = _uc(source=source)
    _save_loading_snapshot(store, event_id="evt-1", lines=(_loading_line(),))
    first = uc.execute(technician_id=_TECH, confirm=True)
    assert first.observed == 1
    # Stale scan: candidate still listed, observed_ids not updated
    second = uc.execute(technician_id=_TECH, confirm=True)
    assert second.candidates == 1
    assert second.observed == 0
    assert second.skipped_already == 1
