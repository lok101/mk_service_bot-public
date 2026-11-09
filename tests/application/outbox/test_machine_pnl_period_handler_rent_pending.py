from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryResidualSessionReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
    NoOpZeroMaintenanceAlerter,
    RecordingRentAccountantAlerter,
)

from src.application.form_submissions.outbox_errors import DeferredRetryOutboxError
from src.application.machine_pnl.models import make_pnl_id
from src.application.outbox.composite_terminal_failure_notifier import (
    CompositeOutboxTerminalFailureNotifier,
)
from src.application.outbox.handler_ids import MACHINE_PNL_PERIOD_HANDLER_ID
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.domain.machine_sales import MachineSale
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_FAILED,
    OUTBOX_STATUS_PENDING,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker

_PERIOD_ID = "period-rent-pending-1"
_SESSION_ID = "session-rent-pending-1"
_MACHINE_ID = MachineId("101")
_TECH = TechnicianId("tech-1")
_SKU = "coffee-beans"
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)


@dataclass(slots=True)
class _RecordingOpsFailureNotifier:
    """Fake ops path (≠ accountant); duck-typed into OutboxWorker via setattr."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "handler_id": handler_id,
                "error_message": error_message,
                "entry_id": entry_id,
                "claim_id": claim_id,
                "event_document": event_document,
            }
        )


@dataclass(slots=True)
class _RecordingFormWorkflowNotifier:
    messages: list[Any] = field(default_factory=list)

    async def notify(self, message: Any) -> None:
        self.messages.append(message)


@dataclass(slots=True)
class _RecordingMachinePnlOpsAlerter:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        period_id: str | None,
        event_id: str | None,
    ) -> None:
        self.calls.append(
            {
                "handler_id": handler_id,
                "error_message": error_message,
                "period_id": period_id,
                "event_id": event_id,
            }
        )


@dataclass(slots=True)
class _NoOpDailySalesDemandOpsAlerter:
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        sales_day: str | None,
        event_id: str | None,
    ) -> None:
        return None


def _snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=_PERIOD_ID,
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(
            ReconciliationLine(
                product_code=_SKU,
                actual_prev=Decimal("10"),
                actual=Decimal("7"),
                calculated=Decimal("5"),
                delta=Decimal("2"),
                loads_total=Decimal("0"),
                sales_total=Decimal("3"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        reconciled=True,
    )


def _event() -> MachinePeriodPnlRequested:
    return MachinePeriodPnlRequested(
        event_id=EventId(f"machine_pnl:{_PERIOD_ID}"),
        period_id=_PERIOD_ID,
        source_session_id=_SESSION_ID,
        occurred_at=_NOW,
    )


def _pending_handler(
    *,
    recording: RecordingRentAccountantAlerter,
    max_attempts: int = 7,
) -> MachinePnlPeriodHandler:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())
    sales = InMemoryMachineSalesWindowReader()
    sales.add(
        MachineSale(
            source_id="sale-1",
            machine_id=_MACHINE_ID,
            product_code=_SKU,
            quantity=Decimal("3"),
            occurred_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 5, 5, 11, 5, tzinfo=UTC),
            sale_kind="coffee",
            price=Decimal("50.00"),
        )
    )
    catalog = InMemoryUnitCostCatalog(_default=Decimal("10.00"))
    return MachinePnlPeriodHandler(
        snapshots=snapshots,
        sales=sales,
        period_pnl_store=InMemoryPeriodPnlStore(),
        load_unit_cost_catalog=lambda: catalog,
        residual_sessions=InMemoryResidualSessionReader(),
        load_opex_params=lambda: InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=lambda: InMemoryLocationRentOccupancyPort(),
        rent_accountant_alerter=recording,
        rent_pending_retry_hours=24,
        rent_pending_max_attempts=max_attempts,
    )


def test_machine_pnl_handler_rent_pending_deferred_and_accountant_alert() -> None:
    recording = RecordingRentAccountantAlerter()
    handler = _pending_handler(recording=recording)
    store = handler.period_pnl_store

    with pytest.raises(DeferredRetryOutboxError) as ei:
        asyncio.run(handler.process(_event()))

    err = ei.value
    assert err.delay == timedelta(hours=24)
    assert err.max_attempts == 7
    assert len(recording.calls) == 1
    assert recording.calls[0].period_id == _PERIOD_ID
    assert recording.calls[0].machine_id == _MACHINE_ID
    assert recording.calls[0].next_retry_hours == 24
    assert store.get(make_pnl_id(_PERIOD_ID)) is None
    assert store.list_by_period_id(_PERIOD_ID) == ()


def test_machine_pnl_rent_pending_exhausted_ops_alert() -> None:
    asyncio.run(_test_machine_pnl_rent_pending_exhausted_ops_alert())


async def _test_machine_pnl_rent_pending_exhausted_ops_alert() -> None:
    accountant = RecordingRentAccountantAlerter()
    ops = _RecordingOpsFailureNotifier()
    handler = _pending_handler(recording=accountant, max_attempts=2)
    store = InMemoryOutboxStore(max_attempts=10)
    event = _event()
    processors = OutboxProcessorRegistry()
    processors.register(MACHINE_PNL_PERIOD_HANDLER_ID, handler.process)
    store.enqueue(
        event_id=event.event_id.value,
        handler_id=MACHINE_PNL_PERIOD_HANDLER_ID,
        event_document=event_to_outbox_document(event),
    )

    worker = OutboxWorker(store=store, processors=processors)
    object.__setattr__(worker, "failure_notifier", ops)

    await worker.process_batch()
    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 1
    assert len(accountant.calls) == 1
    assert ops.calls == []

    entry["next_retry_at"] = datetime.now(tz=UTC) - timedelta(seconds=1)
    await worker.process_batch()

    entry = next(iter(store._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert entry["attempts"] == 2
    assert len(accountant.calls) == 2
    assert len(ops.calls) == 1
    assert ops.calls[0]["handler_id"] == MACHINE_PNL_PERIOD_HANDLER_ID
    assert "rent terms pending" in ops.calls[0]["error_message"]
    # ops channel ≠ accountant remind text
    assert "заполните rent_monthly" not in ops.calls[0]["error_message"]


def test_outbox_terminal_failure_notifier_silent_for_machine_pnl_period() -> None:
    """Prod FormWorkflow notifier alone no-ops when purpose is None (machine_pnl)."""
    primary = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=_RecordingFormWorkflowNotifier(),
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    event = _event()
    asyncio.run(
        primary.notify_terminal_failure(
            handler_id=MACHINE_PNL_PERIOD_HANDLER_ID,
            event_document=event_to_outbox_document(event),
            error_message="rent terms pending",
        ),
    )
    # no raise; FormWorkflow path does not cover machine_pnl_period


def test_composite_failure_notifier_ops_alert_on_machine_pnl_terminal() -> None:
    """Prod path: composite fans out to MACHINE_PNL_ALERT_CHAT_ID ops alerter."""
    form_wf = _RecordingFormWorkflowNotifier()
    primary = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=form_wf,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    ops = _RecordingMachinePnlOpsAlerter()
    composite = CompositeOutboxTerminalFailureNotifier(
        primary=primary,
        machine_pnl_ops=ops,
        daily_sales_demand_ops=_NoOpDailySalesDemandOpsAlerter(),
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    event = _event()
    error = "rent terms pending after max attempts"

    asyncio.run(
        composite.notify_terminal_failure(
            handler_id=MACHINE_PNL_PERIOD_HANDLER_ID,
            event_document=event_to_outbox_document(event),
            error_message=error,
        ),
    )

    assert form_wf.messages == []
    assert len(ops.calls) == 1
    assert ops.calls[0]["handler_id"] == MACHINE_PNL_PERIOD_HANDLER_ID
    assert ops.calls[0]["period_id"] == _PERIOD_ID
    assert ops.calls[0]["event_id"] == event.event_id.value
    assert ops.calls[0]["error_message"] == error
    assert "заполните rent_monthly" not in ops.calls[0]["error_message"]


def test_composite_failure_notifier_skips_ops_for_other_handlers() -> None:
    ops = _RecordingMachinePnlOpsAlerter()
    composite = CompositeOutboxTerminalFailureNotifier(
        primary=OutboxTerminalFailureNotifier(
            form_submission_store=InMemoryFormSubmissionStore(),
            form_workflow_notifier=_RecordingFormWorkflowNotifier(),
            event_deserializer=OutboxEventDeserializerAdapter(),
        ),
        machine_pnl_ops=ops,
        daily_sales_demand_ops=_NoOpDailySalesDemandOpsAlerter(),
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    asyncio.run(
        composite.notify_terminal_failure(
            handler_id="unknown-handler",
            event_document={},
            error_message="err",
        ),
    )
    assert ops.calls == []
