from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading import AcceptMicromarketInventory
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.micromarket_loading.micromarket_sales_after import (
    MachineSalesMicromarketSalesAfter,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_MACHINE = "701"
_T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_T1 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def test_accept_replays_machine_sales_after_inventory_anchor() -> None:
    """happy: Accept + MachineSalesMicromarketSalesAfter deducts sale after anchor."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    sales_store = InMemoryMachineSalesStore()
    sales_store.insert_if_absent(
        MachineSale(
            source_id="sale-after",
            machine_id=MachineId(_MACHINE),
            product_code="2311",
            quantity=Decimal("2"),
            occurred_at=_T1,
            ingested_at=_T1,
            sale_kind="micromarket",
            machine_code=_MACHINE,
        ),
    )
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=MachineSalesMicromarketSalesAfter(sales_store=sales_store),
    )
    uc.execute(
        mode="as_of",
        machine_code=_MACHINE,
        quantities={"2311": Decimal("10")},
        inventory_id="inv-asof-sales",
        submitted_at=datetime(2026, 9, 2, tzinfo=UTC),
        as_of_from_form=_T0,
    )
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("8")
