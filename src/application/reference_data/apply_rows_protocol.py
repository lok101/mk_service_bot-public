from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.application.reference_data.models import ReferenceDataSourceId


@runtime_checkable
class ReferenceDataApplyRowsProvider(Protocol):
    def apply_rows(self, source_id: ReferenceDataSourceId, rows: list[list[str]]) -> None: ...
