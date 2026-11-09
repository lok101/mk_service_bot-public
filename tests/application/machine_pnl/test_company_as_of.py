from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.inventory_reconciliation import MachineCompanyOccupancy
from src.application.machine_pnl.company_as_of import resolve_month_company_id
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_MACHINE = MachineId("101")
_TZ = ZoneInfo("UTC")
_START = date(2026, 7, 1)
_END = date(2026, 7, 31)


def _sale(
    *,
    source_id: str,
    day: int,
    company_id: int | None,
    price: Decimal = Decimal("10"),
    qty: Decimal = Decimal("1"),
) -> MachineSale:
    occurred = datetime(2026, 7, day, 12, 0, tzinfo=UTC)
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE,
        product_code="2301",
        quantity=qty,
        occurred_at=occurred,
        ingested_at=occurred,
        sale_kind="coffee",
        price=price,
        company_id=company_id,
    )


def _occ(
    *,
    company_id: int,
    valid_from: datetime,
    valid_to: datetime | None = None,
) -> MachineCompanyOccupancy:
    return MachineCompanyOccupancy(
        machine_id=_MACHINE,
        company_id=company_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_as_of_single_company_from_sales() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(_sale(source_id="a", day=5, company_id=42),),
        occupancies=(),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id == 42
    assert warnings == ()


def test_as_of_majority_revenue_adds_warning() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(
            _sale(source_id="a", day=2, company_id=1, price=Decimal("10"), qty=Decimal("1")),
            _sale(source_id="b", day=20, company_id=2, price=Decimal("10"), qty=Decimal("3")),
        ),
        occupancies=(
            _occ(
                company_id=1,
                valid_from=datetime(2026, 6, 1, tzinfo=UTC),
                valid_to=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            ),
            _occ(company_id=2, valid_from=datetime(2026, 7, 20, 12, 0, tzinfo=UTC)),
        ),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id == 2
    assert [item.code for item in warnings] == ["company_majority_assumption"]


def test_as_of_revenue_tie_uses_later_valid_from() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(
            _sale(source_id="a", day=2, company_id=1, price=Decimal("10")),
            _sale(source_id="b", day=20, company_id=2, price=Decimal("10")),
        ),
        occupancies=(
            _occ(
                company_id=1,
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                valid_to=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            ),
            _occ(company_id=2, valid_from=datetime(2026, 7, 20, 12, 0, tzinfo=UTC)),
        ),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id == 2
    assert [item.code for item in warnings] == ["company_majority_assumption"]


def test_as_of_open_occupancy_when_month_has_no_company_sales() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(),
        occupancies=(_occ(company_id=7, valid_from=datetime(2026, 1, 1, tzinfo=UTC)),),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id == 7
    assert warnings == ()


def test_as_of_none_when_no_sales_and_no_occupancy() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(_sale(source_id="a", day=5, company_id=None),),
        occupancies=(),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id is None
    assert warnings == ()


def test_as_of_multiple_occupancies_without_sales_picks_later_valid_from() -> None:
    company_id, warnings = resolve_month_company_id(
        sales=(),
        occupancies=(
            _occ(
                company_id=1,
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                valid_to=datetime(2026, 7, 15, tzinfo=UTC),
            ),
            _occ(company_id=2, valid_from=datetime(2026, 7, 15, tzinfo=UTC)),
        ),
        period_start=_START,
        period_end=_END,
        tz=_TZ,
    )
    assert company_id == 2
    assert [item.code for item in warnings] == ["company_majority_assumption"]
