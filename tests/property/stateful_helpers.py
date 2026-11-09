from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import ReconciliationSessionId
from src.domain.technician_settlement import TechnicianSettlement
from src.domain.technician_warehouse import (
    TechnicianWarehouse,
    TechnicianWarehouseDelta,
    TransferDirection,
)

ORDERED_MOMENTS: tuple[datetime, ...] = (
    datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
    datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
)
FIXED_ANCHOR = ORDERED_MOMENTS[1]
_SYNTHETIC_MOMENT = datetime(1, 1, 1, tzinfo=UTC)


def normalize(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return dict(values)


def _normalize_nonzero(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {sku: quantity for sku, quantity in values.items() if quantity != 0}


def _delta_view(delta: TechnicianWarehouseDelta | None) -> dict[str, Decimal]:
    return {} if delta is None else dict(delta.delta_by_sku)


def warehouse_view(
    warehouse: TechnicianWarehouse,
    known_document_ids: frozenset[str],
) -> tuple[object, ...]:
    return (
        warehouse.calculated_stock_since_baseline(),
        warehouse.latest_inventory_id,
        warehouse.latest_warehouse_delta(),
        _delta_view(warehouse.compute_warehouse_delta_between_latest_inventories()),
        warehouse.observed_transfer_document_ids(),
        {doc_id: warehouse.is_transfer_finalized(doc_id) for doc_id in known_document_ids},
        warehouse.is_closed(),
    )


def settlement_view(
    aggregate: TechnicianSettlement,
    session_ids: frozenset[str],
) -> tuple[object, ...]:
    return (
        aggregate.net_balance_by_sku(),
        aggregate.last_session_finalized_at(),
        {
            session_id: aggregate.completion_result_for(ReconciliationSessionId(session_id))
            for session_id in session_ids
        },
    )


@dataclass(frozen=True, slots=True)
class _OracleTransfer:
    document_id: str
    moment: datetime
    updated_at: datetime
    observed_at: datetime
    content_hash: str
    direction: TransferDirection
    lines: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class _OracleLoading:
    source_event_id: str
    submitted_at: datetime
    lines: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class _OracleInventory:
    inventory_id: str
    form_token: str
    counted_at: datetime
    actual: dict[str, Decimal]
    baseline: bool


@dataclass(slots=True)
class WarehouseOracle:
    """Test-only mutable snapshot; does not call production delta helpers."""

    _transfers: dict[str, _OracleTransfer] = field(default_factory=dict)
    _voided: set[str] = field(default_factory=set)
    _finalized: set[str] = field(default_factory=set)
    _loadings: dict[str, _OracleLoading] = field(default_factory=dict)
    _inventories: list[_OracleInventory] = field(default_factory=list)
    _form_tokens: set[str] = field(default_factory=set)

    def observe_supply(
        self,
        document_id: str,
        lines: dict[str, Decimal],
        moment: datetime,
        content_hash: str,
    ) -> None:
        if document_id in self._finalized:
            existing = self._transfers.get(document_id)
            if existing is not None and existing.content_hash == content_hash:
                return
            return
        version = (moment, moment)
        existing = self._transfers.get(document_id)
        if existing is not None:
            existing_version = (existing.updated_at, existing.observed_at)
            if existing.content_hash == content_hash and existing_version == version:
                return
            if version < existing_version:
                return
        self._voided.discard(document_id)
        self._transfers[document_id] = _OracleTransfer(
            document_id=document_id,
            moment=moment,
            updated_at=moment,
            observed_at=moment,
            content_hash=content_hash,
            direction=TransferDirection.SUPPLY_IN,
            lines=dict(lines),
        )

    def void(self, document_id: str) -> None:
        if document_id in self._finalized:
            return
        self._voided.add(document_id)

    def finalize(self, document_ids: tuple[str, ...]) -> None:
        self._finalized.update(document_ids)

    def observe_loading(
        self,
        source_event_id: str,
        lines: dict[str, Decimal],
        submitted_at: datetime,
    ) -> None:
        if source_event_id in self._loadings:
            return
        self._loadings[source_event_id] = _OracleLoading(
            source_event_id=source_event_id,
            submitted_at=submitted_at,
            lines=dict(lines),
        )

    def count_inventory(
        self,
        inventory_id: str,
        form_token: str,
        actual: dict[str, Decimal],
        counted_at: datetime,
        *,
        baseline: bool = False,
    ) -> None:
        if form_token in self._form_tokens:
            return
        self._form_tokens.add(form_token)
        self._inventories.append(
            _OracleInventory(
                inventory_id=inventory_id,
                form_token=form_token,
                counted_at=counted_at,
                actual=dict(actual),
                baseline=baseline,
            )
        )
        self._inventories.sort(key=lambda inventory: inventory.counted_at)

    def stock(self) -> dict[str, Decimal]:
        stock: dict[str, Decimal] = {}
        for transfer in self._transfers.values():
            if transfer.document_id in self._voided:
                continue
            if transfer.direction is TransferDirection.SUPPLY_IN:
                sign = Decimal("1")
            else:
                sign = Decimal("-1")
            for sku, quantity in transfer.lines.items():
                stock[sku] = stock.get(sku, Decimal("0")) + sign * quantity
        for loading in self._loadings.values():
            for sku, quantity in loading.lines.items():
                stock[sku] = stock.get(sku, Decimal("0")) - quantity
        return _normalize_nonzero(stock)

    def latest_delta_view(self) -> dict[str, Decimal]:
        if not self._inventories:
            return {}
        current = self._inventories[-1]
        if current.baseline:
            return {}
        if len(self._inventories) == 1:
            previous_actual: dict[str, Decimal] = {}
            window_start = _SYNTHETIC_MOMENT
        else:
            previous = self._inventories[-2]
            previous_actual = dict(previous.actual)
            window_start = previous.counted_at
        return _oracle_delta_by_sku(
            previous_actual=previous_actual,
            current_actual=dict(current.actual),
            transfers=self._transfers,
            voided=self._voided,
            loadings=self._loadings,
            window_start=window_start,
            window_end=current.counted_at,
        )


def _oracle_delta_by_sku(
    *,
    previous_actual: dict[str, Decimal],
    current_actual: dict[str, Decimal],
    transfers: dict[str, _OracleTransfer],
    voided: set[str],
    loadings: dict[str, _OracleLoading],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Decimal]:
    supply_in: dict[str, Decimal] = {}
    supply_returns: dict[str, Decimal] = {}
    loading_totals: dict[str, Decimal] = {}
    for transfer in transfers.values():
        if transfer.document_id in voided:
            continue
        if not (window_start < transfer.moment <= window_end):
            continue
        target = supply_in if transfer.direction is TransferDirection.SUPPLY_IN else supply_returns
        for sku, quantity in transfer.lines.items():
            target[sku] = target.get(sku, Decimal("0")) + quantity
    for loading in loadings.values():
        if not (window_start < loading.submitted_at <= window_end):
            continue
        for sku, quantity in loading.lines.items():
            loading_totals[sku] = loading_totals.get(sku, Decimal("0")) + quantity
    all_skus = (
        set(previous_actual)
        | set(current_actual)
        | set(supply_in)
        | set(supply_returns)
        | set(loading_totals)
    )
    delta_by_sku: dict[str, Decimal] = {}
    for sku in all_skus:
        calculated = (
            previous_actual.get(sku, Decimal("0"))
            + supply_in.get(sku, Decimal("0"))
            - supply_returns.get(sku, Decimal("0"))
            - loading_totals.get(sku, Decimal("0"))
        )
        delta = current_actual.get(sku, Decimal("0")) - calculated
        if delta != 0:
            delta_by_sku[sku] = delta
    return delta_by_sku
