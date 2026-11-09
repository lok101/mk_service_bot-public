from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.kitvending import (
    KitSaleResolveSkip,
    KitSaleResolveSuccess,
    RawKitSaleIdentity,
)
from src.application.inventory_reconciliation.ports import (
    KitPortionSalesGateway,
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
    VendingMachineCodeResolver,
)
from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.domain.ids import MachineId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class VerifyPortionSalesHoldingError(Exception):
    """Holding skip(s) recorded; fail closed so outbox retries the portion step."""


@runtime_checkable
class PendingSalesRefresh(Protocol):
    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> object: ...


@beartype
@dataclass(frozen=True, slots=True)
class VerifyPortionSalesResult:
    inserted: int
    skipped_holding: int
    skipped_non_holding: int
    resolved: int


@beartype
@dataclass(frozen=True, slots=True)
class VerifyPortionSales:
    sales_store: MachineSalesStore
    kit_gateway: KitPortionSalesGateway
    skip_store: MachineSaleSkipStore
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    code_resolver: VendingMachineCodeResolver
    refresh: PendingSalesRefresh
    now: Callable[[], datetime] = _utc_now

    @beartype
    def execute(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> VerifyPortionSalesResult:
        windows = self._windows(technician_id=technician_id, cutoff=cutoff)
        if not windows:
            self.refresh.execute()
            return VerifyPortionSalesResult(
                inserted=0,
                skipped_holding=0,
                skipped_non_holding=0,
                resolved=0,
            )

        from_date = min(period.opened_at for period in windows)
        scope_machines = {period.machine_id for period in windows}
        raw_sales = self.kit_gateway.fetch_raw_window(from_date=from_date, to_date=cutoff)
        kit_ids = self._kit_source_ids_in_scope(raw_sales, windows=windows)
        mongo_ids = self._mongo_source_ids(windows)
        missing = sorted(kit_ids - mongo_ids)

        inserted = 0
        skipped_holding = 0
        skipped_non_holding = 0
        ingested_at = self.now()
        raw_by_source_id = {item.source_id: item for item in raw_sales}

        for source_id in missing:
            outcome = self.kit_gateway.resolve(source_id)
            if isinstance(outcome, KitSaleResolveSkip):
                identity = raw_by_source_id[source_id]
                seen_at = self.now()
                self.skip_store.upsert(
                    MachineSaleSkip(
                        source_id=source_id,
                        reason_class=outcome.reason_class,
                        kit_vending_machine_id=identity.kit_vending_machine_id,
                        vending_machine_name=identity.vending_machine_name,
                        occurred_at=identity.occurred_at,
                        line_number=identity.line_number,
                        matrix_id=identity.matrix_id,
                        goods_name=identity.goods_name,
                        external_id=None,
                        first_seen_at=seen_at,
                        last_seen_at=seen_at,
                    ),
                )
                if outcome.holding:
                    skipped_holding += 1
                else:
                    skipped_non_holding += 1
                continue

            assert isinstance(outcome, KitSaleResolveSuccess)
            row = outcome.row
            machine_id = self.code_resolver.resolve(row.vending_machine_code)
            if machine_id is None or machine_id not in scope_machines:
                continue
            sale = MachineSale(
                source_id=row.source_id,
                machine_id=machine_id,
                product_code=row.product_code,
                quantity=row.quantity,
                occurred_at=row.occurred_at,
                ingested_at=ingested_at,
                sale_kind=row.sale_kind,
                kit_matrix_id=row.kit_matrix_id,
                kit_vending_machine_id=row.kit_vending_machine_id,
                kit_line_number=row.kit_line_number,
                machine_code=row.vending_machine_code,
                price=row.price,
                domain_product_id=row.domain_product_id,
            )
            if self.sales_store.insert_if_absent(sale):
                inserted += 1
            self.skip_store.delete_by_source_id(sale.source_id)

        if skipped_holding > 0:
            raise VerifyPortionSalesHoldingError(
                f"holding skips in portion sales verify: {skipped_holding}",
            )

        self.refresh.execute()
        return VerifyPortionSalesResult(
            inserted=inserted,
            skipped_holding=skipped_holding,
            skipped_non_holding=skipped_non_holding,
            resolved=len(missing),
        )

    @beartype
    def _windows(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> list[ResponsibilityPeriodReconciliation]:
        posted = self.reconciliation_repo.list_posted_unreconciled(technician_id=technician_id)
        pending = [
            snapshot
            for snapshot in self.reconciliation_repo.list_by_status(status="pending_sales")
            if snapshot.responsible_technician_id == technician_id
        ]
        return [snapshot for snapshot in (*posted, *pending) if snapshot.closed_at <= cutoff]

    @beartype
    def _mongo_source_ids(
        self,
        windows: list[ResponsibilityPeriodReconciliation],
    ) -> set[str]:
        ids: set[str] = set()
        for period in windows:
            ids.update(
                self.sales_store.list_source_ids(
                    machine_id=period.machine_id,
                    opened_at=period.opened_at,
                    closed_at=period.closed_at,
                ),
            )
        return ids

    @beartype
    def _kit_source_ids_in_scope(
        self,
        raw_sales: list[RawKitSaleIdentity],
        *,
        windows: list[ResponsibilityPeriodReconciliation],
    ) -> set[str]:
        period_windows = [
            (period.machine_id, period.opened_at, period.closed_at) for period in windows
        ]
        kit_ids: set[str] = set()
        for identity in raw_sales:
            if identity.vending_machine_code is None:
                continue
            machine_id = self.code_resolver.resolve(identity.vending_machine_code)
            if machine_id is None:
                continue
            if not any(
                mid == machine_id and opened_at < identity.occurred_at <= closed_at
                for mid, opened_at, closed_at in period_windows
            ):
                continue
            kit_ids.add(identity.source_id)
        return kit_ids


__all__ = [
    "PendingSalesRefresh",
    "VerifyPortionSales",
    "VerifyPortionSalesHoldingError",
    "VerifyPortionSalesResult",
]
