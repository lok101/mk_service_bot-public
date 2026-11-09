from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.application.snack_loading.accept_inventory import AcceptSnackInventory
from src.application.snack_loading.ports import ResolvedSaleForReplay
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError
from src.domain.snack_loading.events import SnackInventoryAccepted
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

_MACHINE = "514"
_CELL = (_MACHINE, "SnackA", 1)
_AS_OF = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 7, 2, 15, 0, tzinfo=UTC)


@dataclass(slots=True)
class _FakeSalesAfter:
    sales: Sequence[ResolvedSaleForReplay]

    def query(self, machine_code: str, after: datetime) -> Sequence[ResolvedSaleForReplay]:
        del machine_code
        return tuple(sale for sale in self.sales if sale.occurred_at > after)


class _ConflictOnceStore(InMemorySnackMachineStockStore):
    def __init__(self) -> None:
        super().__init__()
        self._fails = 1

    def save(self, stock: SnackMachineStock) -> None:
        if self._fails > 0:
            self._fails -= 1
            raise SnackStockConcurrencyError(machine_code=stock.machine_code)
        super().save(stock)


def _sale(
    *,
    source_id: str,
    occurred_at: datetime,
    quantity: Decimal = Decimal("1"),
    resolve_status: str = "resolved",
) -> ResolvedSaleForReplay:
    return ResolvedSaleForReplay(
        source_id=source_id,
        logical_matrix_name="SnackA",
        line_number=1,
        product_code="SKU1",
        quantity=quantity,
        occurred_at=occurred_at,
        resolve_status=resolve_status,
    )


def test_accept_snack_inventory_retries_on_stock_conflict() -> None:
    # error then happy
    stock_store = _ConflictOnceStore()
    uc = AcceptSnackInventory(
        stock_store=stock_store,
        sales_after=_FakeSalesAfter(sales=()),
    )
    uc.execute(
        machine_code=_MACHINE,
        mode="now",
        as_of=None,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-retry-1",
    )
    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("10")


def test_accept_snack_inventory_retry_idempotent_by_inventory_id() -> None:
    # error→happy: stream already has inventory_id; OCC retry must not duplicate it
    stock_store = _ConflictOnceStore()
    stock_store._fails = 0
    seed = SnackMachineStock(machine_code=_MACHINE)
    seed.apply_inventory(
        as_of=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-idem-1",
    )
    stock_store.save(seed)
    stock_store._fails = 1
    sale_after = _sale(
        source_id="sale-after",
        occurred_at=datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
    )
    uc = AcceptSnackInventory(
        stock_store=stock_store,
        sales_after=_FakeSalesAfter(sales=(sale_after,)),
    )
    uc.execute(
        machine_code=_MACHINE,
        mode="now",
        as_of=None,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-idem-1",
    )
    events = stock_store._streams.get(_MACHINE, ())
    inventory_events = [e for e in events if isinstance(e, SnackInventoryAccepted)]
    assert len(inventory_events) == 1
    assert inventory_events[0].inventory_id == "inv-idem-1"
    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("9")


def test_inventory_as_of_replays_sales_after_anchor() -> None:
    stock_store = InMemorySnackMachineStockStore()
    fake_sales = _FakeSalesAfter(
        sales=(
            _sale(
                source_id="sale-after",
                occurred_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
            ),
        ),
    )
    uc = AcceptSnackInventory(stock_store=stock_store, sales_after=fake_sales)

    uc.execute(
        machine_code=_MACHINE,
        mode="as_of",
        as_of=_AS_OF,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-1",
    )

    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("9")
    assert loaded.has_completed_inventory is True


def test_inventory_sale_exactly_at_as_of_not_replayed() -> None:
    stock_store = InMemorySnackMachineStockStore()
    fake_sales = _FakeSalesAfter(
        sales=(_sale(source_id="sale-at-anchor", occurred_at=_AS_OF),),
    )
    uc = AcceptSnackInventory(stock_store=stock_store, sales_after=fake_sales)

    uc.execute(
        machine_code=_MACHINE,
        mode="as_of",
        as_of=_AS_OF,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-2",
    )

    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("10")


def test_inventory_now_uses_submitted_at_as_anchor() -> None:
    stock_store = InMemorySnackMachineStockStore()
    fake_sales = _FakeSalesAfter(
        sales=(
            _sale(
                source_id="before-submit",
                occurred_at=datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
            ),
            _sale(
                source_id="after-submit",
                occurred_at=datetime(2026, 7, 2, 16, 0, tzinfo=UTC),
            ),
        ),
    )
    uc = AcceptSnackInventory(stock_store=stock_store, sales_after=fake_sales)

    uc.execute(
        machine_code=_MACHINE,
        mode="now",
        as_of=None,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-3",
    )

    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("9")
    assert loaded.has_completed_inventory is True


def test_inventory_replay_skips_unresolved_sales() -> None:
    stock_store = InMemorySnackMachineStockStore()
    fake_sales = _FakeSalesAfter(
        sales=(
            _sale(
                source_id="unresolved-after",
                occurred_at=datetime(2026, 7, 1, 13, 0, tzinfo=UTC),
                resolve_status="unresolved_matrix",
            ),
        ),
    )
    uc = AcceptSnackInventory(stock_store=stock_store, sales_after=fake_sales)

    uc.execute(
        machine_code=_MACHINE,
        mode="as_of",
        as_of=_AS_OF,
        submitted_at=_SUBMITTED_AT,
        quantities={_CELL: Decimal("10")},
        product_by_key={_CELL: "SKU1"},
        inventory_id="inv-4",
    )

    loaded = stock_store.load(_MACHINE)
    assert loaded is not None
    assert loaded.qty(*_CELL) == Decimal("10")
