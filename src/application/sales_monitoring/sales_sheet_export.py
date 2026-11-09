from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.sales_monitoring.ports import (
    MachineDisplayLookup,
    ProductDisplayLookup,
    SalesForSheetExportLoader,
    SalesSheetExportCursor,
    SalesSheetExportPort,
    SalesSheetExportRow,
)
from src.application.shared.sheet_cell_format import (
    format_sheet_datetime,
    format_sheet_decimal,
)
from src.domain.machine_sales import MachineSale

SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE = 2000

SALES_SHEET_EXPORT_HEADERS: tuple[str, ...] = (
    "Дата и время",
    "Код аппарата",
    "Имя аппарата",
    "Код товара",
    "Имя товара",
    "Сумма",
    "Тип аппарата",
)


@beartype
@dataclass(frozen=True, slots=True)
class SalesSheetExportResult:
    mode: Literal["backfill", "incremental"]
    exported_count: int
    trimmed_count: int
    pages: int
    cursor_occurred_at: datetime | None
    cursor_source_id: str | None


@beartype
def map_sale_to_export_row(
    sale: MachineSale,
    *,
    tz: ZoneInfo,
    machine_name: str | None,
    product_name: str | None,
) -> SalesSheetExportRow:
    date_text = format_sheet_datetime(sale.occurred_at, tz)
    price_text = "" if sale.price is None else format_sheet_decimal(sale.price)
    return SalesSheetExportRow(
        values=(
            date_text,
            sale.machine_code or "",
            machine_name or "",
            sale.product_code,
            product_name or "",
            price_text,
            sale.sale_kind,
        )
    )


def sheet_row_count(sale: MachineSale) -> int:
    if sale.sale_kind != "micromarket":
        return 1
    qty = sale.quantity
    if qty != qty.to_integral_value() or qty < 1:
        return 1
    return int(qty)


@beartype
def map_sale_to_export_rows(
    sale: MachineSale,
    *,
    tz: ZoneInfo,
    machine_name: str | None,
    product_name: str | None,
) -> tuple[SalesSheetExportRow, ...]:
    row = map_sale_to_export_row(
        sale,
        tz=tz,
        machine_name=machine_name,
        product_name=product_name,
    )
    count = sheet_row_count(sale)
    return tuple(row for _ in range(count))


@beartype
@dataclass(frozen=True, slots=True)
class ExportSalesToSheet:
    sales: SalesForSheetExportLoader
    cursor: SalesSheetExportCursor
    sheet: SalesSheetExportPort
    machines: MachineDisplayLookup
    products: ProductDisplayLookup
    timezone: ZoneInfo
    max_rows: int
    page_size: int = SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE

    @beartype
    def execute(self) -> SalesSheetExportResult:
        cursor = self.cursor.load()
        mode: Literal["backfill", "incremental"] = "backfill" if cursor is None else "incremental"
        exported_count = 0
        pages = 0
        final_cursor = cursor
        if cursor is None:
            batch = list(self.sales.list_latest(limit=self.max_rows))
            exported_count, pages, final_cursor = self._export_pages(batch)
        else:
            occurred_at, source_id = cursor
            while True:
                page = list(
                    self.sales.list_after(
                        occurred_at=occurred_at,
                        source_id=source_id,
                        limit=self.page_size,
                    )
                )
                if not page:
                    break
                chunk_exported, chunk_pages, final_cursor = self._export_pages(page)
                exported_count += chunk_exported
                pages += chunk_pages
                assert final_cursor is not None
                occurred_at, source_id = final_cursor
        trimmed_count = 0
        if exported_count > 0:
            trimmed_count = self.sheet.trim_to_max_data_rows(self.max_rows)
        return SalesSheetExportResult(
            mode=mode,
            exported_count=exported_count,
            trimmed_count=trimmed_count,
            pages=pages,
            cursor_occurred_at=None if final_cursor is None else final_cursor[0],
            cursor_source_id=None if final_cursor is None else final_cursor[1],
        )

    @beartype
    def _chunks_by_sheet_rows(
        self,
        sales: Sequence[MachineSale],
    ) -> list[list[MachineSale]]:
        chunks: list[list[MachineSale]] = []
        current: list[MachineSale] = []
        rows = 0
        for sale in sales:
            need = sheet_row_count(sale)
            if current and rows + need > self.page_size:
                chunks.append(current)
                current = []
                rows = 0
            current.append(sale)
            rows += need
            if rows >= self.page_size:
                chunks.append(current)
                current = []
                rows = 0
        if current:
            chunks.append(current)
        return chunks

    @beartype
    def _export_pages(
        self,
        sales: Sequence[MachineSale],
    ) -> tuple[int, int, tuple[datetime, str] | None]:
        exported = 0
        pages = 0
        final_cursor: tuple[datetime, str] | None = None
        for chunk in self._chunks_by_sheet_rows(sales):
            self.sheet.ensure_header(SALES_SHEET_EXPORT_HEADERS)
            rows: list[SalesSheetExportRow] = []
            for sale in chunk:
                rows.extend(
                    map_sale_to_export_rows(
                        sale,
                        tz=self.timezone,
                        machine_name=self.machines.name_for(sale.machine_id),
                        product_name=self.products.name_for(sale.product_code),
                    )
                )
            self.sheet.append_rows(rows)
            last = chunk[-1]
            final_cursor = (last.occurred_at, last.source_id)
            self.cursor.save(occurred_at=last.occurred_at, source_id=last.source_id)
            exported += len(rows)
            pages += 1
        return exported, pages, final_cursor


__all__ = [
    "ExportSalesToSheet",
    "SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE",
    "SALES_SHEET_EXPORT_HEADERS",
    "SalesSheetExportResult",
    "map_sale_to_export_row",
    "map_sale_to_export_rows",
]
