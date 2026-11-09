from __future__ import annotations

from beartype import beartype

from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementSupplySnapshot,
)


@beartype
class MoySkladProcurementAttributesFetcher:
    def __init__(self, *, client: object) -> None:
        self._client = client

    @beartype
    def fetch(self, catalog_code: str) -> ProcurementSupplySnapshot | ProcurementFetchFailed:
        fetch = getattr(self._client, "fetch_last_supply_procurement", None)
        if fetch is None:
            return ProcurementFetchFailed(catalog_code=catalog_code)
        row = fetch(catalog_code)
        if row is None:
            return ProcurementFetchFailed(catalog_code=catalog_code)
        return ProcurementSupplySnapshot(
            catalog_code=row.catalog_code,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            last_buy_price=row.last_buy_price,
            supply_moment=row.supply_moment,
            package_quantity=row.package_quantity,
            supplier_product_name=row.supplier_product_name,
        )
