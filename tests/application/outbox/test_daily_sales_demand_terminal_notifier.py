from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from src.application.outbox.composite_terminal_failure_notifier import (
    CompositeOutboxTerminalFailureNotifier,
)
from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.application.outbox.terminal_failure_notifier import OutboxTerminalFailureNotifier
from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter
from src.infrastructure.outbox.serialization import event_to_outbox_document


@dataclass(slots=True)
class _RecordingFormWorkflowNotifier:
    messages: list[Any] = field(default_factory=list)

    async def notify(self, message: Any) -> None:
        self.messages.append(message)


@dataclass(slots=True)
class _RecordingDailySalesDemandOpsAlerter:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        sales_day: str | None,
        event_id: str | None,
    ) -> None:
        self.calls.append(
            {
                "handler_id": handler_id,
                "error_message": error_message,
                "sales_day": sales_day,
                "event_id": event_id,
            }
        )


@dataclass(slots=True)
class _NoOpMachinePnlOpsAlerter:
    def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        error_message: str,
        period_id: str | None,
        event_id: str | None,
    ) -> None:
        return None


def test_composite_notifies_ops_on_daily_sales_demand_terminal() -> None:
    form_wf = _RecordingFormWorkflowNotifier()
    primary = OutboxTerminalFailureNotifier(
        form_submission_store=InMemoryFormSubmissionStore(),
        form_workflow_notifier=form_wf,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    ops = _RecordingDailySalesDemandOpsAlerter()
    composite = CompositeOutboxTerminalFailureNotifier(
        primary=primary,
        machine_pnl_ops=_NoOpMachinePnlOpsAlerter(),
        daily_sales_demand_ops=ops,
        event_deserializer=OutboxEventDeserializerAdapter(),
    )
    event = DailySalesDemandRequested(
        event_id=EventId("daily_sales_demand:2026-08-09"),
        sales_day=date(2026, 8, 9),
        occurred_at=datetime(2026, 8, 10, 4, 0, tzinfo=UTC),
    )
    error = "ingest cursor not ready"

    asyncio.run(
        composite.notify_terminal_failure(
            handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
            event_document=event_to_outbox_document(event),
            error_message=error,
        ),
    )

    assert form_wf.messages == []
    assert len(ops.calls) == 1
    assert ops.calls[0]["handler_id"] == DAILY_SALES_DEMAND_HANDLER_ID
    assert ops.calls[0]["sales_day"] == "2026-08-09"
    assert ops.calls[0]["event_id"] == event.event_id.value
    assert ops.calls[0]["error_message"] == error
