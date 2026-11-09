from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse import (
    TechnicianWarehouse,
    TechnicianWarehouseLine,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
    TransferDirection,
)
from src.domain.technician_warehouse.events import TechnicianWarehouseEvent

from .stateful_helpers import ORDERED_MOMENTS, WarehouseOracle, _delta_view, warehouse_view
from .strategies import POSITIVE_DECIMAL, SKU, SKU_MAPS, TOKEN

TRANSFER_ID = TOKEN
WAREHOUSE_LINES = st.dictionaries(SKU, POSITIVE_DECIMAL, max_size=4)
MOMENTS = st.sampled_from(ORDERED_MOMENTS)
_TECHNICIAN_ID = TechnicianId("tech-property")
_DOCUMENT_ID = "id-a"
_FORM_TOKEN = "id-b"
_FORM_TOKEN_SECOND = "id-c"
_TRANSFER_MOMENT = ORDERED_MOMENTS[0]
_INVENTORY_MOMENT = ORDERED_MOMENTS[1]
_SECOND_INVENTORY_MOMENT = ORDERED_MOMENTS[2]
_TRANSFER_QTY = Decimal("2.000")
_INVENTORY_QTY = Decimal("1.000")
_SECOND_INVENTORY_QTY = Decimal("3.000")


def _lines_from_map(lines: dict[str, Decimal]) -> tuple[TechnicianWarehouseLine, ...]:
    return tuple(
        TechnicianWarehouseLine(sku=sku, quantity_base=quantity) for sku, quantity in lines.items()
    )


def _supply_event(
    *,
    technician_id: TechnicianId,
    document_id: str,
    lines: dict[str, Decimal],
    moment: datetime,
) -> TechnicianWarehouseTransferObserved:
    return TechnicianWarehouseTransferObserved(
        event_id=EventId(f"wh-transfer-{document_id}-{moment.isoformat()}"),
        technician_id=technician_id,
        occurred_at=moment,
        external_document_id=document_id,
        moment=moment,
        updated_at=moment,
        observed_at=moment,
        content_hash=f"hash-{document_id}",
        direction=TransferDirection.SUPPLY_IN,
        lines=_lines_from_map(lines),
    )


class TechnicianWarehouseStateMachine(RuleBasedStateMachine):
    @initialize()
    def initialize(self) -> None:
        self.warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
        self.oracle = WarehouseOracle()
        self.durable_events: list[TechnicianWarehouseEvent] = []
        self.known_document_ids: set[str] = set()
        self.last_supply: dict[str, tuple[dict[str, Decimal], datetime]] = {}
        self.form_tokens: list[str] = []

    @rule(document_id=TRANSFER_ID, lines=WAREHOUSE_LINES, moment=MOMENTS)
    def observe_supply(
        self,
        document_id: str,
        lines: dict[str, Decimal],
        moment: datetime,
    ) -> None:
        if not lines:
            return
        event = _supply_event(
            technician_id=self.warehouse.technician_id,
            document_id=document_id,
            lines=lines,
            moment=moment,
        )
        applied = self.warehouse.observe_transfer(event)
        self.oracle.observe_supply(document_id, lines, moment, f"hash-{document_id}")
        self.known_document_ids.add(document_id)
        if applied is not None:
            self.last_supply[document_id] = (dict(lines), moment)

    @rule(source_event_id=TRANSFER_ID, lines=WAREHOUSE_LINES, at=MOMENTS)
    def observe_loading(
        self,
        source_event_id: str,
        lines: dict[str, Decimal],
        at: datetime,
    ) -> None:
        if not lines:
            return
        event = TechnicianWarehouseLoadingObserved(
            event_id=EventId(f"wh-load-{source_event_id}"),
            technician_id=self.warehouse.technician_id,
            occurred_at=at,
            source_event_id=source_event_id,
            machine_id=MachineId("vm-property"),
            submitted_at=at,
            lines=_lines_from_map(lines),
        )
        self.warehouse.observe_loading(event)
        self.oracle.observe_loading(source_event_id, lines, at)

    @rule(inventory_id=TRANSFER_ID, form_token=TRANSFER_ID, actual=SKU_MAPS, at=MOMENTS)
    def count_inventory(
        self,
        inventory_id: str,
        form_token: str,
        actual: dict[str, Decimal],
        at: datetime,
    ) -> None:
        self.warehouse.count_inventory(
            inventory_id=inventory_id,
            form_token=form_token,
            counted_at=at,
            actual_by_sku=actual,
            baseline=False,
        )
        self.oracle.count_inventory(
            inventory_id=inventory_id,
            form_token=form_token,
            actual=actual,
            counted_at=at,
            baseline=False,
        )
        if form_token not in self.form_tokens:
            self.form_tokens.append(form_token)

    @rule(document_id=TRANSFER_ID)
    def observe_duplicate_transfer(self, document_id: str) -> None:
        previous = self.last_supply.get(document_id)
        if previous is None:
            return
        lines, moment = previous
        event = _supply_event(
            technician_id=self.warehouse.technician_id,
            document_id=document_id,
            lines=lines,
            moment=moment,
        )
        self.warehouse.observe_transfer(event)
        self.oracle.observe_supply(document_id, lines, moment, f"hash-{document_id}")

    @rule(document_id=TRANSFER_ID, lines=WAREHOUSE_LINES, at=MOMENTS)
    def observe_older_transfer(
        self,
        document_id: str,
        lines: dict[str, Decimal],
        at: datetime,
    ) -> None:
        previous = self.last_supply.get(document_id)
        if previous is None or not lines or at >= previous[1]:
            return
        event = _supply_event(
            technician_id=self.warehouse.technician_id,
            document_id=document_id,
            lines=lines,
            moment=at,
        )
        self.warehouse.observe_transfer(event)
        self.oracle.observe_supply(document_id, lines, at, f"hash-{document_id}")

    @rule(document_id=TRANSFER_ID, at=MOMENTS)
    def void_transfer_once_or_idempotently(self, document_id: str, at: datetime) -> None:
        if self.warehouse.is_transfer_finalized(document_id):
            return
        self.warehouse.void_transfer(external_document_id=document_id, observed_at=at)
        self.warehouse.void_transfer(external_document_id=document_id, observed_at=at)
        self.oracle.void(document_id)
        self.known_document_ids.add(document_id)

    @rule(at=MOMENTS)
    def finalize_known_transfers(self, at: datetime) -> None:
        document_ids = tuple(sorted(self.warehouse.observed_transfer_document_ids()))
        if not document_ids:
            return
        self.warehouse.finalize_transfers(
            session_id="sess-property",
            external_document_ids=document_ids,
            finalized_at=at,
        )
        self.oracle.finalize(document_ids)
        self.known_document_ids.update(document_ids)

    @rule(inventory_id=TRANSFER_ID, actual=SKU_MAPS, at=MOMENTS)
    def repeat_inventory_form_token(
        self,
        inventory_id: str,
        actual: dict[str, Decimal],
        at: datetime,
    ) -> None:
        if not self.form_tokens:
            return
        form_token = self.form_tokens[0]
        self.warehouse.count_inventory(
            inventory_id=inventory_id,
            form_token=form_token,
            counted_at=at,
            actual_by_sku=actual,
            baseline=False,
        )
        self.oracle.count_inventory(
            inventory_id=inventory_id,
            form_token=form_token,
            actual=actual,
            counted_at=at,
            baseline=False,
        )

    @rule()
    def clear_pending_save_boundary(self) -> None:
        self.durable_events.extend(self.warehouse.collect_events())
        self.warehouse.clear_pending_events()

    @invariant()
    def calculated_stock_matches_oracle(self) -> None:
        assert self.warehouse.calculated_stock_since_baseline() == self.oracle.stock()

    @invariant()
    def latest_delta_matches_inventory_flow_oracle(self) -> None:
        assert (
            _delta_view(self.warehouse.compute_warehouse_delta_between_latest_inventories())
            == self.oracle.latest_delta_view()
        )

    @invariant()
    def replay_matches_live(self) -> None:
        all_events = [*self.durable_events, *self.warehouse.collect_events()]
        replayed = TechnicianWarehouse.rehydrate(self.warehouse.technician_id, all_events)
        known = frozenset(self.known_document_ids)
        assert warehouse_view(replayed, known) == warehouse_view(self.warehouse, known)


class TestTechnicianWarehouseStateMachine(TechnicianWarehouseStateMachine.TestCase):
    settings = settings(
        max_examples=100,
        stateful_step_count=50,
        deadline=None,
    )


def test_duplicate_transfer_and_inventory_ids_preserve_replay_state() -> None:
    """INV-WH-002: duplicate transfer and inventory ids stay one effect after replay."""
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    lines = {"coffee": _TRANSFER_QTY}
    event = _supply_event(
        technician_id=_TECHNICIAN_ID,
        document_id=_DOCUMENT_ID,
        lines=lines,
        moment=_TRANSFER_MOMENT,
    )
    warehouse.observe_transfer(event)
    warehouse.observe_transfer(event)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token=_FORM_TOKEN,
        counted_at=_INVENTORY_MOMENT,
        actual_by_sku={"coffee": _INVENTORY_QTY},
        baseline=False,
    )
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token=_FORM_TOKEN,
        counted_at=_INVENTORY_MOMENT,
        actual_by_sku={"coffee": Decimal("9.000")},
        baseline=False,
    )
    events = list(warehouse.collect_events())
    warehouse.clear_pending_events()
    replayed = TechnicianWarehouse.rehydrate(warehouse.technician_id, events)
    known = frozenset({_DOCUMENT_ID})
    assert warehouse.observed_transfer_document_ids() == frozenset({_DOCUMENT_ID})
    assert warehouse.latest_inventory_id == "inv-1"
    assert warehouse.calculated_stock_since_baseline() == {"coffee": _TRANSFER_QTY}
    assert warehouse_view(replayed, known) == warehouse_view(warehouse, known)
    live_delta = _delta_view(warehouse.compute_warehouse_delta_between_latest_inventories())
    replay_delta = _delta_view(replayed.compute_warehouse_delta_between_latest_inventories())
    assert live_delta == replay_delta
    assert live_delta == {"coffee": _INVENTORY_QTY - _TRANSFER_QTY}


def test_two_inventories_distinct_form_tokens_preserve_session_delta_after_replay() -> None:
    """Edge: session delta between two inventories survives replay via warehouse_view."""
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    lines = {"coffee": _TRANSFER_QTY}
    event = _supply_event(
        technician_id=_TECHNICIAN_ID,
        document_id=_DOCUMENT_ID,
        lines=lines,
        moment=_TRANSFER_MOMENT,
    )
    warehouse.observe_transfer(event)
    warehouse.count_inventory(
        inventory_id="inv-1",
        form_token=_FORM_TOKEN,
        counted_at=_INVENTORY_MOMENT,
        actual_by_sku={"coffee": _INVENTORY_QTY},
        baseline=False,
    )
    warehouse.count_inventory(
        inventory_id="inv-2",
        form_token=_FORM_TOKEN_SECOND,
        counted_at=_SECOND_INVENTORY_MOMENT,
        actual_by_sku={"coffee": _SECOND_INVENTORY_QTY},
        baseline=False,
    )
    events = list(warehouse.collect_events())
    warehouse.clear_pending_events()
    replayed = TechnicianWarehouse.rehydrate(warehouse.technician_id, events)
    known = frozenset({_DOCUMENT_ID})
    assert warehouse.latest_inventory_id == "inv-2"
    assert warehouse_view(replayed, known) == warehouse_view(warehouse, known)
    live_delta = _delta_view(warehouse.compute_warehouse_delta_between_latest_inventories())
    replay_delta = _delta_view(replayed.compute_warehouse_delta_between_latest_inventories())
    assert live_delta == replay_delta
    # Between inv-1 and inv-2: no transfers in window → delta = actual2 − actual1.
    assert live_delta == {"coffee": _SECOND_INVENTORY_QTY - _INVENTORY_QTY}
