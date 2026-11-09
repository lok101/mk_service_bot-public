from __future__ import annotations

from beartype import beartype

from src.domain.ids import TechnicianId


class FinalizedTransferChangedError(Exception):
    """Raised when a finalized MS transfer is changed or voided."""

    def __init__(self, external_document_id: str) -> None:
        self.external_document_id = external_document_id
        super().__init__(f"Finalized transfer changed: {external_document_id}")


class WarehouseAlreadyClosed(Exception):
    """Raised when a mutation is attempted on an exit-closed technician warehouse."""

    def __init__(self, technician_id: TechnicianId) -> None:
        self.technician_id = technician_id
        super().__init__(f"Warehouse already closed: {technician_id.value}")


class MoySkladUnavailable(Exception):
    """Raised when MoySklad is unavailable during warehouse import or delta."""


@beartype
class TechnicianWarehouseConcurrencyError(Exception):
    """Raised when optimistic persistence loses a race after all retries."""

    def __init__(self, *, technician_id: TechnicianId) -> None:
        self.technician_id = technician_id
        super().__init__(technician_id.value)
