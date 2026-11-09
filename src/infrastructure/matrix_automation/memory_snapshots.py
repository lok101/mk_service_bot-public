from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.matrix_automation import PriceSnapshotDocument


@beartype
class InMemoryMatrixPriceSnapshotStore:
    def __init__(self) -> None:
        self._documents: list[PriceSnapshotDocument] = []

    @beartype
    def save(self, document: PriceSnapshotDocument) -> None:
        self._documents.append(document)

    @beartype
    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return any(
            doc.machine_code == machine_code and doc.logical_matrix_name == logical_matrix_name
            for doc in self._documents
        )

    @beartype
    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        matching = [
            doc
            for doc in self._documents
            if doc.machine_code == machine_code and doc.logical_matrix_name == logical_matrix_name
        ]
        if not matching:
            return None
        for doc in sorted(matching, key=lambda item: item.recorded_at, reverse=True):
            if any(line.line_number == line_number for line in doc.lines):
                return doc
        return None

    @beartype
    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> Sequence[PriceSnapshotDocument]:
        latest_by_matrix: dict[str, PriceSnapshotDocument] = {}
        for doc in sorted(self._documents, key=lambda item: item.recorded_at):
            if doc.machine_code != machine_code:
                continue
            latest_by_matrix[doc.logical_matrix_name] = doc
        return tuple(latest_by_matrix[name] for name in sorted(latest_by_matrix))
