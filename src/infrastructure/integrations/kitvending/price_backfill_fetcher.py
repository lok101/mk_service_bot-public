from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.inventory_reconciliation import KitSalePriceRow
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.source_id import build_sale_source_id


@beartype
@dataclass(frozen=True, slots=True)
class KitVendingMainApiPriceFetcher:
    """Читает `Sum` за окно через `main_api.get_sales` (head-аккаунт, `accounts[0]`).

    Не резолвит product/machine code — только source_id + сырой Sum, для price backfill.
    """

    main_api: KitVendingApiClient

    @beartype
    def fetch_price_rows(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> Sequence[KitSalePriceRow]:
        raw_sales = self.main_api.get_sales(from_date=from_date, to_date=to_date)
        return tuple(
            KitSalePriceRow(source_id=build_sale_source_id(sale), sum_value=sale.price)
            for sale in raw_sales
        )
