from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.kitvending import (
    KitVendingFetchStats,
    KitVendingSaleRow,
)
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.domain.ids import MachineId
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
_KV_ROW = {
    "source_id": "kv-1",
    "vending_machine_code": "VM01",
    "product_code": "coffee-1",
    "quantity": "2",
    "occurred_at": "2026-06-05T12:00:00Z",
}


def test_import_inserts_new_sales_and_skips_duplicates() -> None:
    store = InMemoryMachineSalesStore()
    machine_map = {"VM01": MachineId("vm-01")}
    client = StubKitVendingClient(rows=[_KV_ROW])
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
    )

    first = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    second = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert first.inserted == 1
    assert first.skipped_unmapped == 0
    assert second.inserted == 0
    assert second.skipped_unmapped == 0
    assert first.affected_machine_ids == (MachineId("vm-01"),)
    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].quantity == Decimal("2")


def test_import_sets_sale_kind_from_vending_machine_code() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "129",
                "product_code": "2301",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00+00:00",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"129": MachineId("vm-01")}),
    )

    service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].sale_kind == "coffee"


def test_import_with_identity_resolver_prod_default() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW])
    service = ImportKitVendingSales(sales_store=store, kitvending_client=client)

    result = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.inserted == 1
    assert result.skipped_unmapped == 0
    assert result.affected_machine_ids == (MachineId("VM01"),)
    sales = store.find_in_window(
        MachineId("VM01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].machine_id == MachineId("VM01")


def test_import_returns_batch_max_occurred_at_from_all_fetched_rows() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-unmapped",
                "vending_machine_code": "UNKNOWN",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-07T18:00:00Z",
            },
            {
                "source_id": "kv-mapped",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00Z",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("VM01")}),
    )

    result = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.batch_max_occurred_at == datetime(2026, 6, 7, 18, 0, tzinfo=UTC)


def test_import_batch_max_occurred_at_none_when_fetch_empty() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[])
    service = ImportKitVendingSales(sales_store=store, kitvending_client=client)

    result = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.batch_max_occurred_at is None


def test_import_counts_skipped_unmapped_codes() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "UNKNOWN",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00Z",
            },
            {
                "source_id": "kv-2",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T13:00:00Z",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("VM01")}),
    )

    result = service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.inserted == 1
    assert result.skipped_unmapped == 1
    assert result.affected_machine_ids == (MachineId("VM01"),)


def test_import_uses_injected_clock_for_ingested_at() -> None:
    fixed = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(rows=[_KV_ROW])
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        now=lambda: fixed,
    )

    service.execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    sales = store.find_in_window(
        MachineId("VM01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert sales[0].ingested_at == fixed


def test_import_kitvending_sales_reads_fetch_stats_from_protocol_client() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[_KV_ROW],
        fetch_stats=KitVendingFetchStats(
            skipped_unresolved_product=3,
            skipped_no_machine_code=2,
        ),
    )
    result = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
    ).execute(since=datetime(2026, 6, 1, 0, 0, tzinfo=UTC))

    assert result.skipped_unresolved_product == 3
    assert result.skipped_no_machine_code == 2


def test_kit_vending_sale_row_carries_price() -> None:
    row = KitVendingSaleRow(
        source_id="src-1",
        vending_machine_code="VM1",
        product_code="P1",
        quantity=Decimal("1"),
        occurred_at=_NOW,
        price=Decimal("120.00"),
    )
    assert row.price == Decimal("120.00")


def test_import_maps_kit_sum_to_price() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "src-price-1",
                "vending_machine_code": "VM01",
                "product_code": "P1",
                "quantity": "1",
                "occurred_at": "2026-07-27T12:00:00Z",
                "price": "77.7",
            },
        ],
    )
    service = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
    )

    service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 7, 1, tzinfo=UTC),
        closed_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].price == Decimal("77.7")


def test_stub_row_carries_company_id() -> None:
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "42",
            },
        ],
    )
    rows = client.fetch_all(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0].company_id == 42


def test_import_persists_company_id_on_insert() -> None:
    store = InMemoryMachineSalesStore()
    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "42",
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
    assert sales[0].company_id == 42


def test_import_patches_company_id_when_existing_is_missing() -> None:
    store = InMemoryMachineSalesStore()
    machine_map = {"VM01": MachineId("vm-01")}
    first_client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
            },
        ],
    )
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=first_client,
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    second_client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "42",
            },
        ],
    )
    result = ImportKitVendingSales(
        sales_store=store,
        kitvending_client=second_client,
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    assert result.inserted == 0
    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert sales[0].company_id == 42


def test_import_does_not_overwrite_existing_company_id() -> None:
    store = InMemoryMachineSalesStore()
    machine_map = {"VM01": MachineId("vm-01")}
    first_client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "42",
            },
        ],
    )
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=first_client,
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    second_client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "2",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "99",
            },
        ],
    )
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=second_client,
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    sales = store.find_in_window(
        MachineId("vm-01"),
        opened_at=datetime(2026, 6, 1, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    assert sales[0].company_id == 42


def test_import_rebuilds_occupancy_after_insert() -> None:
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
                "company_id": "1",
            },
            {
                "source_id": "kv-2",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-20T08:00:00Z",
                "company_id": "2",
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
    assert intervals[0].company_id == 1
    assert intervals[1].company_id == 2
    assert intervals[1].valid_from == datetime(2026, 6, 20, 8, 0, tzinfo=UTC)


def test_import_rebuilds_occupancy_after_patch() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    machine_map = {"VM01": MachineId("vm-01")}
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(
            rows=[
                {
                    "source_id": "kv-1",
                    "vending_machine_code": "VM01",
                    "product_code": "coffee-1",
                    "quantity": "1",
                    "occurred_at": "2026-06-05T12:00:00Z",
                },
            ],
        ),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert occupancy.list_for_machine(MachineId("vm-01")) == ()

    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(
            rows=[
                {
                    "source_id": "kv-1",
                    "vending_machine_code": "VM01",
                    "product_code": "coffee-1",
                    "quantity": "1",
                    "occurred_at": "2026-06-05T12:00:00Z",
                    "company_id": "7",
                },
            ],
        ),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    intervals = occupancy.list_for_machine(MachineId("vm-01"))
    assert len(intervals) == 1
    assert intervals[0].company_id == 7


def test_import_skips_rebuild_when_duplicate_already_has_company_id() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    machine_map = {"VM01": MachineId("vm-01")}
    rows = [
        {
            "source_id": "kv-1",
            "vending_machine_code": "VM01",
            "product_code": "coffee-1",
            "quantity": "1",
            "occurred_at": "2026-06-05T12:00:00Z",
            "company_id": "7",
        },
    ]
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(rows=rows),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    occupancy.replace_for_machine(MachineId("vm-01"), ())
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(rows=rows),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert occupancy.list_for_machine(MachineId("vm-01")) == ()


def test_import_triggers_export_once_after_occupancy_rebuild() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    calls: list[int] = []

    def _hook() -> None:
        calls.append(1)

    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-1",
                "vending_machine_code": "VM01",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-05T12:00:00Z",
                "company_id": "1",
            },
            {
                "source_id": "kv-2",
                "vending_machine_code": "VM02",
                "product_code": "coffee-1",
                "quantity": "1",
                "occurred_at": "2026-06-06T12:00:00Z",
                "company_id": "2",
            },
        ],
    )
    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver(
            {"VM01": MachineId("vm-01"), "VM02": MachineId("vm-02")}
        ),
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(calls) == 1
    assert occupancy.list_for_machine(MachineId("vm-01"))
    assert occupancy.list_for_machine(MachineId("vm-02"))


def test_import_skips_export_when_no_rebuild() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    calls: list[int] = []
    rows = [
        {
            "source_id": "kv-1",
            "vending_machine_code": "VM01",
            "product_code": "coffee-1",
            "quantity": "1",
            "occurred_at": "2026-06-05T12:00:00Z",
            "company_id": "1",
        },
    ]
    machine_map = {"VM01": MachineId("vm-01")}

    def _hook() -> None:
        calls.append(1)

    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(rows=rows),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(calls) == 1

    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(rows=rows),
        code_resolver=MappingVendingMachineCodeResolver(machine_map),
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(calls) == 1  # второй tick без insert/patch — hook не звать


def test_import_keeps_occupancy_when_export_raises() -> None:
    store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()

    def _boom() -> None:
        raise RuntimeError("sheets down")

    ImportKitVendingSales(
        sales_store=store,
        kitvending_client=StubKitVendingClient(
            rows=[
                {
                    "source_id": "kv-1",
                    "vending_machine_code": "VM01",
                    "product_code": "coffee-1",
                    "quantity": "1",
                    "occurred_at": "2026-06-05T12:00:00Z",
                    "company_id": "1",
                },
            ],
        ),
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
        occupancy_store=occupancy,
        after_occupancy_rebuild=_boom,
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))
    intervals = occupancy.list_for_machine(MachineId("vm-01"))
    assert len(intervals) == 1
    assert intervals[0].company_id == 1
