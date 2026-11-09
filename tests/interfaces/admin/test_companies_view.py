from __future__ import annotations

import pytest

from src.application.master_data import (
    CompanyValidationError,
    InMemoryCompanyStore,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.interfaces.admin.companies_view import (
    bindings_from_form,
    build_companies_list_view,
    format_bindings_summary,
    parse_company_list_status,
)


def test_parse_company_list_status_default_active() -> None:
    assert parse_company_list_status(None) == "active"
    assert parse_company_list_status("inactive") == "inactive"
    assert parse_company_list_status("all") == "all"
    assert parse_company_list_status("weird") == "active"


def test_format_bindings_summary() -> None:
    summary = format_bindings_summary(
        (
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
        )
    )
    assert "vending:123" in summary
    assert "poll" in summary or "sales_poll" in summary
    assert "shop:456" in summary


def test_companies_list_default_active_only() -> None:
    store = InMemoryCompanyStore()
    store.upsert(MasterCompany(company_id=1, name="A", is_active=True))
    store.upsert(MasterCompany(company_id=2, name="B", is_active=False))
    view = build_companies_list_view(store, status="active")
    assert [r.name for r in view.rows] == ["A"]


def test_companies_list_filter_inactive() -> None:
    store = InMemoryCompanyStore()
    store.upsert(MasterCompany(company_id=1, name="A", is_active=True))
    store.upsert(MasterCompany(company_id=2, name="B", is_active=False))
    view = build_companies_list_view(store, status="inactive")
    assert [r.name for r in view.rows] == ["B"]


def test_companies_list_filter_all() -> None:
    store = InMemoryCompanyStore()
    store.upsert(MasterCompany(company_id=1, name="A", is_active=True))
    store.upsert(MasterCompany(company_id=2, name="B", is_active=False))
    view = build_companies_list_view(store, status="all")
    assert [r.name for r in view.rows] == ["A", "B"]


def test_bindings_from_form_indexed_rows() -> None:
    bindings = bindings_from_form(
        {
            "platform-0": "kit_vending",
            "kit_company_id-0": "123",
            "role-sales_poll-0": "on",
            "role-catalog-0": "on",
            "platform-1": "kit_shop",
            "kit_company_id-1": "456",
            "role-default-1": "on",
        }
    )
    assert len(bindings) == 2
    assert bindings[0].platform is KitPlatform.KIT_VENDING
    assert bindings[0].kit_company_id == 123
    assert KitPlatformRole.SALES_POLL in bindings[0].roles
    assert bindings[1].platform is KitPlatform.KIT_SHOP
    assert bindings[1].kit_company_id == 456


def test_bindings_from_form_incomplete_row() -> None:
    with pytest.raises(CompanyValidationError):
        bindings_from_form({"platform-0": "kit_vending"})


def test_bindings_from_form_invalid_platform() -> None:
    with pytest.raises(CompanyValidationError):
        bindings_from_form({"platform-0": "nope", "kit_company_id-0": "1"})
