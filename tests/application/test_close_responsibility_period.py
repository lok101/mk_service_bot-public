from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.close_period_helpers import (
    ClosePeriodTestOptions,
    build_close_period_service,
    coffee_line,
    first_revision_event,
    second_revision_event,
)

from src.application.form_submissions.outbox_errors import NonRetryableOutboxError
from src.application.inventory_reconciliation.period_errors import PeriodSnapshotNotReadyError
from src.domain.ids import TechnicianId


def test_skips_when_only_first_revision() -> None:
    service, repo = build_close_period_service()
    result = service.execute(closing_event=first_revision_event())
    assert result is None
    assert repo.get_by_period_id("rev-1:rev-2") is None


def test_closes_period_with_domain_delta() -> None:
    service, repo = build_close_period_service()
    result = service.execute(closing_event=second_revision_event())
    assert result is not None
    assert result.period_id == "rev-1:rev-2"
    assert result.responsible_technician_id == TechnicianId("tech-a")
    assert result.status == "complete"
    assert result.lines[0].delta == Decimal("0")
    assert repo.get_by_period_id("rev-1:rev-2") == result


def test_repeat_execute_overwrites_unsettled_snapshot() -> None:
    service, repo = build_close_period_service()
    first = service.execute(closing_event=second_revision_event())
    second = service.execute(closing_event=second_revision_event())
    assert first is not None
    assert second is not None
    assert first.period_id == second.period_id
    assert repo.get_by_period_id("rev-1:rev-2") == second


def test_skips_when_period_already_reconciled() -> None:
    service, repo = build_close_period_service()
    first = service.execute(closing_event=second_revision_event())
    assert first is not None
    repo.mark_reconciled((first.period_id,))
    second = service.execute(closing_event=second_revision_event())
    assert second is None


def test_raises_not_ready_when_closing_submission_missing() -> None:
    service, _repo = build_close_period_service(
        options=ClosePeriodTestOptions(accept_closing=False),
    )
    with pytest.raises(PeriodSnapshotNotReadyError, match="evt-rev-2"):
        service.execute(closing_event=second_revision_event())


def test_raises_nonretryable_when_opening_submission_missing() -> None:
    service, _repo = build_close_period_service(
        options=ClosePeriodTestOptions(accept_opening=False),
    )
    with pytest.raises(NonRetryableOutboxError, match="evt-rev-1"):
        service.execute(closing_event=second_revision_event())


def test_raises_nonretryable_when_loading_submission_missing() -> None:
    service, _repo = build_close_period_service(
        options=ClosePeriodTestOptions(accept_loading=False),
    )
    with pytest.raises(NonRetryableOutboxError, match="evt-load-1"):
        service.execute(closing_event=second_revision_event())


def test_raises_nonretryable_on_duplicate_product_code(caplog: pytest.LogCaptureFixture) -> None:
    service, _repo = build_close_period_service(
        options=ClosePeriodTestOptions(
            opening_lines=(coffee_line("50"), coffee_line("50")),
        ),
    )
    with pytest.raises(NonRetryableOutboxError, match="DuplicateProductCodeInStock"):
        service.execute(closing_event=second_revision_event())
    assert "period_reconciliation_domain_error" in caplog.text
