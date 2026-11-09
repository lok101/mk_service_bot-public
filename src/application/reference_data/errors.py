from __future__ import annotations

from beartype import beartype

from src.application.reference_data.models import ReferenceDataSourceId


class ReferenceDataUnavailable(RuntimeError):
    @beartype
    def __init__(self, source_id: ReferenceDataSourceId) -> None:
        super().__init__(f"Reference data unavailable for source {source_id.value!r}")
        self.source_id = source_id
