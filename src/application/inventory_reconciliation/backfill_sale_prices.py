from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    KitSalesWindowPriceFetcher,
    MachineSalesStore,
)

PRICE_BACKFILL_CUTOVER: Final[datetime] = datetime(2026, 7, 29, 8, 19, 54, tzinfo=UTC)


@beartype
@dataclass(frozen=True, slots=True)
class BackfillSalePricesFromKitResult:
    window_from: datetime | None
    window_to: datetime
    updated: int = 0
    already_priced_skipped: int = 0
    missing_in_kit: int = 0
    missing_sum: int = 0
    invalid_sum: int = 0


@beartype
@dataclass(frozen=True, slots=True)
class BackfillSalePricesFromKit:
    sales_store: MachineSalesStore
    price_fetcher: KitSalesWindowPriceFetcher
    cutover: datetime = PRICE_BACKFILL_CUTOVER

    @beartype
    def execute(self) -> BackfillSalePricesFromKitResult:
        window_from = self.sales_store.min_occurred_at_missing_price()
        if window_from is None:
            return BackfillSalePricesFromKitResult(window_from=None, window_to=self.cutover)

        rows = self.price_fetcher.fetch_price_rows(from_date=window_from, to_date=self.cutover)
        price_by_source_id: dict[str, Decimal] = {}
        missing_sum = 0
        invalid_sum = 0
        missing_sum_ids: set[str] = set()
        for row in rows:
            if row.source_id is None:
                continue
            if row.sum_value is None:
                missing_sum += 1
                missing_sum_ids.add(row.source_id)
                continue
            try:
                price = Decimal(str(row.sum_value))
            except InvalidOperation, ValueError:
                invalid_sum += 1
                continue
            if not price.is_finite():
                invalid_sum += 1
                continue
            price_by_source_id[row.source_id] = price

        docs = self.sales_store.find_missing_price_before(self.cutover)
        updated = 0
        already_priced_skipped = 0
        missing_in_kit = 0
        for sale in docs:
            matched_price = price_by_source_id.get(sale.source_id)
            if matched_price is None:
                if sale.source_id in missing_sum_ids:
                    continue
                missing_in_kit += 1
                continue
            if self.sales_store.set_price_if_absent(sale.source_id, matched_price):
                updated += 1
            else:
                already_priced_skipped += 1

        return BackfillSalePricesFromKitResult(
            window_from=window_from,
            window_to=self.cutover,
            updated=updated,
            already_priced_skipped=already_priced_skipped,
            missing_in_kit=missing_in_kit,
            missing_sum=missing_sum,
            invalid_sum=invalid_sum,
        )
