from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.kitvending import (
    KitVendingFetchStats,
    KitVendingSaleRow,
)
from src.domain.ids import MachineId
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_PORTION_VERIFY_SOURCE = Path("src/application/inventory_reconciliation/verify_portion_sales.py")


@dataclass(slots=True)
class _RowClient:
    row: KitVendingSaleRow
    last_fetch_stats: KitVendingFetchStats = field(default_factory=KitVendingFetchStats)

    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]:
        return [self.row]


def test_import_sales_copies_domain_product_id() -> None:
    sales = InMemoryMachineSalesStore()
    occurred = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    client = _RowClient(
        KitVendingSaleRow(
            source_id="kit:1",
            vending_machine_code="701",
            product_code="2311",
            quantity=Decimal("1"),
            occurred_at=occurred,
            domain_product_id="prod-1",
        ),
    )
    ImportKitVendingSales(sales_store=sales, kitvending_client=client).execute(since=occurred)
    saved = sales._by_source_id["kit:1"]
    assert saved.domain_product_id == "prod-1"
    assert saved.product_code == "2311"
    assert saved.machine_id == MachineId("701")


def test_portion_verify_copies_domain_product_id() -> None:
    source = _PORTION_VERIFY_SOURCE.read_text(encoding="utf-8")
    assert "domain_product_id=row.domain_product_id" in source
