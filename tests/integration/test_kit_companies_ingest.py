from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.domain.ids import MachineId
from src.infrastructure.mongodb.companies import MongoCompanyStore
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient

pytestmark = pytest.mark.integration


def test_ingest_persists_mk_company_id_on_mongo_sale(
    mongo_database,
) -> None:
    company_store = MongoCompanyStore(collection=mongo_database["master_companies"])
    company_store.ensure_indexes()
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
    sales_store = MongoMachineSalesStore.from_collection(mongo_database["machine_sales"])
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
    ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")}),
    ).execute(since=datetime(2026, 6, 1, tzinfo=UTC))

    document = mongo_database["machine_sales"].find_one({"source_id": "kv-1"})
    assert document is not None
    assert document["company_id"] == 123
