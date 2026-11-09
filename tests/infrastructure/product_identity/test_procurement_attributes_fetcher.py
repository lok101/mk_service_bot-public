from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementSupplySnapshot,
)
from src.infrastructure.moysklad.purchase_prices.models import LastSupplyProcurementRow
from src.infrastructure.product_identity.procurement_attributes_fetcher import (
    MoySkladProcurementAttributesFetcher,
)


class _Client:
    def __init__(self, result: LastSupplyProcurementRow | None) -> None:
        self._result = result

    def fetch_last_supply_procurement(self, catalog_code: str) -> LastSupplyProcurementRow | None:
        assert catalog_code == "2311"
        return self._result


def test_adapter_maps_row_to_supply_snapshot() -> None:
    row = LastSupplyProcurementRow(
        catalog_code="2311",
        supplier_id="agent-1",
        supplier_name="ООО",
        last_buy_price=Decimal("12.50"),
        supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        package_quantity=Decimal("6"),
        supplier_product_name="Салат у поставщика",
    )
    result = MoySkladProcurementAttributesFetcher(client=_Client(row)).fetch("2311")
    assert result == ProcurementSupplySnapshot(
        catalog_code="2311",
        supplier_id="agent-1",
        supplier_name="ООО",
        last_buy_price=Decimal("12.50"),
        supply_moment=datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        package_quantity=Decimal("6"),
        supplier_product_name="Салат у поставщика",
    )


def test_adapter_maps_none_to_fetch_failed() -> None:
    result = MoySkladProcurementAttributesFetcher(client=_Client(None)).fetch("2311")
    assert result == ProcurementFetchFailed(catalog_code="2311")
