from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.application.form_workflow.models import FormWorkflowAccepted, FormWorkflowOutcome
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.models import RevisionSource
from src.interfaces.telegram.form_workflow_outbox import FormWorkflowTelegramOutboxHandler

_T0 = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)


@dataclass
class RecordingFormWorkflowNotifier:
    outcomes: list[FormWorkflowOutcome] = field(default_factory=list)

    async def notify(self, outcome: FormWorkflowOutcome) -> None:
        self.outcomes.append(outcome)


def test_process_revision_notifies_accepted() -> None:
    notifier = RecordingFormWorkflowNotifier()
    handler = FormWorkflowTelegramOutboxHandler(notifier=notifier)
    event = RevisionCompleted(
        event_id=EventId("evt-1"),
        revision_id=RevisionId("rev-1"),
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        completed_at=_T0,
        occurred_at=_T0,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    asyncio.run(handler.process_revision(event))

    assert len(notifier.outcomes) == 1
    outcome = notifier.outcomes[0]
    assert isinstance(outcome, FormWorkflowAccepted)
    assert outcome.purpose == "revision"
    assert outcome.machine_id == MachineId("vm-1")


def test_process_loading_notifies_accepted() -> None:
    notifier = RecordingFormWorkflowNotifier()
    handler = FormWorkflowTelegramOutboxHandler(notifier=notifier)
    event = LoadingSubmitted(
        event_id=EventId("evt-2"),
        technician_id=TechnicianId("001"),
        machine_id=MachineId("vm-1"),
        submitted_at=_T0,
        occurred_at=_T0,
        form_id="form-1",
        form_token="token-2",
    )

    asyncio.run(handler.process_loading(event))

    assert len(notifier.outcomes) == 1
    outcome = notifier.outcomes[0]
    assert isinstance(outcome, FormWorkflowAccepted)
    assert outcome.purpose == "loading"
