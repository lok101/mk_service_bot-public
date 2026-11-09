from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.application.inventory_reconciliation import (
    backfill_sales_company_id,
    rebuild_company_occupancy_from_sales,
    verify_company_occupancy,
)
from src.application.master_data import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
    generate_platform_accounts_from_legacy,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.application.master_data.company_directory import KitCompanyDirectory
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def test_generate_platform_accounts_from_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            [
                {
                    "name": "Head",
                    "login": "L1",
                    "password": "SECRET1",
                    "company_id": 123,
                },
                {
                    "name": "Child",
                    "login": "L2",
                    "password": "SECRET2",
                    "company_id": 456,
                },
            ],
        ),
        encoding="utf-8",
    )
    out = tmp_path / "platform.json"
    generate_platform_accounts_from_legacy(legacy_path=legacy, output_path=out)
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert rows[0]["role"] == "sales_poll"
    assert rows[0]["platform"] == "kit_vending"
    assert rows[0]["kit_company_id"] == 123
    assert rows[0]["company_id"] == 123
    assert rows[1]["role"] == "catalog"


def test_backfill_patches_only_null_company_id() -> None:
    store = InMemoryMachineSalesStore()
    occurred = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 12, 1, tzinfo=UTC)
    store.insert_if_absent(
        MachineSale(
            source_id="sale-a",
            machine_id=MachineId("vm-01"),
            product_code="p1",
            quantity=Decimal("1"),
            occurred_at=occurred,
            ingested_at=ingested,
            company_id=None,
            kit_vending_company_id=123,
        ),
    )
    store.insert_if_absent(
        MachineSale(
            source_id="sale-b",
            machine_id=MachineId("vm-01"),
            product_code="p2",
            quantity=Decimal("1"),
            occurred_at=occurred,
            ingested_at=ingested,
            company_id=123,
        ),
    )
    company_store = InMemoryCompanyStore()
    company_store.upsert(
        MasterCompany(
            company_id=123,
            name="Head",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
                ),
            ),
        ),
    )
    directory = KitCompanyDirectory(company_store)

    result = backfill_sales_company_id(
        sales_store=store,
        resolve_mk_company_id=lambda kit_id: directory.resolve(
            KitPlatform.KIT_VENDING,
            kit_id,
        ),
    )

    assert result.patched == 1
    sales = store.list_with_company_id(MachineId("vm-01"))
    by_source = {sale.source_id: sale.company_id for sale in sales}
    assert by_source["sale-a"] == 123
    assert by_source["sale-b"] == 123


def test_rebuild_occupancy_cli_registered() -> None:
    from scripts.companies_admin import build_parser

    parser = build_parser()
    args = parser.parse_args(["rebuild-occupancy"])
    assert args.command == "rebuild-occupancy"


def test_verify_occupancy_reports_no_mismatches_when_aligned() -> None:
    sales_store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    occurred = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 12, 1, tzinfo=UTC)
    sales_store.insert_if_absent(
        MachineSale(
            source_id="sale-a",
            machine_id=MachineId("vm-01"),
            product_code="p1",
            quantity=Decimal("1"),
            occurred_at=occurred,
            ingested_at=ingested,
            company_id=123,
        ),
    )
    from src.application.inventory_reconciliation.company_occupancy import (
        rebuild_company_occupancy,
    )

    intervals = rebuild_company_occupancy(
        MachineId("vm-01"),
        sales_store.list_with_company_id(MachineId("vm-01")),
    )
    occupancy.replace_for_machine(MachineId("vm-01"), intervals)

    result = verify_company_occupancy(sales_store=sales_store, occupancy_store=occupancy)

    assert result.machines_checked == 1
    assert result.mismatches == ()


def test_rebuild_occupancy_from_sales_fills_empty_store() -> None:
    sales_store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    occurred = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 12, 1, tzinfo=UTC)
    sales_store.insert_if_absent(
        MachineSale(
            source_id="sale-mm",
            machine_id=MachineId("701"),
            product_code="p1",
            quantity=Decimal("1"),
            occurred_at=occurred,
            ingested_at=ingested,
            company_id=7,
            sale_kind="micromarket",
        ),
    )
    assert occupancy.list_for_machine(MachineId("701")) == ()

    result = rebuild_company_occupancy_from_sales(
        sales_store=sales_store,
        occupancy_store=occupancy,
    )

    assert result.machines_rebuilt == 1
    intervals = occupancy.list_for_machine(MachineId("701"))
    assert len(intervals) == 1
    assert intervals[0].company_id == 7
    assert intervals[0].valid_to is None
    verify = verify_company_occupancy(sales_store=sales_store, occupancy_store=occupancy)
    assert verify.mismatches == ()


def test_rebuild_occupancy_noop_without_company_id_sales() -> None:
    sales_store = InMemoryMachineSalesStore()
    occupancy = InMemoryMachineCompanyOccupancyStore()
    occurred = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    ingested = datetime(2026, 6, 5, 12, 1, tzinfo=UTC)
    sales_store.insert_if_absent(
        MachineSale(
            source_id="sale-null",
            machine_id=MachineId("vm-01"),
            product_code="p1",
            quantity=Decimal("1"),
            occurred_at=occurred,
            ingested_at=ingested,
            company_id=None,
        ),
    )
    result = rebuild_company_occupancy_from_sales(
        sales_store=sales_store,
        occupancy_store=occupancy,
    )
    assert result.machines_rebuilt == 0
    assert occupancy.list_for_machine(MachineId("vm-01")) == ()
