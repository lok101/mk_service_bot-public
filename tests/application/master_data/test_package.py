from __future__ import annotations

from src.application.master_data import (
    COMPANY_COUNTER_KEY,
    CompanyStore,
    InMemoryCompanyStore,
    KitCompanyDirectory,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)


def test_public_surface_exports_companies() -> None:
    assert KitPlatform.KIT_VENDING.value == "kit_vending"
    assert COMPANY_COUNTER_KEY == "company"
    assert KitCompanyDirectory.__name__ == "KitCompanyDirectory"
    assert MasterCompany.__name__ == "MasterCompany"
    assert CompanyStore.__name__ == "CompanyStore"
    assert InMemoryCompanyStore.__name__ == "InMemoryCompanyStore"
    assert KitPlatformBinding.__name__ == "KitPlatformBinding"
    assert KitPlatformRole.__name__ == "KitPlatformRole"


def test_master_data_package_exports_models_and_ports() -> None:
    import src.application.master_data as md

    assert hasattr(md, "MasterLocation")
    assert hasattr(md, "MasterDataStores")
    assert hasattr(md, "allocate_machine_id")


def test_reference_data_ports_all_excludes_master_data_command_types() -> None:
    from src.application.reference_data import ports as rd_ports

    leaked = {
        "MasterDataStores",
        "MasterDataAuditStore",
        "MasterDataCounterStore",
        "MasterLocationStore",
        "MasterMachineStore",
        "MasterPlacementStore",
        "SystemUserStore",
        "TechnicianStore",
    } & set(rd_ports.__all__)
    assert leaked == set()
