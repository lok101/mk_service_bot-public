from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import EventId
from src.domain.micromarket_loading.events import (
    MicromarketInventoryAccepted,
    MicromarketLoadingApplied,
    MicromarketSaleDeducted,
    MicromarketStockAnomalyRecorded,
    MicromarketStockEvent,
)


def _new_event_id() -> EventId:
    return EventId(f"event-{uuid.uuid4()}")


@beartype
@dataclass(slots=True)
class MicromarketDeviceStock:
    machine_code: str
    _qty: dict[str, Decimal] = field(default_factory=dict, repr=False)
    _last_factual: dict[str, Decimal] = field(default_factory=dict, repr=False)
    _basis: dict[str, str] = field(default_factory=dict, repr=False)
    _has_completed_inventory: bool = field(default=False, repr=False)
    _seen_sale_source_ids: set[str] = field(default_factory=set, repr=False)
    _seen_anomaly_sale_source_ids: set[str] = field(default_factory=set, repr=False)
    _seen_inventory_ids: set[str] = field(default_factory=set, repr=False)
    _seen_loading_run_ids: set[str] = field(default_factory=set, repr=False)
    _pending: list[MicromarketStockEvent] = field(default_factory=list, repr=False)
    _loaded_version: int = field(default=0, repr=False)

    @property
    def has_completed_inventory(self) -> bool:
        return self._has_completed_inventory

    @property
    @beartype
    def loaded_version(self) -> int:
        return self._loaded_version

    @beartype
    def qty(self, product_code: str) -> Decimal:
        return self._qty.get(product_code, Decimal("0"))

    @beartype
    def last_factual_qty(self, product_code: str) -> Decimal | None:
        return self._last_factual.get(product_code)

    @beartype
    def quantity_basis(self, product_code: str) -> str | None:
        return self._basis.get(product_code)

    @beartype
    def quantities(self) -> dict[str, Decimal]:
        return dict(self._qty)

    @beartype
    def has_seen_sale_source_id(self, sale_source_id: str) -> bool:
        return sale_source_id in self._seen_sale_source_ids

    @beartype
    def pull_events(self) -> tuple[MicromarketStockEvent, ...]:
        events = tuple(self._pending)
        self._pending.clear()
        return events

    @classmethod
    @beartype
    def rehydrate(
        cls,
        *,
        machine_code: str,
        events: Iterable[MicromarketStockEvent],
        loaded_version: int | None = None,
    ) -> MicromarketDeviceStock:
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
        quantities: Mapping[str, Decimal],
        inventory_id: str,
        partial: bool = False,
    ) -> MicromarketInventoryAccepted | None:
        if inventory_id in self._seen_inventory_ids:
            return None
        for quantity in quantities.values():
            if quantity < 0:
                raise ValueError("inventory quantity must not be negative")
        prior_codes = set(self._qty)
        event = MicromarketInventoryAccepted(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            inventory_id=inventory_id,
            as_of=as_of,
            quantities=tuple(sorted(quantities.items())),
            occurred_at=as_of,
            partial=partial,
        )
        self._apply(event)
        self._pending.append(event)
        if partial:
            explicit = {code for code, _qty in event.quantities}
            for code in sorted(prior_codes - explicit):
                qty = self._qty.get(code, Decimal("0"))
                if qty <= 0:
                    continue
                anomaly = MicromarketStockAnomalyRecorded(
                    event_id=_new_event_id(),
                    machine_code=self.machine_code,
                    kind="inventory_line_omitted",
                    product_code=code,
                    detail=f"omitted available={qty}",
                    sale_source_id="",
                    requested_qty=Decimal("0"),
                    available_qty=qty,
                    clamped_qty=Decimal("0"),
                    occurred_at=event.occurred_at,
                )
                self._apply(anomaly)
                self._pending.append(anomaly)
        return event

    @beartype
    def apply_sale_deduct(
        self,
        *,
        sale_source_id: str,
        product_code: str,
        qty: Decimal,
        occurred_at: datetime,
    ) -> tuple[MicromarketStockAnomalyRecorded, ...]:
        if qty <= 0:
            return ()
        if sale_source_id in self._seen_sale_source_ids:
            return ()

        available = self._qty.get(product_code, Decimal("0"))
        clamped = min(qty, available)
        anomalies: list[MicromarketStockAnomalyRecorded] = []
        if clamped < qty and sale_source_id not in self._seen_anomaly_sale_source_ids:
            anomaly = MicromarketStockAnomalyRecorded(
                event_id=_new_event_id(),
                machine_code=self.machine_code,
                kind="oversell_clamp",
                product_code=product_code,
                detail=(f"requested={qty} available={available} clamped={clamped}"),
                sale_source_id=sale_source_id,
                requested_qty=qty,
                available_qty=available,
                clamped_qty=clamped,
                occurred_at=occurred_at,
            )
            self._apply(anomaly)
            self._pending.append(anomaly)
            anomalies.append(anomaly)

        event = MicromarketSaleDeducted(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            sale_source_id=sale_source_id,
            product_code=product_code,
            qty=clamped,
            occurred_at=occurred_at,
        )
        self._apply(event)
        self._pending.append(event)
        return tuple(anomalies)

    @beartype
    def apply_loading(
        self,
        *,
        lines: Mapping[str, Decimal],
        loading_run_id: str,
        occurred_at: datetime,
    ) -> MicromarketLoadingApplied | None:
        if loading_run_id in self._seen_loading_run_ids:
            return None
        event = MicromarketLoadingApplied(
            event_id=_new_event_id(),
            machine_code=self.machine_code,
            loading_run_id=loading_run_id,
            lines=tuple(sorted(lines.items())),
            occurred_at=occurred_at,
        )
        self._apply(event)
        self._pending.append(event)
        return event

    @beartype
    def _apply(self, event: MicromarketStockEvent) -> None:
        if isinstance(event, MicromarketInventoryAccepted):
            if event.partial:
                prior_codes = set(self._qty)
                explicit = {code for code, _quantity in event.quantities}
                for code, quantity in event.quantities:
                    self._qty[code] = quantity
                    self._last_factual[code] = quantity
                    self._basis[code] = "factual"
                for code in prior_codes - explicit:
                    self._basis[code] = "virtual"
            else:
                self._qty = {code: quantity for code, quantity in event.quantities}
                self._last_factual = {code: quantity for code, quantity in event.quantities}
                self._basis = {code: "factual" for code, _quantity in event.quantities}
            self._has_completed_inventory = True
            self._seen_inventory_ids.add(event.inventory_id)
            self._seen_sale_source_ids.clear()
            self._seen_anomaly_sale_source_ids.clear()
            return

        if isinstance(event, MicromarketSaleDeducted):
            self._seen_sale_source_ids.add(event.sale_source_id)
            current = self._qty.get(event.product_code, Decimal("0"))
            self._qty[event.product_code] = current - event.qty
            if event.product_code in self._basis or event.product_code in self._last_factual:
                self._basis[event.product_code] = "virtual"
            return

        if isinstance(event, MicromarketLoadingApplied):
            if event.loading_run_id in self._seen_loading_run_ids:
                return
            self._seen_loading_run_ids.add(event.loading_run_id)
            for product_code, increment in event.lines:
                current = self._qty.get(product_code, Decimal("0"))
                self._qty[product_code] = current + increment
            return

        if isinstance(event, MicromarketStockAnomalyRecorded):
            if event.sale_source_id:
                self._seen_anomaly_sale_source_ids.add(event.sale_source_id)
            return
