from __future__ import annotations

from datetime import UTC, datetime

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.kitvending import (
    HoldingSkipSample,
    KitVendingFetchStats,
)
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.domain.ids import MachineId
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_HOLD_AT = datetime(2026, 5, 2, 7, 0, tzinfo=UTC)
_KV_ROW = {
    "source_id": "kv-hold-1",
    "vending_machine_code": "VM01",
    "product_code": "coffee-1",
    "quantity": "1",
    "occurred_at": "2026-05-02T06:00:00Z",
}


def test_import_result_exposes_hold_at_from_fetch_stats() -> None:
    store = InMemoryMachineSalesStore()
    sample = HoldingSkipSample(
        occurred_at=_HOLD_AT,
        reason_class="critical_product_resolve",
        machine_key="176",
    )
    fetch_stats = KitVendingFetchStats(
        holding_skip_count=1,
        hold_at=_HOLD_AT,
        holding_samples=(sample,),
        fingerprint_pairs=(("176", "critical_product_resolve"),),
    )
    client = StubKitVendingClient(rows=[_KV_ROW], fetch_stats=fetch_stats)
    result = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
    ).execute(since=datetime(2026, 5, 1, tzinfo=UTC))

    assert result.hold_at == fetch_stats.hold_at
    assert result.fingerprint_pairs == fetch_stats.fingerprint_pairs
    assert result.holding_skip_count == fetch_stats.holding_skip_count
    assert result.holding_samples == fetch_stats.holding_samples
    assert result.success_occurred_ats == (datetime(2026, 5, 2, 6, 0, tzinfo=UTC),)
    assert result.batch_max_occurred_at == datetime(2026, 5, 2, 6, 0, tzinfo=UTC)
