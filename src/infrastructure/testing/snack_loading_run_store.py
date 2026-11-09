from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.snack_loading.ports import SnackLoadingRunRecord, SnackLoadingRunStore


@beartype
@dataclass(slots=True)
class InMemorySnackLoadingRunStore(SnackLoadingRunStore):
    _records: dict[str, SnackLoadingRunRecord] = field(default_factory=dict)

    @beartype
    def get(self, run_id: str) -> SnackLoadingRunRecord | None:
        return self._records.get(run_id)

    @beartype
    def save(self, record: SnackLoadingRunRecord) -> None:
        self._records[record.run_id] = record
