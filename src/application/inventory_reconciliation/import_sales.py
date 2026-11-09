from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancyStore,
    rebuild_company_occupancy,
)
from src.application.inventory_reconciliation.kitvending import (
    HoldingSkipSample,
    ReasonClass,
)
from src.application.inventory_reconciliation.ports import (
    KitVendingClient,
    MachineSalesStore,
    VendingMachineCodeResolver,
)
from src.application.inventory_reconciliation.resolvers import IdentityVendingMachineCodeResolver
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.application.snack_loading import (
    ApplySnackSaleToStock,
    NoOpSnackSaleUnresolvedAlertNotifier,
    SnackSaleUnresolvedAlertNotifier,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_LOGGER = logging.getLogger(__name__)

_UNRESOLVED_STATUSES = frozenset(
    {
        "unresolved_matrix",
        "unresolved_machine",
        "unresolved_line",
        "product_mismatch",
    },
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(frozen=True, slots=True)
class ImportKitVendingSalesResult:
    inserted: int
    skipped_unmapped: int
    affected_machine_ids: tuple[MachineId, ...]
    skipped_unresolved_product: int = 0
    skipped_no_machine_code: int = 0
    batch_max_occurred_at: datetime | None = None
    success_occurred_ats: tuple[datetime, ...] = ()
    inserted_occurred_ats: tuple[datetime, ...] = ()
    hold_at: datetime | None = None
    holding_skip_count: int = 0
    holding_samples: tuple[HoldingSkipSample, ...] = ()
    fingerprint_pairs: tuple[tuple[str, ReasonClass], ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class ImportKitVendingSales:
    sales_store: MachineSalesStore
    kitvending_client: KitVendingClient
    code_resolver: VendingMachineCodeResolver = IdentityVendingMachineCodeResolver()
    now: Callable[[], datetime] = _utc_now
    apply_snack_sale: ApplySnackSaleToStock | None = None
    unresolved_alert_min: int = 10
    unresolved_alert_notifier: SnackSaleUnresolvedAlertNotifier = (
        NoOpSnackSaleUnresolvedAlertNotifier()
    )
    skip_store: MachineSaleSkipStore | None = None
    occupancy_store: MachineCompanyOccupancyStore | None = None
    after_occupancy_rebuild: Callable[[], None] | None = None

    @beartype
    def execute(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ImportKitVendingSalesResult:
        ingested_at = self.now()
        inserted = 0
        skipped_unmapped = 0
        unresolved_or_mismatch = 0
        affected_machine_ids: set[MachineId] = set()
        rebuild_ids: set[MachineId] = set()
        success_occurred_ats: list[datetime] = []
        inserted_occurred_ats: list[datetime] = []

        for row in self.kitvending_client.fetch_all(since=since, until=until):
            success_occurred_ats.append(row.occurred_at)
            machine_id = self.code_resolver.resolve(row.vending_machine_code)
            if machine_id is None:
                skipped_unmapped += 1
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
                company_id=row.company_id,
                domain_product_id=row.domain_product_id,
            )
            inserted_now = self.sales_store.insert_if_absent(sale)
            if inserted_now:
                rebuild_ids.add(machine_id)
                inserted += 1
                inserted_occurred_ats.append(sale.occurred_at)
                if self.skip_store is not None:
                    self.skip_store.delete_by_source_id(sale.source_id)
            elif sale.company_id is not None:
                patched = self.sales_store.patch_company_id_if_missing(
                    sale.source_id,
                    sale.company_id,
                )
                if patched:
                    rebuild_ids.add(machine_id)
            if inserted_now and self.apply_snack_sale is not None:
                enriched = self.apply_snack_sale.execute(sale)
                if enriched.resolve_status is not None:
                    self.sales_store.set_resolve_status(
                        sale.source_id,
                        enriched.resolve_status,
                    )
                if enriched.resolve_status in _UNRESOLVED_STATUSES:
                    unresolved_or_mismatch += 1
            affected_machine_ids.add(machine_id)

        if unresolved_or_mismatch >= self.unresolved_alert_min:
            self.unresolved_alert_notifier.notify_unresolved_sales(
                count=unresolved_or_mismatch,
            )

        if self.occupancy_store is not None:
            for machine_id in sorted(rebuild_ids, key=lambda item: item.value):
                sales = self.sales_store.list_with_company_id(machine_id)
                intervals = rebuild_company_occupancy(machine_id, sales)
                self.occupancy_store.replace_for_machine(machine_id, intervals)
                _LOGGER.info(
                    "machine_company_occupancy rebuilt machine_id=%s interval_count=%s",
                    machine_id.value,
                    len(intervals),
                )
            if rebuild_ids and self.after_occupancy_rebuild is not None:
                try:
                    self.after_occupancy_rebuild()
                except Exception:
                    _LOGGER.exception("master_data_export_after_occupancy_failed")

        fetch_stats = self.kitvending_client.last_fetch_stats
        batch_max_occurred_at = max(success_occurred_ats, default=None)

        return ImportKitVendingSalesResult(
            inserted=inserted,
            skipped_unmapped=skipped_unmapped,
            affected_machine_ids=tuple(
                sorted(affected_machine_ids, key=lambda machine_id: machine_id.value),
            ),
            skipped_unresolved_product=fetch_stats.skipped_unresolved_product,
            skipped_no_machine_code=fetch_stats.skipped_no_machine_code,
            batch_max_occurred_at=batch_max_occurred_at,
            success_occurred_ats=tuple(success_occurred_ats),
            inserted_occurred_ats=tuple(inserted_occurred_ats),
            hold_at=fetch_stats.hold_at,
            holding_skip_count=fetch_stats.holding_skip_count,
            holding_samples=fetch_stats.holding_samples,
            fingerprint_pairs=fetch_stats.fingerprint_pairs,
        )
