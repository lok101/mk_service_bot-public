from __future__ import annotations

from datetime import UTC, datetime

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.domain.ids import MachineId
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def test_import_persists_mk_company_id_on_insert() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "123",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
    )
    service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].company_id == 123


def test_import_rebuilds_occupancy_with_mk_company_id() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "123",
            },
            {
                "source_id": "kv-2",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-20T08:00:00Z",
                "company_id": "456",
            },
        ],
    )
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
        occupancy_store=occupancy,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    intervals = occupancy.list_for_machine(MachineId("vm-01"))
    assert len(intervals) == 2
    assert intervals[0].company_id == 123
    assert intervals[1].company_id == 456
    assert intervals[1].valid_from == datetime(2026, 6, 20, 8, 0, tzinfo=UTC)
