from __future__ import annotations

from beartype import beartype

from src.domain.ids import TechnicianId


@beartype
class TechnicianSettlementConcurrencyError(Exception):
    """Raised when optimistic persistence loses a race after all retries."""

    def __init__(self, *, technician_id: TechnicianId) -> None:
        self.technician_id = technician_id
        super().__init__(technician_id.value)
