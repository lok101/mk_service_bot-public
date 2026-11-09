from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.kitvending import (
    KitVendingFetchStats,
    KitVendingSaleRow,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def test_import_marks_only_new_inserts_as_inserted_occurred_ats() -> None:
    store = InMemoryMachineSalesStore()
    existing_occurred_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    store.insert_if_absent(
        MachineSale(
            source_id="kv-existing",
            machine_id=MachineId("129"),
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=existing_occurred_at,
            ingested_at=existing_occurred_at,
        ),
    )
    new_occurred_at = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-existing",
                "vending_machine_code": "129",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": existing_occurred_at.isoformat().replace("+00:00", "Z"),
            },
            {
                "source_id": "kv-new",
                "vending_machine_code": "129",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": new_occurred_at.isoformat().replace("+00:00", "Z"),
            },
        ],
    )
    import_sales = ImportKitVendingSales(sales_store=store, kitvending_client=client)

    result = import_sales.execute(since=datetime(2026, 8, 1, 0, 0, tzinfo=UTC))

    assert result.inserted == 1
    assert result.inserted_occurred_ats == (new_occurred_at,)
    assert result.success_occurred_ats == (existing_occurred_at, new_occurred_at)


@dataclass(slots=True)
class _CapturingKitVendingClient:
    rows: list[KitVendingSaleRow] = field(default_factory=list)
    captured: list[tuple[datetime, datetime | None]] = field(default_factory=list)
    last_fetch_stats: KitVendingFetchStats = field(default_factory=KitVendingFetchStats)

    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]:
        self.captured.append((since, until))
        return self.rows


def test_execute_passes_until_through_to_fetch_all() -> None:
    # happy: until доходит до kitvending_client.fetch_all без изменений
    store = InMemoryMachineSalesStore()
    client = _CapturingKitVendingClient()
    import_sales = ImportKitVendingSales(sales_store=store, kitvending_client=client)
    since = datetime(2026, 8, 1, tzinfo=UTC)
    until = datetime(2026, 8, 5, tzinfo=UTC)

    import_sales.execute(since=since, until=until)

    assert client.captured == [(since, until)]


def test_execute_without_until_still_calls_fetch_all_with_none() -> None:
    # regression: live-путь (без until) не меняется
    store = InMemoryMachineSalesStore()
    client = _CapturingKitVendingClient()
    import_sales = ImportKitVendingSales(sales_store=store, kitvending_client=client)
    since = datetime(2026, 8, 1, tzinfo=UTC)

    import_sales.execute(since=since)

    assert client.captured == [(since, None)]
