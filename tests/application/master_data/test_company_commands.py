from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.master_data import (
    COMPANY_COUNTER_KEY,
    CompanyValidationError,
    CreateCompany,
    InMemoryCompanyStore,
    InMemoryMasterDataAuditStore,
    InMemoryMasterDataCounterStore,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
    UpdateCompany,
    allocate_company_id,
)

_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_ACTOR = 42


def _create_uc(
    store: InMemoryCompanyStore | None = None,
    counters: InMemoryMasterDataCounterStore | None = None,
    audit: InMemoryMasterDataAuditStore | None = None,
) -> tuple[CreateCompany, InMemoryCompanyStore, InMemoryMasterDataAuditStore]:
    store = store or InMemoryCompanyStore()
    counters = counters or InMemoryMasterDataCounterStore()
    audit = audit or InMemoryMasterDataAuditStore()
    return (
        CreateCompany(store=store, counters=counters, audit=audit),
        store,
        audit,
    )


def _vending(*, kit_id: int, roles: tuple[KitPlatformRole, ...]) -> KitPlatformBinding:
    return KitPlatformBinding(
        platform=KitPlatform.KIT_VENDING,
        kit_company_id=kit_id,
        roles=roles,
    )


def test_allocate_company_id_uses_max_existing_plus_one() -> None:
    store = InMemoryCompanyStore()
    store.upsert(MasterCompany(company_id=7, name="A", is_active=True))
    counters = InMemoryMasterDataCounterStore()
    # empty counter must still jump to max_existing+1
    assert allocate_company_id(counters, store=store) == 8
    assert counters.allocate_next(COMPANY_COUNTER_KEY) == 9


def test_allocate_company_id_respects_seeded_counter() -> None:
    store = InMemoryCompanyStore()
    store.upsert(MasterCompany(company_id=3, name="A", is_active=True))
    counters = InMemoryMasterDataCounterStore()
    counters.set(COMPANY_COUNTER_KEY, 10)
    assert allocate_company_id(counters, store=store) == 11


def test_create_company_allocates_and_audits() -> None:
    uc, store, audit = _create_uc()
    company = uc.execute(
        name="  Ромашка  ",
        bindings=(),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    assert company.company_id == 1
    assert company.name == "Ромашка"
    assert company.is_active is True
    assert store.get(1) == company
    assert len(audit.list_all()) == 1
    record = audit.list_all()[0]
    assert record.command == "create_company"
    assert record.payload == {"company_id": "1"}
    assert record.actor_telegram_user_id == _ACTOR


def test_create_company_rejects_blank_name() -> None:
    uc, _, _ = _create_uc()
    with pytest.raises(CompanyValidationError):
        uc.execute(name="  ", bindings=(), actor_telegram_user_id=_ACTOR, now=_NOW)


def test_create_rejects_invalid_vending_roles() -> None:
    uc, _, _ = _create_uc()
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="X",
            bindings=(_vending(kit_id=1, roles=(KitPlatformRole.DEFAULT,)),),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_rejects_empty_vending_roles() -> None:
    uc, _, _ = _create_uc()
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="X",
            bindings=(_vending(kit_id=1, roles=()),),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_rejects_invalid_shop_roles() -> None:
    uc, _, _ = _create_uc()
    binding = KitPlatformBinding(
        platform=KitPlatform.KIT_SHOP,
        kit_company_id=9,
        roles=(KitPlatformRole.SALES_POLL,),
    )
    with pytest.raises(CompanyValidationError):
        uc.execute(name="X", bindings=(binding,), actor_telegram_user_id=_ACTOR, now=_NOW)


def test_create_rejects_second_global_sales_poll() -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=1,
            name="Existing",
            is_active=True,
            platform_bindings=(
                _vending(kit_id=10, roles=(KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG)),
            ),
        )
    )
    uc, _, _ = _create_uc(store=store)
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="New",
            bindings=(_vending(kit_id=11, roles=(KitPlatformRole.SALES_POLL,)),),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_rejects_duplicate_binding_across_companies() -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=1,
            name="Existing",
            is_active=True,
            platform_bindings=(_vending(kit_id=10, roles=(KitPlatformRole.CATALOG,)),),
        )
    )
    uc, _, _ = _create_uc(store=store)
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="New",
            bindings=(_vending(kit_id=10, roles=(KitPlatformRole.CATALOG,)),),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_rejects_duplicate_binding_in_form() -> None:
    uc, _, _ = _create_uc()
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="X",
            bindings=(
                _vending(kit_id=1, roles=(KitPlatformRole.CATALOG,)),
                _vending(kit_id=1, roles=(KitPlatformRole.CATALOG,)),
            ),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_create_rejects_non_positive_kit_company_id() -> None:
    uc, _, _ = _create_uc()
    with pytest.raises(CompanyValidationError):
        uc.execute(
            name="X",
            bindings=(_vending(kit_id=0, roles=(KitPlatformRole.CATALOG,)),),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_update_company_replaces_bindings() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateCompany(store=store, counters=counters, audit=audit).execute(
        name="A",
        bindings=(_vending(kit_id=1, roles=(KitPlatformRole.CATALOG,)),),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    shop = KitPlatformBinding(
        platform=KitPlatform.KIT_SHOP,
        kit_company_id=5,
        roles=(KitPlatformRole.DEFAULT,),
    )
    updated = UpdateCompany(store=store, audit=audit).execute(
        company_id=created.company_id,
        name="A2",
        is_active=True,
        bindings=(shop,),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    assert updated.name == "A2"
    assert updated.platform_bindings == (shop,)
    assert any(r.command == "update_company" for r in audit.list_all())


def test_update_deactivate_keeps_company_id() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateCompany(store=store, counters=counters, audit=audit).execute(
        name="A",
        bindings=(),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    updated = UpdateCompany(store=store, audit=audit).execute(
        company_id=created.company_id,
        name="A",
        is_active=False,
        bindings=(),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    assert updated.is_active is False
    assert updated.company_id == created.company_id


def test_update_unknown_company_rejected() -> None:
    store = InMemoryCompanyStore()
    audit = InMemoryMasterDataAuditStore()
    with pytest.raises(CompanyValidationError):
        UpdateCompany(store=store, audit=audit).execute(
            company_id=999,
            name="X",
            is_active=True,
            bindings=(),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )


def test_update_rejects_blank_name() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    audit = InMemoryMasterDataAuditStore()
    created = CreateCompany(store=store, counters=counters, audit=audit).execute(
        name="A",
        bindings=(),
        actor_telegram_user_id=_ACTOR,
        now=_NOW,
    )
    with pytest.raises(CompanyValidationError):
        UpdateCompany(store=store, audit=audit).execute(
            company_id=created.company_id,
            name="  ",
            is_active=True,
            bindings=(),
            actor_telegram_user_id=_ACTOR,
            now=_NOW,
        )
