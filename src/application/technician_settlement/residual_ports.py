from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.technician_settlement.residual_document import ReconciliationResidualDocument


@runtime_checkable
class ReconciliationResidualDocumentRepository(Protocol):
    @beartype
    def save(self, document: ReconciliationResidualDocument) -> None: ...

    @beartype
    def count_all(self) -> int: ...

    @beartype
    def delete_all(self) -> int: ...
