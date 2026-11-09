from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.micromarket_loading.micromarket_sales_after import (
    MachineSalesMicromarketSalesAfter,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_AFTER = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_MACHINE = "701"


def _sale(**kwargs: object) -> MachineSale:
    base: dict[str, object] = dict(
        source_id="s1",
        machine_id=MachineId(_MACHINE),
        product_code="2311",
        quantity=Decimal("2"),
        occurred_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        sale_kind="micromarket",
        machine_code=_MACHINE,
        resolve_status=None,
    )
    base.update(kwargs)
    return MachineSale(**base)  # type: ignore[arg-type]


def test_micromarket_sales_after_returns_sales_after_anchor() -> None:
    """happy: resolved/kitshop sales after anchor mapped for replay."""
    sales_store = InMemoryMachineSalesStore()
    sales_store.insert_if_absent(_sale(source_id="after-anchor"))
    sales_store.insert_if_absent(
        _sale(
            source_id="at-anchor",
            occurred_at=_AFTER,
        ),
    )
    sales_store.insert_if_absent(
        _sale(
            source_id="other-machine",
            machine_code="702",
            machine_id=MachineId("702"),
            occurred_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
        ),
    )
    port = MachineSalesMicromarketSalesAfter(sales_store=sales_store)

    rows = port.query(_MACHINE, _AFTER)

    assert len(rows) == 1
    assert rows[0].sale_source_id == "after-anchor"
    assert rows[0].product_code == "2311"
    assert rows[0].qty == Decimal("2")


def test_micromarket_sales_after_skips_unresolved_and_snack() -> None:
    """edge: unresolved resolve_status and snack kind are omitted."""
    sales_store = InMemoryMachineSalesStore()
    sales_store.insert_if_absent(
        _sale(source_id="unresolved", resolve_status="unresolved_matrix"),
    )
    sales_store.insert_if_absent(
        _sale(source_id="snack-row", sale_kind="snack", resolve_status="resolved"),
    )
    sales_store.insert_if_absent(_sale(source_id="ok"))
    port = MachineSalesMicromarketSalesAfter(sales_store=sales_store)

    rows = port.query(_MACHINE, _AFTER)

    assert [row.sale_source_id for row in rows] == ["ok"]


def test_micromarket_sales_after_empty_when_no_sales() -> None:
    """edge: no sales → empty sequence."""
    port = MachineSalesMicromarketSalesAfter(sales_store=InMemoryMachineSalesStore())
    assert port.query(_MACHINE, _AFTER) == ()
