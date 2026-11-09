from __future__ import annotations

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.application.master_data.company_directory import KitCompanyDirectory


def _seed_head_company(store: InMemoryCompanyStore) -> None:
    store.upsert(
        MasterCompany(
            company_id=123,
            name="Орлов М.О.",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
                ),
                KitPlatformBinding(
                    platform=KitPlatform.KIT_SHOP,
                    kit_company_id=456,
                    roles=(KitPlatformRole.DEFAULT,),
                ),
            ),
        ),
    )


def test_resolve_kit_vending_id_to_mk_company_id() -> None:
    store = InMemoryCompanyStore()
    _seed_head_company(store)
    directory = KitCompanyDirectory(store)
    assert directory.resolve(KitPlatform.KIT_VENDING, 123) == 123
    assert directory.resolve(KitPlatform.KIT_SHOP, 456) == 123


def test_resolve_unknown_binding_returns_none() -> None:
    store = InMemoryCompanyStore()
    _seed_head_company(store)
    directory = KitCompanyDirectory(store)
    assert directory.resolve(KitPlatform.KIT_VENDING, 999) is None


def test_display_name_from_master_company() -> None:
    store = InMemoryCompanyStore()
    _seed_head_company(store)
    directory = KitCompanyDirectory(store)
    assert directory.display_name(123) == "Орлов М.О."
    assert directory.display_names()[123] == "Орлов М.О."
