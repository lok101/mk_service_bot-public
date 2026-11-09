from __future__ import annotations

from beartype import beartype


class PeriodSnapshotNotReadyError(Exception):
    """Dependencies for period snapshot are not yet available; outbox should retry."""

    @beartype
    def __init__(self, message: str) -> None:
        if not message:
            raise ValueError("message must not be empty")
        super().__init__(message)


class PeriodReconciliationNotFound(Exception):
    """No responsibility period reconciliation document for the given period_id."""

    @beartype
    def __init__(self, *, period_id: str) -> None:
        if not period_id:
            raise ValueError("period_id must not be empty")
        self.period_id = period_id
        super().__init__(period_id)
