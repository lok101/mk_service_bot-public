from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from src.domain.micromarket_loading import (
    MicromarketDeviceStock,
    MicromarketStockAnomalyRecorded,
    MicromarketStockEvent,
)
from src.domain.snack_loading import (
    CellKey,
    SnackMachineStock,
    SnackStockAnomalyRecorded,
    SnackStockEvent,
)

from .strategies import (
    AWARE_DATETIMES,
    NON_NEGATIVE_DECIMALS,
    NON_NEGATIVE_SKU_MAPS,
    POSITIVE_DECIMAL,
    SKU,
    TOKEN,
)

SNACK_CELL = st.tuples(
    st.just("501"),
    st.sampled_from(("A", "B")),
    st.integers(min_value=1, max_value=8),
)
SNACK_CELL_NON_NEGATIVE_MAP = st.dictionaries(SNACK_CELL, NON_NEGATIVE_DECIMALS, max_size=4)

_SNACK_MACHINE = "501"
_MICROMARKET_MACHINE = "701"
_OVERSELL_MOMENT = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
_INVENTORY_MOMENT = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
_LOADING_MOMENT = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
_SNACK_CELL_KEY: CellKey = ("501", "A", 1)
_SNACK_OVERSELL_QTY = Decimal("5.000")
_SNACK_AVAILABLE_QTY = Decimal("2.000")
_MM_PRODUCT = "coffee"
_MM_LOAD_QTY = Decimal("3.000")
_MM_AVAILABLE_QTY = Decimal("1.000")
_MM_OVERSELL_QTY = Decimal("10.000")


class SnackStockStateMachine(RuleBasedStateMachine):
    @initialize()
    def initialize(self) -> None:
        self.stock = SnackMachineStock(machine_code=_SNACK_MACHINE)
        self.events: list[SnackStockEvent] = []
        self.oracle_qty: dict[CellKey, Decimal] = {}
        self.seen_sources: set[str] = set()
        self.current_pending: list[SnackStockEvent] = []

    def _sync_pending(self) -> None:
        self.current_pending = list(self.stock._pending)

    @rule(quantities=SNACK_CELL_NON_NEGATIVE_MAP, inventory_id=TOKEN, as_of=AWARE_DATETIMES)
    def inventory(
        self,
        quantities: dict[CellKey, Decimal],
        inventory_id: str,
        as_of: datetime,
    ) -> None:
        product_by_key = {key: f"sku-{key[1]}-{key[2]}" for key in quantities}
        accepted = self.stock.apply_inventory(
            as_of=as_of,
            quantities=quantities,
            product_by_key=product_by_key,
            inventory_id=inventory_id,
        )
        if accepted is not None:
            self.oracle_qty = dict(quantities)
            self.seen_sources.clear()
        self._sync_pending()

    @rule(increments=SNACK_CELL_NON_NEGATIVE_MAP, run_id=TOKEN, move_id=TOKEN, at=AWARE_DATETIMES)
    def loading(
        self,
        increments: dict[CellKey, Decimal],
        run_id: str,
        move_id: str,
        at: datetime,
    ) -> None:
        self.stock.apply_loading(
            run_id=run_id,
            move_id=move_id,
            increments=increments,
            occurred_at=at,
        )
        for key, increment in increments.items():
            self.oracle_qty[key] = self.oracle_qty.get(key, Decimal("0")) + increment
        self._sync_pending()

    @rule(cell=SNACK_CELL, quantity=POSITIVE_DECIMAL, source_id=TOKEN, at=AWARE_DATETIMES)
    def sale(
        self,
        cell: CellKey,
        quantity: Decimal,
        source_id: str,
        at: datetime,
    ) -> None:
        _machine, logical_matrix_name, line_number = cell
        already_seen = source_id in self.seen_sources
        anomalies = self.stock.apply_sale_deduct(
            source_id=source_id,
            logical_matrix_name=logical_matrix_name,
            line_number=line_number,
            product_code=self.stock.product(*cell) or "sku-unknown",
            quantity=quantity,
            occurred_at=at,
        )
        self._sync_pending()
        if already_seen:
            assert anomalies == ()
            return
        available = self.oracle_qty.get(cell, Decimal("0"))
        clamped = min(quantity, available)
        if clamped < quantity:
            assert len(anomalies) == 1
            assert isinstance(anomalies[0], SnackStockAnomalyRecorded)
            assert anomalies[0].clamped_quantity == clamped
        else:
            assert anomalies == ()
        self.oracle_qty[cell] = available - clamped
        self.seen_sources.add(source_id)

    @rule()
    def clear_pending_save_boundary(self) -> None:
        self.events.extend(self.stock.pull_events())
        self.current_pending.clear()

    @invariant()
    def quantities_are_non_negative_and_match_replay(self) -> None:
        pending = self.current_pending
        replayed = SnackMachineStock.rehydrate(
            machine_code=_SNACK_MACHINE,
            events=[*self.events, *pending],
        )
        for key, expected in self.oracle_qty.items():
            assert expected >= 0
            assert self.stock.qty(*key) == replayed.qty(*key) == expected
        assert self.stock.has_completed_inventory == replayed.has_completed_inventory


class MicromarketStockStateMachine(RuleBasedStateMachine):
    @initialize()
    def initialize(self) -> None:
        self.stock = MicromarketDeviceStock(machine_code=_MICROMARKET_MACHINE)
        self.events: list[MicromarketStockEvent] = []
        self.oracle_qty: dict[str, Decimal] = {}
        self.seen_sources: set[str] = set()
        self.known_source_ids: set[str] = set()
        self.current_pending: list[MicromarketStockEvent] = []

    def _sync_pending(self) -> None:
        self.current_pending = list(self.stock._pending)

    @rule(quantities=NON_NEGATIVE_SKU_MAPS, inventory_id=TOKEN, as_of=AWARE_DATETIMES)
    def inventory(
        self,
        quantities: dict[str, Decimal],
        inventory_id: str,
        as_of: datetime,
    ) -> None:
        accepted = self.stock.apply_inventory(
            as_of=as_of,
            quantities=quantities,
            inventory_id=inventory_id,
        )
        if accepted is not None:
            self.oracle_qty = dict(quantities)
            self.seen_sources.clear()
        self._sync_pending()

    @rule(lines=NON_NEGATIVE_SKU_MAPS, run_id=TOKEN, at=AWARE_DATETIMES)
    def loading(
        self,
        lines: dict[str, Decimal],
        run_id: str,
        at: datetime,
    ) -> None:
        applied = self.stock.apply_loading(
            lines=lines,
            loading_run_id=run_id,
            occurred_at=at,
        )
        if applied is not None:
            for product_code, increment in lines.items():
                self.oracle_qty[product_code] = (
                    self.oracle_qty.get(product_code, Decimal("0")) + increment
                )
        self._sync_pending()

    @rule(product_code=SKU, quantity=POSITIVE_DECIMAL, source_id=TOKEN, at=AWARE_DATETIMES)
    def sale(
        self,
        product_code: str,
        quantity: Decimal,
        source_id: str,
        at: datetime,
    ) -> None:
        already_seen = source_id in self.seen_sources
        self.known_source_ids.add(source_id)
        anomalies = self.stock.apply_sale_deduct(
            sale_source_id=source_id,
            product_code=product_code,
            qty=quantity,
            occurred_at=at,
        )
        self._sync_pending()
        if already_seen:
            assert anomalies == ()
            return
        available = self.oracle_qty.get(product_code, Decimal("0"))
        clamped = min(quantity, available)
        if clamped < quantity:
            assert len(anomalies) == 1
            assert isinstance(anomalies[0], MicromarketStockAnomalyRecorded)
            assert anomalies[0].clamped_qty == clamped
        else:
            assert anomalies == ()
        self.oracle_qty[product_code] = available - clamped
        self.seen_sources.add(source_id)

    @rule()
    def clear_pending_save_boundary(self) -> None:
        self.events.extend(self.stock.pull_events())
        self.current_pending.clear()

    @invariant()
    def live_oracle_replay_match(self) -> None:
        pending = self.current_pending
        replayed = MicromarketDeviceStock.rehydrate(
            machine_code=_MICROMARKET_MACHINE,
            events=[*self.events, *pending],
        )
        for product_code, expected in self.oracle_qty.items():
            assert expected >= 0
            assert self.stock.qty(product_code) == replayed.qty(product_code) == expected
        assert self.stock.quantities() == replayed.quantities() == self.oracle_qty
        assert self.stock.has_completed_inventory == replayed.has_completed_inventory
        for source_id in self.known_source_ids:
            expected_seen = source_id in self.seen_sources
            assert self.stock.has_seen_sale_source_id(source_id) is expected_seen
            assert replayed.has_seen_sale_source_id(source_id) is expected_seen


class TestSnackStockStateMachine(SnackStockStateMachine.TestCase):
    settings = settings(
        max_examples=100,
        stateful_step_count=50,
        deadline=None,
    )


class TestMicromarketStockStateMachine(MicromarketStockStateMachine.TestCase):
    settings = settings(
        max_examples=100,
        stateful_step_count=50,
        deadline=None,
    )


def test_snack_oversell_then_duplicate_source_stays_zero_after_replay() -> None:
    """INV-STK-001: oversell clamps to zero; duplicate source is a no-op after replay."""
    stock = SnackMachineStock(machine_code=_SNACK_MACHINE)
    stock.apply_inventory(
        as_of=_INVENTORY_MOMENT,
        quantities={_SNACK_CELL_KEY: _SNACK_AVAILABLE_QTY},
        product_by_key={_SNACK_CELL_KEY: "sku-A-1"},
        inventory_id="id-a",
    )
    anomalies = stock.apply_sale_deduct(
        source_id="id-b",
        logical_matrix_name="A",
        line_number=1,
        product_code="sku-A-1",
        quantity=_SNACK_OVERSELL_QTY,
        occurred_at=_OVERSELL_MOMENT,
    )
    assert len(anomalies) == 1
    assert stock.qty(*_SNACK_CELL_KEY) == Decimal("0")
    duplicate = stock.apply_sale_deduct(
        source_id="id-b",
        logical_matrix_name="A",
        line_number=1,
        product_code="sku-A-1",
        quantity=_SNACK_OVERSELL_QTY,
        occurred_at=_OVERSELL_MOMENT,
    )
    assert duplicate == ()
    assert stock.qty(*_SNACK_CELL_KEY) == Decimal("0")
    events = list(stock.pull_events())
    replayed = SnackMachineStock.rehydrate(machine_code=_SNACK_MACHINE, events=events)
    assert replayed.qty(*_SNACK_CELL_KEY) == Decimal("0")
    assert stock.qty(*_SNACK_CELL_KEY) == replayed.qty(*_SNACK_CELL_KEY)


def test_micromarket_inventory_loading_oversell_stays_non_negative_after_replay() -> None:
    """INV-STK-001: inventory+loading+oversell stays non-negative and matches replay."""
    stock = MicromarketDeviceStock(machine_code=_MICROMARKET_MACHINE)
    stock.apply_inventory(
        as_of=_INVENTORY_MOMENT,
        quantities={_MM_PRODUCT: _MM_AVAILABLE_QTY},
        inventory_id="id-a",
    )
    stock.apply_loading(
        lines={_MM_PRODUCT: _MM_LOAD_QTY},
        loading_run_id="id-b",
        occurred_at=_LOADING_MOMENT,
    )
    anomalies = stock.apply_sale_deduct(
        sale_source_id="id-c",
        product_code=_MM_PRODUCT,
        qty=_MM_OVERSELL_QTY,
        occurred_at=_OVERSELL_MOMENT,
    )
    assert len(anomalies) == 1
    assert stock.qty(_MM_PRODUCT) == Decimal("0")
    events = list(stock.pull_events())
    replayed = MicromarketDeviceStock.rehydrate(
        machine_code=_MICROMARKET_MACHINE,
        events=events,
    )
    assert replayed.qty(_MM_PRODUCT) == Decimal("0")
    assert stock.quantities() == replayed.quantities()
    assert all(qty >= 0 for qty in stock.quantities().values())


def test_snack_and_micromarket_state_machines() -> None:
    """Registry anchor: both stateful suites keep the required Hypothesis budget."""
    assert TestSnackStockStateMachine.settings.max_examples >= 100
    assert TestMicromarketStockStateMachine.settings.max_examples >= 100
