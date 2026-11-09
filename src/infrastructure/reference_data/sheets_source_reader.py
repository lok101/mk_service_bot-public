from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from beartype import beartype

from src.application.reference_data import ReferenceDataSourceId
from src.application.reference_data.ports import ReferenceDataSourceReader
from src.infrastructure.integrations.google.sheets.sheet_reader import read_sheet_rows

ReadRowsFn = Callable[..., list[list[str]]]


@beartype
@dataclass(slots=True)
class SheetsReferenceDataSourceReader(ReferenceDataSourceReader):
    credentials_file: str
    sources: dict[ReferenceDataSourceId, tuple[str, int]]
    read_rows_fn: ReadRowsFn = read_sheet_rows

    @beartype
    def read_rows(self, source_id: ReferenceDataSourceId) -> list[list[str]]:
        spreadsheet_id, sheet_id = self.sources[source_id]
        return self.read_rows_fn(
            credentials_file=self.credentials_file,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
