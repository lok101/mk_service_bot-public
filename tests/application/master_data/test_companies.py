from __future__ import annotations

import pytest

from src.application.master_data.companies import (
    DuplicatePlatformBinding,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
    validate_bindings_unique,
)


def test_master_company_holds_bindings() -> None:
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
    assert company.company_id == 123
    assert company.platform_bindings[0].platform is KitPlatform.KIT_VENDING


def test_validate_bindings_unique_accepts_distinct_platform_ids() -> None:
    companies = (
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
        MasterCompany(
            company_id=456,
            name="Child",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=456,
                    roles=(KitPlatformRole.CATALOG,),
                ),
            ),
        ),
    )
    validate_bindings_unique(companies)


def test_duplicate_platform_binding_rejected() -> None:
    companies = (
        MasterCompany(
            company_id=123,
            name="A",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.CATALOG,),
                ),
            ),
        ),
        MasterCompany(
            company_id=456,
            name="B",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=123,
                    roles=(KitPlatformRole.CATALOG,),
                ),
            ),
        ),
    )
    with pytest.raises(DuplicatePlatformBinding):
        validate_bindings_unique(companies)
