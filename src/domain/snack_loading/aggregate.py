from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import EventId
from src.domain.snack_loading.events import (
    CellKey,
    SnackInventoryAccepted,
    SnackLoadingApplied,
    SnackSaleDeducted,
    SnackStockAnomalyRecorded,
    SnackStockEvent,
)


def _new_event_id() -> EventId:
    return EventId(f"event-{uuid.uuid4()}")


@beartype
@dataclass(slots=True)
class SnackMachineStock:
    machine_code: str
    _cells: dict[CellKey, Decimal] = field(default_factory=dict, repr=False)
    _products: dict[CellKey, str] = field(default_factory=dict, repr=False)
    _has_completed_inventory: bool = field(default=False, repr=False)
    _seen_source_ids: set[str] = field(default_factory=set, repr=False)
    _seen_anomaly_source_ids: set[str] = field(default_factory=set, repr=False)
    _seen_inventory_ids: set[str] = field(default_factory=set, repr=False)
    _pending: list[SnackStockEvent] = field(default_factory=list, repr=False)
    _loaded_version: int = field(default=0, repr=False)

    @property
    def has_completed_inventory(self) -> bool:
        return self._has_completed_inventory

    @property
    @beartype
    def loaded_version(self) -> int:
        return self._loaded_version

    @beartype
    def qty(self, machine_code: str, logical_matrix_name: str, line_number: int) -> Decimal:
        return self._cells.get((machine_code, logical_matrix_name, line_number), Decimal("0"))

    @beartype
    def product(self, machine_code: str, logical_matrix_name: str, line_number: int) -> str | None:
        return self._products.get((machine_code, logical_matrix_name, line_number))

    @beartype
    def pull_events(self) -> tuple[SnackStockEvent, ...]:
        events = tuple(self._pending)
        self._pending.clear()
        return events

    @classmethod
    @beartype
    def rehydrate(
        cls,
        *,
        machine_code: str,
        events: Iterable[SnackStockEvent],
        loaded_version: int | None = None,
    ) -> SnackMachineStock:
        events_tuple = tuple(events)
        stock = cls(machine_code=machine_code)
        for event in events_tuple:
            stock._apply(event)
        stock._pending.clear()
        stock._loaded_version = len(events_tuple) if loaded_version is None else loaded_version
        return stock

    @beartype
    def apply_inventory(
        self,
        *,
        as_of: datetime,
        quantities: Mapping[CellKey, Decimal],
        product_by_key: Mapping[CellKey, str],
        inventory_id: str,
    ) -> SnackInventoryAccepted | None:
        if inventory_id in self._seen_inventory_ids:
            return None
        self._require_own_keys(quantities)
        self._require_own_keys(product_by_key)
        event = SnackInventoryAccepted(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            inventory_id=inventory_id,
            as_of=as_of,
            quantities=tuple(sorted(quantities.items())),
            product_by_key=tuple(sorted(product_by_key.items())),
            occurred_at=as_of,
        )
        self._apply(event)
        self._pending.append(event)
        return event

    @beartype
    def apply_sale_deduct(
        self,
        *,
        source_id: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
        quantity: Decimal,
        occurred_at: datetime,
    ) -> tuple[SnackStockAnomalyRecorded, ...]:
        if quantity <= 0:
            return ()
        if source_id in self._seen_source_ids:
            return ()

        cell_key: CellKey = (self.machine_code, logical_matrix_name, line_number)
        available = self._cells.get(cell_key, Decimal("0"))
        clamped = min(quantity, available)
        anomalies: list[SnackStockAnomalyRecorded] = []
        if clamped < quantity and source_id not in self._seen_anomaly_source_ids:
            anomaly = SnackStockAnomalyRecorded(
                event_id=_new_event_id(),
                machine_code=self.machine_code,
                source_id=source_id,
                cell_key=cell_key,
                requested_quantity=quantity,
                available_quantity=available,
                clamped_quantity=clamped,
                occurred_at=occurred_at,
            )
            self._apply(anomaly)
            self._pending.append(anomaly)
            anomalies.append(anomaly)

        event = SnackSaleDeducted(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            source_id=source_id,
            cell_key=cell_key,
            product_code=product_code,
            quantity=clamped,
            occurred_at=occurred_at,
        )
        self._apply(event)
        self._pending.append(event)
        return tuple(anomalies)

    @beartype
    def apply_loading(
        self,
        *,
        run_id: str,
        move_id: str,
        increments: Mapping[CellKey, Decimal],
        occurred_at: datetime,
    ) -> SnackLoadingApplied:
        self._require_own_keys(increments)
        event = SnackLoadingApplied(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            run_id=run_id,
            move_id=move_id,
            increments=tuple(sorted(increments.items())),
            occurred_at=occurred_at,
        )
        self._apply(event)
        self._pending.append(event)
        return event

    @beartype
    def _require_own_keys(self, mapping: Mapping[CellKey, object]) -> None:
        for machine_code, _, _ in mapping:
            if machine_code != self.machine_code:
                raise ValueError(
                    f"cell key machine_code {machine_code!r} does not match "
                    f"aggregate {self.machine_code!r}"
                )

    @beartype
    def _apply(self, event: SnackStockEvent) -> None:
        if isinstance(event, SnackInventoryAccepted):
            self._cells = {key: qty for key, qty in event.quantities}
            self._products = {key: product for key, product in event.product_by_key}
            self._has_completed_inventory = True
            self._seen_inventory_ids.add(event.inventory_id)
            self._seen_source_ids.clear()
            self._seen_anomaly_source_ids.clear()
            return

        if isinstance(event, SnackSaleDeducted):
            self._seen_source_ids.add(event.source_id)
            current = self._cells.get(event.cell_key, Decimal("0"))
            self._cells[event.cell_key] = current - event.quantity
            return

        if isinstance(event, SnackLoadingApplied):
            for key, increment in event.increments:
                current = self._cells.get(key, Decimal("0"))
                self._cells[key] = current + increment
            return

        if isinstance(event, SnackStockAnomalyRecorded):
            self._seen_anomaly_source_ids.add(event.source_id)
            return
