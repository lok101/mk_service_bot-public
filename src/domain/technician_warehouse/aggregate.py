from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import EventId, TechnicianId
from src.domain.technician_warehouse.errors import (
    FinalizedTransferChangedError,
    WarehouseAlreadyClosed,
)
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseExitClosed,
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferFinalized,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
    WarehouseEvent,
)
from src.domain.technician_warehouse.models import (
    SYNTHETIC_ZERO_BASELINE_ID,
    TechnicianWarehouseDelta,
    TransferDirection,
)


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseBookStock:
    """Open-book calculated stock after latest inventory (no live MoySklad)."""

    stock_by_sku: dict[str, Decimal]
    as_of: datetime


@beartype
@dataclass(slots=True)
class TechnicianWarehouse:
    technician_id: TechnicianId
    _transfers: dict[str, TechnicianWarehouseTransferObserved] = field(
        default_factory=dict,
        repr=False,
    )
    _voided_transfer_ids: set[str] = field(default_factory=set, repr=False)
    _loadings: dict[str, TechnicianWarehouseLoadingObserved] = field(
        default_factory=dict,
        repr=False,
    )
    _inventories: list[TechnicianWarehouseInventoryCounted] = field(
        default_factory=list,
        repr=False,
    )
    _inventory_by_form_token: dict[str, TechnicianWarehouseInventoryCounted] = field(
        default_factory=dict,
        repr=False,
    )
    _latest_delta: TechnicianWarehouseDelta | None = field(default=None, repr=False)
    _finalized_transfer_ids: set[str] = field(default_factory=set, repr=False)
    _is_closed: bool = field(default=False, repr=False)
    _exit_closed_at: datetime | None = field(default=None, repr=False)
    _pending_events: list[WarehouseEvent] = field(default_factory=list, repr=False)
    _version: int = field(default=0, repr=False)

    @property
    def version(self) -> int:
        return self._version

    @property
    def latest_inventory_id(self) -> str | None:
        if not self._inventories:
            return None
        return self._inventories[-1].inventory_id

    @beartype
    def latest_inventory_counted_at_at_or_before(self, anchor_at: datetime) -> datetime | None:
        eligible = [
            inventory for inventory in self._inventories if inventory.counted_at <= anchor_at
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda inventory: inventory.counted_at).counted_at

    @beartype
    def transfer_document_ids_in_moment_window(
        self,
        *,
        moment_from: datetime,
        moment_to: datetime,
    ) -> tuple[str, ...]:
        document_ids = [
            transfer.external_document_id
            for transfer in self._transfers.values()
            if transfer.external_document_id not in self._voided_transfer_ids
            and moment_from <= transfer.moment <= moment_to
        ]
        return tuple(sorted(document_ids))

    @beartype
    def is_transfer_finalized(self, external_document_id: str) -> bool:
        return external_document_id in self._finalized_transfer_ids

    @beartype
    def observed_transfer_document_ids(self) -> frozenset[str]:
        return frozenset(
            document_id
            for document_id in self._transfers
            if document_id not in self._voided_transfer_ids
        )

    @beartype
    def non_voided_transfers(self) -> tuple[TechnicianWarehouseTransferObserved, ...]:
        return tuple(
            transfer
            for doc_id, transfer in self._transfers.items()
            if doc_id not in self._voided_transfer_ids
        )

    @classmethod
    @beartype
    def empty(cls, technician_id: TechnicianId) -> TechnicianWarehouse:
        return cls(technician_id=technician_id)

    @classmethod
    @beartype
    def rehydrate(
        cls,
        technician_id: TechnicianId,
        events: Iterable[WarehouseEvent],
    ) -> TechnicianWarehouse:
        warehouse = cls.empty(technician_id)
        event_list = list(events)
        for event in event_list:
            warehouse._apply(event)
        warehouse._version = len(event_list)
        warehouse._pending_events.clear()
        return warehouse

    @beartype
    def observe_transfer(
        self,
        event: TechnicianWarehouseTransferObserved,
    ) -> TechnicianWarehouseTransferObserved | None:
        if self._is_closed:
            raise WarehouseAlreadyClosed(self.technician_id)
        if event.technician_id != self.technician_id:
            raise ValueError("transfer technician_id mismatch")

        if event.external_document_id in self._finalized_transfer_ids:
            existing = self._transfers.get(event.external_document_id)
            if existing is not None and existing.content_hash == event.content_hash:
                return None
            raise FinalizedTransferChangedError(event.external_document_id)

        existing = self._transfers.get(event.external_document_id)
        if (
            existing is not None
            and existing.content_hash == event.content_hash
            and _transfer_version_key(event) == _transfer_version_key(existing)
        ):
            return None

        if existing is not None and _transfer_version_key(event) < _transfer_version_key(existing):
            return None

        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def void_transfer(
        self,
        *,
        external_document_id: str,
        observed_at: datetime,
    ) -> TechnicianWarehouseTransferVoided | None:
        if self._is_closed:
            raise WarehouseAlreadyClosed(self.technician_id)
        if external_document_id in self._finalized_transfer_ids:
            raise FinalizedTransferChangedError(external_document_id)

        if external_document_id in self._voided_transfer_ids:
            return None

        existing = self._transfers.get(external_document_id)
        previous_content_hash = existing.content_hash if existing is not None else ""

        event = TechnicianWarehouseTransferVoided(
            event_id=EventId(str(uuid.uuid4())),
            technician_id=self.technician_id,
            occurred_at=datetime.now(tz=UTC),
            external_document_id=external_document_id,
            previous_content_hash=previous_content_hash,
            observed_at=observed_at,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def observe_loading(
        self,
        event: TechnicianWarehouseLoadingObserved,
    ) -> TechnicianWarehouseLoadingObserved | None:
        if self._is_closed:
            raise WarehouseAlreadyClosed(self.technician_id)
        if event.source_event_id in self._loadings:
            return None

        if event.technician_id != self.technician_id:
            raise ValueError("loading technician_id mismatch")

        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def calculated_stock_since_baseline(self) -> dict[str, Decimal]:
        stock: dict[str, Decimal] = {}
        for transfer in self._transfers.values():
            if transfer.external_document_id in self._voided_transfer_ids:
                continue
            if transfer.direction is TransferDirection.SUPPLY_IN:
                sign = Decimal("1")
            else:
                sign = Decimal("-1")
            for line in transfer.lines:
                stock[line.sku] = stock.get(line.sku, Decimal("0")) + sign * line.quantity_base

        for loading in self._loadings.values():
            for line in loading.lines:
                stock[line.sku] = stock.get(line.sku, Decimal("0")) - line.quantity_base

        return _normalize_decimal_map(stock)

    @beartype
    def book_stock_since_latest_inventory(self) -> TechnicianWarehouseBookStock | None:
        """Calculated book: last inventory actual ± imported transfers − loadings."""
        if not self._inventories:
            return None
        latest = self._inventories[-1]
        window_start = latest.counted_at
        stock: dict[str, Decimal] = {sku: qty for sku, qty in latest.lines}
        for transfer in self._transfers.values():
            if transfer.external_document_id in self._voided_transfer_ids:
                continue
            if transfer.moment <= window_start:
                continue
            sign = (
                Decimal("1") if transfer.direction is TransferDirection.SUPPLY_IN else Decimal("-1")
            )
            for line in transfer.lines:
                stock[line.sku] = stock.get(line.sku, Decimal("0")) + sign * line.quantity_base
        for loading in self._loadings.values():
            if loading.submitted_at <= window_start:
                continue
            for line in loading.lines:
                stock[line.sku] = stock.get(line.sku, Decimal("0")) - line.quantity_base
        return TechnicianWarehouseBookStock(
            stock_by_sku=_normalize_decimal_map(stock),
            as_of=window_start,
        )

    @beartype
    def count_inventory(
        self,
        *,
        inventory_id: str,
        form_token: str,
        counted_at: datetime,
        actual_by_sku: dict[str, Decimal],
        baseline: bool,
    ) -> TechnicianWarehouseInventoryCounted:
        if self._is_closed:
            raise WarehouseAlreadyClosed(self.technician_id)
        existing = self._inventory_by_form_token.get(form_token)
        if existing is not None:
            return existing

        lines = tuple(sorted(actual_by_sku.items()))
        event = TechnicianWarehouseInventoryCounted(
            event_id=EventId(str(uuid.uuid4())),
            technician_id=self.technician_id,
            occurred_at=datetime.now(tz=UTC),
            inventory_id=inventory_id,
            form_token=form_token,
            counted_at=counted_at,
            lines=lines,
            baseline=baseline,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def latest_warehouse_delta(self) -> TechnicianWarehouseDelta | None:
        return self._latest_delta

    @beartype
    def compute_warehouse_delta_between_latest_inventories(
        self,
    ) -> TechnicianWarehouseDelta | None:
        """Session delta for latest inventory vs prior inventory or synthetic zero.

        Previous is synthetic when the eligible current has no prior inventory in stream.
        Seed-only current (``baseline=True``) does not open a session.
        """
        if not self._inventories:
            return None
        current = self._inventories[-1]
        if current.baseline:
            return None
        if len(self._inventories) == 1:
            previous_inventory_id = SYNTHETIC_ZERO_BASELINE_ID
            previous_inventory_moment = datetime(1, 1, 1, tzinfo=UTC)
            previous_actual: dict[str, Decimal] = {}
        else:
            previous = self._inventories[-2]
            previous_inventory_id = previous.inventory_id
            previous_inventory_moment = previous.counted_at
            previous_actual = dict(previous.lines)
        return _compute_warehouse_delta(
            previous_inventory_id=previous_inventory_id,
            previous_inventory_moment=previous_inventory_moment,
            previous_actual=previous_actual,
            current_inventory_id=current.inventory_id,
            current_inventory_moment=current.counted_at,
            current_actual=dict(current.lines),
            transfers=self._transfers,
            voided_transfer_ids=self._voided_transfer_ids,
            loadings=self._loadings,
        )

    @beartype
    def compute_warehouse_delta_for_inventory_id(
        self,
        inventory_id: str,
    ) -> TechnicianWarehouseDelta | None:
        """Session delta for a named inventory vs its prior inventory or synthetic zero.

        Looks up ``inventory_id`` in stream order (not latest). Missing id or
        ``baseline=True`` current → ``None`` (same fail-closed signal as latest path).
        """
        current_index: int | None = None
        for index, inventory in enumerate(self._inventories):
            if inventory.inventory_id == inventory_id:
                current_index = index
                break
        if current_index is None:
            return None
        current = self._inventories[current_index]
        if current.baseline:
            return None
        if current_index == 0:
            previous_inventory_id = SYNTHETIC_ZERO_BASELINE_ID
            previous_inventory_moment = datetime(1, 1, 1, tzinfo=UTC)
            previous_actual: dict[str, Decimal] = {}
        else:
            previous = self._inventories[current_index - 1]
            previous_inventory_id = previous.inventory_id
            previous_inventory_moment = previous.counted_at
            previous_actual = dict(previous.lines)
        return _compute_warehouse_delta(
            previous_inventory_id=previous_inventory_id,
            previous_inventory_moment=previous_inventory_moment,
            previous_actual=previous_actual,
            current_inventory_id=current.inventory_id,
            current_inventory_moment=current.counted_at,
            current_actual=dict(current.lines),
            transfers=self._transfers,
            voided_transfer_ids=self._voided_transfer_ids,
            loadings=self._loadings,
        )

    @beartype
    def is_closed(self) -> bool:
        return self._is_closed

    @beartype
    def exit_closed_at(self) -> datetime | None:
        return self._exit_closed_at

    @beartype
    def close_exit(
        self,
        *,
        closed_at: datetime,
        return_external_document_id: str,
        return_content_hash: str,
    ) -> TechnicianWarehouseExitClosed:
        if self._is_closed:
            raise WarehouseAlreadyClosed(self.technician_id)
        event = TechnicianWarehouseExitClosed(
            event_id=EventId(str(uuid.uuid4())),
            technician_id=self.technician_id,
            occurred_at=datetime.now(tz=UTC),
            closed_at=closed_at,
            return_external_document_id=return_external_document_id,
            return_content_hash=return_content_hash,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def finalize_transfers(
        self,
        *,
        session_id: str,
        external_document_ids: tuple[str, ...],
        finalized_at: datetime,
    ) -> TechnicianWarehouseTransferFinalized:
        event = TechnicianWarehouseTransferFinalized(
            event_id=EventId(str(uuid.uuid4())),
            technician_id=self.technician_id,
            occurred_at=datetime.now(tz=UTC),
            session_id=session_id,
            external_document_ids=external_document_ids,
            finalized_at=finalized_at,
        )
        self._apply(event)
        self._pending_events.append(event)
        return event

    @beartype
    def collect_events(self) -> tuple[WarehouseEvent, ...]:
        return tuple(self._pending_events)

    @beartype
    def clear_pending_events(self) -> None:
        self._pending_events.clear()

    @beartype
    def _apply(self, event: WarehouseEvent) -> None:
        if isinstance(event, TechnicianWarehouseTransferObserved):
            self._voided_transfer_ids.discard(event.external_document_id)
            current = self._transfers.get(event.external_document_id)
            if (
                current is None
                or _transfer_version_key(event) > _transfer_version_key(current)
                or (
                    event.content_hash != current.content_hash
                    and _transfer_version_key(event) == _transfer_version_key(current)
                )
            ):
                self._transfers[event.external_document_id] = event
            return

        if isinstance(event, TechnicianWarehouseTransferVoided):
            self._voided_transfer_ids.add(event.external_document_id)
            return

        if isinstance(event, TechnicianWarehouseLoadingObserved):
            self._loadings[event.source_event_id] = event
            return

        if isinstance(event, TechnicianWarehouseInventoryCounted):
            self._inventory_by_form_token[event.form_token] = event
            self._inventories.append(event)
            self._inventories.sort(key=lambda inventory: inventory.counted_at)
            return

        if isinstance(event, TechnicianWarehouseTransferFinalized):
            self._finalized_transfer_ids.update(event.external_document_ids)
            return

        if isinstance(event, TechnicianWarehouseExitClosed):
            self._is_closed = True
            self._exit_closed_at = event.closed_at
            if self._inventories:
                previous = self._inventories[-1]
                previous_inventory_id = previous.inventory_id
                previous_inventory_moment = previous.counted_at
                previous_actual = dict(previous.lines)
            else:
                previous_inventory_id = SYNTHETIC_ZERO_BASELINE_ID
                previous_inventory_moment = datetime(1, 1, 1, tzinfo=UTC)
                previous_actual = {}
            self._latest_delta = _compute_warehouse_delta(
                previous_inventory_id=previous_inventory_id,
                previous_inventory_moment=previous_inventory_moment,
                previous_actual=previous_actual,
                current_inventory_id=event.event_id.value,
                current_inventory_moment=event.closed_at,
                current_actual={},
                transfers=self._transfers,
                voided_transfer_ids=self._voided_transfer_ids,
                loadings=self._loadings,
            )
            return


@beartype
def _compute_warehouse_delta(
    *,
    previous_inventory_id: str,
    previous_inventory_moment: datetime,
    previous_actual: dict[str, Decimal],
    current_inventory_id: str,
    current_inventory_moment: datetime,
    current_actual: dict[str, Decimal],
    transfers: dict[str, TechnicianWarehouseTransferObserved],
    voided_transfer_ids: set[str],
    loadings: dict[str, TechnicianWarehouseLoadingObserved],
) -> TechnicianWarehouseDelta:
    supply_in: dict[str, Decimal] = {}
    supply_returns: dict[str, Decimal] = {}
    loading_totals: dict[str, Decimal] = {}
    transfer_audit: list[tuple[str, str]] = []

    window_start = previous_inventory_moment
    window_end = current_inventory_moment

    for transfer in transfers.values():
        if transfer.external_document_id in voided_transfer_ids:
            continue
        if not (window_start < transfer.moment <= window_end):
            continue
        transfer_audit.append((transfer.external_document_id, transfer.content_hash))
        target = supply_in if transfer.direction is TransferDirection.SUPPLY_IN else supply_returns
        for line in transfer.lines:
            target[line.sku] = target.get(line.sku, Decimal("0")) + line.quantity_base

    for loading in loadings.values():
        if not (window_start < loading.submitted_at <= window_end):
            continue
        for line in loading.lines:
            loading_totals[line.sku] = (
                loading_totals.get(line.sku, Decimal("0")) + line.quantity_base
            )

    all_skus = (
        set(previous_actual)
        | set(current_actual)
        | set(supply_in)
        | set(supply_returns)
        | set(loading_totals)
    )
    calculated_by_sku: dict[str, Decimal] = {}
    delta_by_sku: dict[str, Decimal] = {}
    for sku in all_skus:
        calculated = (
            previous_actual.get(sku, Decimal("0"))
            + supply_in.get(sku, Decimal("0"))
            - supply_returns.get(sku, Decimal("0"))
            - loading_totals.get(sku, Decimal("0"))
        )
        calculated_by_sku[sku] = calculated
        delta_by_sku[sku] = current_actual.get(sku, Decimal("0")) - calculated

    sorted_audit = sorted(transfer_audit, key=lambda item: item[0])

    return TechnicianWarehouseDelta(
        current_inventory_id=current_inventory_id,
        current_inventory_moment=current_inventory_moment,
        previous_inventory_id=previous_inventory_id,
        previous_inventory_moment=previous_inventory_moment,
        actual_by_sku=_normalize_decimal_map(current_actual),
        calculated_by_sku=_normalize_decimal_map(calculated_by_sku),
        delta_by_sku=_normalize_decimal_map(delta_by_sku),
        transfer_document_ids=tuple(doc_id for doc_id, _ in sorted_audit),
        transfer_content_hashes=tuple(content_hash for _, content_hash in sorted_audit),
        previous_actual_by_sku=_normalize_decimal_map(previous_actual),
        supply_in_by_sku=_normalize_decimal_map(supply_in),
        returns_by_sku=_normalize_decimal_map(supply_returns),
        loadings_by_sku=_normalize_decimal_map(loading_totals),
    )


@beartype
def _transfer_version_key(
    event: TechnicianWarehouseTransferObserved,
) -> tuple[datetime, datetime]:
    return (event.updated_at, event.observed_at)


@beartype
def _normalize_decimal_map(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {sku: quantity for sku, quantity in values.items() if quantity != 0}
