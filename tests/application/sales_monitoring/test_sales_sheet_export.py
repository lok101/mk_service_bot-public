from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from beartype import beartype

from src.application.sales_monitoring.ports import SalesSheetExportRow
from src.application.sales_monitoring.sales_sheet_export import (
    SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE,
    SALES_SHEET_EXPORT_HEADERS,
    ExportSalesToSheet,
    map_sale_to_export_row,
    map_sale_to_export_rows,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale


def test_canonical_headers_match_spec() -> None:
    assert SALES_SHEET_EXPORT_HEADERS == (
        "Дата и время",
        "Код аппарата",
        "Имя аппарата",
        "Код товара",
        "Имя товара",
        "Сумма",
        "Тип аппарата",
    )
    assert SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE == 2000


def _sale(**kwargs: object) -> MachineSale:
    base: dict[str, object] = dict(
        source_id="s1",
        machine_id=MachineId("m1"),
        product_code="P1",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 30, 6, 5, 4, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 30, 7, 0, 0, tzinfo=UTC),
        sale_kind="coffee",
        machine_code="42",
        price=Decimal("10.50"),
    )
    base.update(kwargs)
    return MachineSale(**base)  # type: ignore[arg-type]


def test_map_sale_to_row_formats_datetime_and_price() -> None:
    row = map_sale_to_export_row(
        _sale(),
        tz=ZoneInfo("Asia/Yekaterinburg"),
        machine_name="Кафе",
        product_name="Сникерс",
    )
    # UTC 06:05:04 → EKB (+5) 11:05:04
    assert row.values[0] == "30.07.2026 11:05:04"
    assert row.values[1] == "42"
    assert row.values[2] == "Кафе"
    assert row.values[3] == "P1"
    assert row.values[4] == "Сникерс"
    assert row.values[5] == "10,5"
    assert row.values[6] == "coffee"


def test_map_sale_to_row_zero_pads_hour() -> None:
    row = map_sale_to_export_row(
        _sale(occurred_at=datetime(2026, 7, 31, 3, 5, 4, tzinfo=UTC)),
        tz=ZoneInfo("Asia/Yekaterinburg"),
        machine_name="Кафе",
        product_name="Сникерс",
    )
    # UTC 03:05:04 → EKB (+5) 08:05:04
    assert row.values[0] == "31.07.2026 08:05:04"


def test_map_sale_empty_lookups_and_null_price() -> None:
    row = map_sale_to_export_row(
        _sale(machine_code=None, price=None, sale_kind="unknown", product_code=""),
        tz=ZoneInfo("UTC"),
        machine_name=None,
        product_name=None,
    )
    assert row.values[1] == ""
    assert row.values[2] == ""
    assert row.values[3] == ""
    assert row.values[4] == ""
    assert row.values[5] == ""
    assert row.values[6] == "unknown"


def test_map_micromarket_quantity_two_expands_unit_rows() -> None:
    # happy: две штуки, сумма каждой = price, не сумма чека
    rows = map_sale_to_export_rows(
        _sale(sale_kind="micromarket", quantity=Decimal("2"), price=Decimal("190")),
        tz=ZoneInfo("UTC"),
        machine_name=None,
        product_name=None,
    )
    assert len(rows) == 2
    assert rows[0].values[5] == "190"
    assert rows[1].values[5] == "190"
    assert rows[0].values[6] == "micromarket"
    assert rows[0].values[2] == ""
    assert rows[0].values[4] == ""


def test_map_coffee_quantity_stays_one_row() -> None:
    # happy: quantity кофе не разворачивается
    rows = map_sale_to_export_rows(
        _sale(sale_kind="coffee", quantity=Decimal("2"), price=Decimal("10.50")),
        tz=ZoneInfo("UTC"),
        machine_name="Кафе",
        product_name="Сникерс",
    )
    assert len(rows) == 1
    assert rows[0].values[5] == "10,5"
    assert rows[0].values[6] == "coffee"


@pytest.mark.parametrize("sale_kind", ["snack", "unknown"])
def test_map_non_micromarket_quantity_stays_one_row(sale_kind: str) -> None:
    # happy: snack/unknown — одна строка на документ
    rows = map_sale_to_export_rows(
        _sale(sale_kind=sale_kind, quantity=Decimal("2"), price=Decimal("10.50")),
        tz=ZoneInfo("UTC"),
        machine_name="Кафе",
        product_name="Сникерс",
    )
    assert len(rows) == 1
    assert rows[0].values[5] == "10,5"
    assert rows[0].values[6] == sale_kind


def test_map_two_positions_keep_own_prices() -> None:
    # happy: суммы строк = цены позиций, не общая сумма чека 270 на каждой
    first = map_sale_to_export_rows(
        _sale(
            source_id="kitshop:1:1",
            sale_kind="micromarket",
            quantity=Decimal("1"),
            price=Decimal("190"),
            product_code="2311",
        ),
        tz=ZoneInfo("UTC"),
        machine_name="Холодильник",
        product_name="А",
    )
    second = map_sale_to_export_rows(
        _sale(
            source_id="kitshop:1:2",
            sale_kind="micromarket",
            quantity=Decimal("1"),
            price=Decimal("80"),
            product_code="2312",
        ),
        tz=ZoneInfo("UTC"),
        machine_name="Холодильник",
        product_name="Б",
    )
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].values[5] == "190"
    assert second[0].values[5] == "80"
    assert first[0].values[3] == "2311"
    assert second[0].values[3] == "2312"


def test_map_micromarket_non_integral_or_below_one_stays_one_row() -> None:
    # edge: строку не выбрасывать
    fractional = map_sale_to_export_rows(
        _sale(sale_kind="micromarket", quantity=Decimal("1.5"), price=Decimal("10")),
        tz=ZoneInfo("UTC"),
        machine_name=None,
        product_name=None,
    )
    zero = map_sale_to_export_rows(
        _sale(sale_kind="micromarket", quantity=Decimal("0"), price=Decimal("10")),
        tz=ZoneInfo("UTC"),
        machine_name=None,
        product_name=None,
    )
    assert len(fractional) == 1
    assert len(zero) == 1
    assert fractional[0].values[5] == "10"
    assert zero[0].values[5] == "10"


def _sale_at(i: int, *, machine: str = "m1") -> MachineSale:
    return MachineSale(
        source_id=f"s{i}",
        machine_id=MachineId(machine),
        product_code=f"P{i}",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 7, 1, tzinfo=UTC) + timedelta(minutes=i),
        ingested_at=datetime(2026, 7, 2, tzinfo=UTC),
        sale_kind="snack",
        machine_code=str(i),
        price=Decimal("1"),
    )


@beartype
@dataclass
class _FakeCursor:
    value: tuple[datetime, str] | None = None

    def load(self) -> tuple[datetime, str] | None:
        return self.value

    def save(self, *, occurred_at: datetime, source_id: str) -> None:
        self.value = (occurred_at, source_id)


@beartype
@dataclass
class _FakeSheet:
    headers_calls: int = 0
    appended: list[SalesSheetExportRow] = field(default_factory=list)
    trim_calls: list[int] = field(default_factory=list)
    fail_on_append_n: int | None = None
    _append_n: int = 0
    preexisting_data_rows: int = 0

    def ensure_header(self, headers: object) -> None:
        assert tuple(headers) == SALES_SHEET_EXPORT_HEADERS
        self.headers_calls += 1

    def append_rows(self, rows: object) -> None:
        self._append_n += 1
        if self.fail_on_append_n == self._append_n:
            raise RuntimeError("sheets boom")
        self.appended.extend(list(rows))  # type: ignore[arg-type]

    def trim_to_max_data_rows(self, max_rows: int) -> int:
        self.trim_calls.append(max_rows)
        total = self.preexisting_data_rows + len(self.appended)
        removed = max(0, total - max_rows)
        return removed


@beartype
@dataclass
class _FakeSales:
    all_sales: list[MachineSale]
    latest_limits: list[int] = field(default_factory=list)

    def list_latest(self, *, limit: int) -> list[MachineSale]:
        self.latest_limits.append(limit)
        ordered = sorted(
            self.all_sales,
            key=lambda s: (s.occurred_at, s.source_id),
            reverse=True,
        )
        newest = ordered[:limit]
        return sorted(newest, key=lambda s: (s.occurred_at, s.source_id))

    def list_after(
        self,
        *,
        occurred_at: datetime,
        source_id: str,
        limit: int,
    ) -> list[MachineSale]:
        after = [
            s
            for s in sorted(self.all_sales, key=lambda x: (x.occurred_at, x.source_id))
            if (s.occurred_at, s.source_id) > (occurred_at, source_id)
        ]
        return after[:limit]


class _Names:
    def name_for(self, key: object) -> str | None:
        return None


def _uc(
    sales: _FakeSales,
    cursor: _FakeCursor,
    sheet: _FakeSheet,
    *,
    max_rows: int = 100,
    page_size: int = 2,
) -> ExportSalesToSheet:
    return ExportSalesToSheet(
        sales=sales,  # type: ignore[arg-type]
        cursor=cursor,  # type: ignore[arg-type]
        sheet=sheet,  # type: ignore[arg-type]
        machines=_Names(),  # type: ignore[arg-type]
        products=_Names(),  # type: ignore[arg-type]
        timezone=ZoneInfo("UTC"),
        max_rows=max_rows,
        page_size=page_size,
    )


def test_backfill_pages_and_advances_cursor_per_chunk() -> None:
    sales = _FakeSales([_sale_at(i) for i in range(5)])
    cursor = _FakeCursor()
    sheet = _FakeSheet()
    result = _uc(sales, cursor, sheet, page_size=2).execute()
    assert sheet.headers_calls >= 1
    assert len(sheet.appended) == 5
    assert cursor.value == (sales.all_sales[4].occurred_at, "s4")
    assert sheet.trim_calls == [100]  # exported_count > 0 → trim (adapter may no-op)
    assert result.mode == "backfill"
    assert result.exported_count == 5
    assert result.pages == 3
    assert result.cursor_source_id == "s4"
    assert result.trimmed_count == 0


def test_backfill_uses_at_most_max_rows() -> None:
    sales = _FakeSales([_sale_at(i) for i in range(10)])
    cursor = _FakeCursor()
    sheet = _FakeSheet()
    _uc(sales, cursor, sheet, max_rows=3, page_size=10).execute()
    assert sales.latest_limits == [3]
    assert len(sheet.appended) == 3


def test_incremental_empty_is_noop() -> None:
    sales = _FakeSales([_sale_at(0)])
    cursor = _FakeCursor(value=(sales.all_sales[0].occurred_at, "s0"))
    sheet = _FakeSheet()
    result = _uc(sales, cursor, sheet).execute()
    assert sheet.appended == []
    assert sheet.headers_calls == 0
    assert sheet.trim_calls == []
    assert cursor.value == (sales.all_sales[0].occurred_at, "s0")
    assert result.mode == "incremental"
    assert result.exported_count == 0
    assert result.pages == 0
    assert result.cursor_source_id == "s0"
    assert result.trimmed_count == 0


def test_incremental_multi_page_until_exhausted() -> None:
    sales = _FakeSales([_sale_at(i) for i in range(5)])
    cursor = _FakeCursor(value=(sales.all_sales[0].occurred_at, "s0"))
    sheet = _FakeSheet()
    result = _uc(sales, cursor, sheet, page_size=2).execute()
    assert [r.values[3] for r in sheet.appended] == ["P1", "P2", "P3", "P4"]
    assert cursor.value == (sales.all_sales[4].occurred_at, "s4")
    assert result.mode == "incremental"
    assert result.exported_count == 4
    assert result.pages == 2


def test_append_fail_keeps_previous_chunk_cursor() -> None:
    sales = _FakeSales([_sale_at(i) for i in range(4)])
    cursor = _FakeCursor()
    sheet = _FakeSheet(fail_on_append_n=2)
    with pytest.raises(RuntimeError, match="sheets boom"):
        _uc(sales, cursor, sheet, page_size=2).execute()
    assert cursor.value == (sales.all_sales[1].occurred_at, "s1")
    assert len(sheet.appended) == 2


def test_trim_called_when_over_max_rows() -> None:
    sales = _FakeSales([_sale_at(i) for i in range(3)])
    cursor = _FakeCursor()
    sheet = _FakeSheet(preexisting_data_rows=5)
    result = _uc(sales, cursor, sheet, max_rows=6, page_size=10).execute()
    assert sheet.trim_calls == [6]
    assert result.trimmed_count == 2


def test_export_chunk_does_not_split_sale() -> None:
    # happy: две продажи по 2 строки, бюджет 3 → два append, курсор в конце на второй
    first = _sale(
        source_id="s0",
        sale_kind="micromarket",
        quantity=Decimal("2"),
        price=Decimal("190"),
        occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    second = _sale(
        source_id="s1",
        sale_kind="micromarket",
        quantity=Decimal("2"),
        price=Decimal("190"),
        occurred_at=datetime(2026, 9, 1, 11, 0, tzinfo=UTC),
    )
    sales = _FakeSales([first, second])
    cursor = _FakeCursor()
    sheet = _FakeSheet()
    result = _uc(sales, cursor, sheet, page_size=3).execute()
    assert result.exported_count == 4
    assert result.pages == 2
    assert len(sheet.appended) == 4
    assert cursor.value == (second.occurred_at, "s1")


def test_export_failed_append_keeps_cursor_on_previous_sale() -> None:
    # error: второй append падает, курсор на первой продаже, её две строки уже записаны
    first = _sale(
        source_id="s0",
        sale_kind="micromarket",
        quantity=Decimal("2"),
        price=Decimal("190"),
        occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    second = _sale(
        source_id="s1",
        sale_kind="micromarket",
        quantity=Decimal("2"),
        price=Decimal("190"),
        occurred_at=datetime(2026, 9, 1, 11, 0, tzinfo=UTC),
    )
    sales = _FakeSales([first, second])
    cursor = _FakeCursor()
    sheet = _FakeSheet(fail_on_append_n=2)
    with pytest.raises(RuntimeError, match="sheets boom"):
        _uc(sales, cursor, sheet, page_size=3).execute()
    assert cursor.value == (first.occurred_at, "s0")
    assert len(sheet.appended) == 2


def test_export_oversized_sale_is_its_own_append() -> None:
    # edge: строк больше бюджета — один append целиком
    sale = _sale(
        source_id="s0",
        sale_kind="micromarket",
        quantity=Decimal("5"),
        price=Decimal("10"),
        occurred_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    sales = _FakeSales([sale])
    cursor = _FakeCursor()
    sheet = _FakeSheet()
    result = _uc(sales, cursor, sheet, page_size=2).execute()
    assert result.pages == 1
    assert result.exported_count == 5
    assert len(sheet.appended) == 5
    assert cursor.value == (sale.occurred_at, "s0")
