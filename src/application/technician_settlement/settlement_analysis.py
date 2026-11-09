from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    PeriodPartyNamesLookup,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.sheets.ports import ProductSpecByCodeResolver
from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs
from src.application.technician_settlement.ports import TechnicianSettlementEventStore
from src.domain.ids import TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.events import (
    ReconciliationMode,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)

_AnalysisSessionEvent = (
    TechnicianReconciliationSessionCommitted | TechnicianReconciliationSessionCompleted
)

__all__ = [
    "AggregateSettlementClusters",
    "AggregateSkuRow",
    "BuildPeriodAnalysisView",
    "BuildSessionAnalysisView",
    "BuildSettlementAnalysisTree",
    "PeriodAnalysisLineRow",
    "PeriodAnalysisView",
    "SessionAnalysisView",
    "SettlementAnalysisCluster",
    "SettlementAnalysisPeriodRow",
    "SettlementAnalysisTree",
    "SettlementClustersAggregate",
    "UnknownAnalysisSession",
    "AnalysisSkuQtyRow",
    "format_analysis_rubles",
]


@beartype
class UnknownAnalysisSession(Exception):
    """Selected session id is unknown or not a completed session for the technician."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Unknown analysis session: {session_id}")


@beartype
@dataclass(frozen=True, slots=True)
class SettlementAnalysisPeriodRow:
    period_id: str
    location_name: str
    opened_at: datetime | None
    closed_at: datetime | None
    missing_snapshot: bool


@beartype
@dataclass(frozen=True, slots=True)
class SettlementAnalysisCluster:
    session_id: str
    mode: ReconciliationMode
    warehouse_inventory_moment: datetime | None
    finalized_at: datetime
    periods: tuple[SettlementAnalysisPeriodRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class SettlementAnalysisTree:
    technician_id: str
    clusters: tuple[SettlementAnalysisCluster, ...]


@beartype
@dataclass(frozen=True, slots=True)
class AggregateSkuRow:
    product_code: str
    product_name: str
    residual: Decimal
    consumption: Decimal
    loss_pct: Decimal | None
    loss_pct_points: int | None
    shortage_money: Decimal
    excess_qty: Decimal
    excess_money: Decimal
    recoverable: bool
    price_missing: bool


@beartype
@dataclass(frozen=True, slots=True)
class SettlementClustersAggregate:
    rows: tuple[AggregateSkuRow, ...]
    shortage_money_total: Decimal
    excess_money_total: Decimal
    recoverable_shortage_money: Decimal
    loss_shortage_money: Decimal
    recoverable_excess_money: Decimal
    loss_excess_money: Decimal

    @property
    def loss_rows(self) -> tuple[AggregateSkuRow, ...]:
        return tuple(row for row in self.rows if not row.recoverable)

    @property
    def recoverable_rows(self) -> tuple[AggregateSkuRow, ...]:
        return tuple(row for row in self.rows if row.recoverable)


@beartype
@dataclass(frozen=True, slots=True)
class AnalysisSkuQtyRow:
    product_code: str
    product_name: str
    qty: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class SessionAnalysisView:
    session_id: str
    technician_id: str
    mode: ReconciliationMode
    warehouse_inventory_moment: datetime | None
    finalized_at: datetime
    warehouse_delta_by_sku: dict[str, Decimal]
    residual_by_sku: dict[str, Decimal]
    warehouse_delta_rows: tuple[AnalysisSkuQtyRow, ...]
    residual_rows: tuple[AnalysisSkuQtyRow, ...]
    period_ids: tuple[str, ...]


@beartype
@dataclass(frozen=True, slots=True)
class PeriodAnalysisLineRow:
    product_code: str
    product_name: str
    sales_total: Decimal
    delta: Decimal
    loads_total: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class PeriodAnalysisView:
    period_id: str
    location_name: str
    opened_at: datetime
    closed_at: datetime
    lines: tuple[PeriodAnalysisLineRow, ...]


def _loss_pct_points(loss_pct: Decimal | None) -> int | None:
    if loss_pct is None:
        return None
    return int((loss_pct * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@beartype
def format_analysis_rubles(amount: Decimal) -> int:
    """Round money to whole rubles for settlement-analysis UI."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _product_display_name(
    catalog: ProductSpecByCodeResolver | None,
    product_code: str,
) -> str:
    if catalog is None:
        return product_code
    spec = catalog.try_resolve_by_code(product_code)
    if spec is None:
        return product_code
    name = spec.name.strip()
    return name or product_code


def _period_location_name(
    snapshot: ResponsibilityPeriodReconciliation,
    lookup: PeriodPartyNamesLookup | None,
) -> str:
    frozen = snapshot.location_name.strip()
    if frozen:
        return frozen
    if lookup is None:
        return ""
    live = lookup.location_name(snapshot.machine_id)
    if live is None:
        return ""
    return live.strip()


def _sku_qty_rows(
    quantities: dict[str, Decimal],
    catalog: ProductSpecByCodeResolver | None,
) -> tuple[AnalysisSkuQtyRow, ...]:
    return tuple(
        AnalysisSkuQtyRow(
            product_code=code,
            product_name=_product_display_name(catalog, code),
            qty=qty,
        )
        for code, qty in sorted(quantities.items())
    )


def _cluster_sort_key(event: _AnalysisSessionEvent) -> datetime:
    if event.warehouse_inventory_moment is not None:
        return event.warehouse_inventory_moment
    return event.finalized_at


_ANALYSIS_SESSION_EVENT_TYPES = (
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)


def _sorted_period_rows(
    periods: list[SettlementAnalysisPeriodRow],
) -> tuple[SettlementAnalysisPeriodRow, ...]:
    dated = [row for row in periods if row.opened_at is not None]
    missing = [row for row in periods if row.opened_at is None]
    dated.sort(
        key=lambda row: (
            (row.location_name or row.period_id).casefold(),
            row.opened_at or datetime.min.replace(tzinfo=UTC),
            row.period_id,
        ),
    )
    missing.sort(key=lambda row: row.period_id)
    return tuple([*dated, *missing])


@beartype
@dataclass(frozen=True, slots=True)
class BuildSettlementAnalysisTree:
    event_store: TechnicianSettlementEventStore
    period_repository: ResponsibilityPeriodReconciliationRepository
    party_names_lookup: PeriodPartyNamesLookup | None = None

    @beartype
    def execute(self, technician_id: TechnicianId) -> SettlementAnalysisTree:
        events = self.event_store.get_events_for_technician(technician_id)
        sessions = [event for event in events if isinstance(event, _ANALYSIS_SESSION_EVENT_TYPES)]
        sessions.sort(key=_cluster_sort_key, reverse=True)
        clusters: list[SettlementAnalysisCluster] = []
        for event in sessions:
            periods: list[SettlementAnalysisPeriodRow] = []
            for period_id in event.period_ids:
                snapshot = self.period_repository.get_by_period_id(period_id)
                if snapshot is None:
                    periods.append(
                        SettlementAnalysisPeriodRow(
                            period_id=period_id,
                            location_name="",
                            opened_at=None,
                            closed_at=None,
                            missing_snapshot=True,
                        )
                    )
                    continue
                periods.append(
                    SettlementAnalysisPeriodRow(
                        period_id=period_id,
                        location_name=_period_location_name(
                            snapshot,
                            self.party_names_lookup,
                        ),
                        opened_at=snapshot.opened_at,
                        closed_at=snapshot.closed_at,
                        missing_snapshot=False,
                    )
                )
            clusters.append(
                SettlementAnalysisCluster(
                    session_id=event.session_id.value,
                    mode=event.mode,
                    warehouse_inventory_moment=event.warehouse_inventory_moment,
                    finalized_at=event.finalized_at,
                    periods=_sorted_period_rows(periods),
                )
            )
        return SettlementAnalysisTree(
            technician_id=technician_id.value,
            clusters=tuple(clusters),
        )


@beartype
@dataclass(frozen=True, slots=True)
class AggregateSettlementClusters:
    event_store: TechnicianSettlementEventStore
    period_repository: ResponsibilityPeriodReconciliationRepository
    catalog: ProductSpecByCodeResolver | None = None

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        session_ids: frozenset[str],
        prefs: SettlementAnalysisPrefs,
    ) -> SettlementClustersAggregate:
        events = self.event_store.get_events_for_technician(technician_id)
        sessions_by_id: dict[str, _AnalysisSessionEvent] = {
            event.session_id.value: event
            for event in events
            if isinstance(event, _ANALYSIS_SESSION_EVENT_TYPES)
        }
        selected: list[_AnalysisSessionEvent] = []
        for session_id in session_ids:
            event = sessions_by_id.get(session_id)
            if event is None:
                raise UnknownAnalysisSession(session_id)
            selected.append(event)

        residual: dict[str, Decimal] = {}
        period_ids: list[str] = []
        for event in selected:
            for sku, qty in event.residual_by_sku.items():
                residual[sku] = residual.get(sku, Decimal("0")) + qty
            period_ids.extend(event.period_ids)

        consumption: dict[str, Decimal] = {}
        for period_id in period_ids:
            snapshot = self.period_repository.get_by_period_id(period_id)
            if snapshot is None:
                continue
            for line in snapshot.lines:
                consumption[line.product_code] = (
                    consumption.get(line.product_code, Decimal("0")) + line.sales_total
                )

        skus = sorted(set(residual) | set(consumption))
        n_ratio = prefs.allowed_loss_pct / Decimal("100")
        rows: list[AggregateSkuRow] = []
        shortage_money_total = Decimal("0")
        excess_money_total = Decimal("0")
        recoverable_shortage_money = Decimal("0")
        loss_shortage_money = Decimal("0")
        recoverable_excess_money = Decimal("0")
        loss_excess_money = Decimal("0")

        for sku in skus:
            res = residual.get(sku, Decimal("0"))
            cons = consumption.get(sku, Decimal("0"))
            if cons > 0:
                loss_pct: Decimal | None = abs(res) / cons
            else:
                loss_pct = None

            price = prefs.unit_prices.get(sku)
            price_missing = price is None
            unit_price = price if price is not None else Decimal("0")

            if res < 0 and not price_missing:
                shortage_money = abs(res) * unit_price
            else:
                shortage_money = Decimal("0")

            excess_qty = max(Decimal("0"), abs(res) - n_ratio * cons) if res < 0 else Decimal("0")
            excess_money = (
                excess_qty * unit_price if not price_missing and excess_qty > 0 else Decimal("0")
            )

            recoverable = sku in prefs.recoverable_product_codes
            rows.append(
                AggregateSkuRow(
                    product_code=sku,
                    product_name=_product_display_name(self.catalog, sku),
                    residual=res,
                    consumption=cons,
                    loss_pct=loss_pct,
                    loss_pct_points=_loss_pct_points(loss_pct),
                    shortage_money=shortage_money,
                    excess_qty=excess_qty,
                    excess_money=excess_money,
                    recoverable=recoverable,
                    price_missing=price_missing,
                )
            )
            shortage_money_total += shortage_money
            excess_money_total += excess_money
            if recoverable:
                recoverable_shortage_money += shortage_money
                recoverable_excess_money += excess_money
            else:
                loss_shortage_money += shortage_money
                loss_excess_money += excess_money

        return SettlementClustersAggregate(
            rows=tuple(rows),
            shortage_money_total=shortage_money_total,
            excess_money_total=excess_money_total,
            recoverable_shortage_money=recoverable_shortage_money,
            loss_shortage_money=loss_shortage_money,
            recoverable_excess_money=recoverable_excess_money,
            loss_excess_money=loss_excess_money,
        )


@beartype
@dataclass(frozen=True, slots=True)
class BuildSessionAnalysisView:
    event_store: TechnicianSettlementEventStore
    catalog: ProductSpecByCodeResolver | None = None

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        session_id: str,
    ) -> SessionAnalysisView | None:
        events = self.event_store.get_events_for_technician(technician_id)
        for event in events:
            if not isinstance(event, _ANALYSIS_SESSION_EVENT_TYPES):
                continue
            if event.session_id.value != session_id:
                continue
            warehouse_delta = dict(event.warehouse_delta_by_sku)
            residual = dict(event.residual_by_sku)
            return SessionAnalysisView(
                session_id=event.session_id.value,
                technician_id=event.technician_id.value,
                mode=event.mode,
                warehouse_inventory_moment=event.warehouse_inventory_moment,
                finalized_at=event.finalized_at,
                warehouse_delta_by_sku=warehouse_delta,
                residual_by_sku=residual,
                warehouse_delta_rows=_sku_qty_rows(warehouse_delta, self.catalog),
                residual_rows=_sku_qty_rows(residual, self.catalog),
                period_ids=event.period_ids,
            )
        return None


@beartype
@dataclass(frozen=True, slots=True)
class BuildPeriodAnalysisView:
    period_repository: ResponsibilityPeriodReconciliationRepository
    party_names_lookup: PeriodPartyNamesLookup | None = None
    catalog: ProductSpecByCodeResolver | None = None

    @beartype
    def execute(self, period_id: str) -> PeriodAnalysisView | None:
        snapshot = self.period_repository.get_by_period_id(period_id)
        if snapshot is None:
            return None
        lines = tuple(
            PeriodAnalysisLineRow(
                product_code=line.product_code,
                product_name=_product_display_name(self.catalog, line.product_code),
                sales_total=line.sales_total,
                delta=line.delta,
                loads_total=line.loads_total,
            )
            for line in snapshot.lines
        )
        return PeriodAnalysisView(
            period_id=snapshot.period_id,
            location_name=_period_location_name(snapshot, self.party_names_lookup),
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
            lines=lines,
        )
