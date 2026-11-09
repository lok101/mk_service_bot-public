from __future__ import annotations

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore


def test_company_store_roundtrip() -> None:
    store = InMemoryCompanyStore()
    company = MasterCompany(
        company_id=123,
        name="Орлов М.О.",
        is_active=True,
        platform_bindings=(
            KitPlatformBinding(
                platform=KitPlatform.KIT_VENDING,
                kit_company_id=123,
                roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
            ),
        ),
    )
    store.upsert(company)
    loaded = store.get(123)
    assert loaded == company
    assert store.list_all() == (company,)
    assert store.is_empty() is False
