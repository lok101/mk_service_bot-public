from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.infrastructure.integrations.kitvending.platform_accounts import (
    KitPlatformAccount,
    load_kit_platform_accounts,
)
from src.infrastructure.integrations.kitvending.platform_accounts_validation import (
    validate_platform_accounts,
)


def test_load_platform_accounts_parses_roles(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": "vending-head",
                    "company_id": 123,
                    "platform": "kit_vending",
                    "kit_company_id": 123,
                    "role": "sales_poll",
                    "login": "L1",
                    "password": "P1",
                },
                {
                    "account_key": "vending-child",
                    "company_id": 456,
                    "platform": "kit_vending",
                    "kit_company_id": 456,
                    "role": "catalog",
                    "login": "L2",
                    "password": "P2",
                },
            ],
        ),
        encoding="utf-8",
    )
    accounts = load_kit_platform_accounts(path)
    assert len(accounts) == 2
    assert accounts[0].role is KitPlatformRole.SALES_POLL
    assert accounts[0].platform is KitPlatform.KIT_VENDING
    assert isinstance(accounts[0], KitPlatformAccount)


def test_load_platform_accounts_rejects_missing_role(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": "x",
                    "company_id": 1,
                    "platform": "kit_vending",
                    "kit_company_id": 1,
                    "login": "L",
                    "password": "P",
                },
            ],
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="role"):
        load_kit_platform_accounts(path)


def _account(**kwargs: object) -> KitPlatformAccount:
    defaults: dict[str, object] = {
        "account_key": "k",
        "company_id": 123,
        "platform": KitPlatform.KIT_VENDING,
        "kit_company_id": 123,
        "role": KitPlatformRole.SALES_POLL,
        "login": "L",
        "password": SecretStr("P"),
    }
    defaults.update(kwargs)
    return KitPlatformAccount(**defaults)


def test_validate_rejects_two_sales_poll_vending_accounts() -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=123,
            name="A",
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
    accounts = (
        _account(account_key="a1", role=KitPlatformRole.SALES_POLL),
        _account(
            account_key="a2",
            company_id=456,
            kit_company_id=456,
            role=KitPlatformRole.SALES_POLL,
        ),
    )
    with pytest.raises(ValueError, match="sales_poll"):
        validate_platform_accounts(accounts, company_store=store)


def test_validate_rejects_account_binding_mismatch() -> None:
    store = InMemoryCompanyStore()
    store.upsert(
        MasterCompany(
            company_id=123,
            name="A",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=999,
                    roles=(KitPlatformRole.SALES_POLL,),
                ),
            ),
        ),
    )
    accounts = (_account(kit_company_id=123),)
    with pytest.raises(ValueError, match="binding"):
        validate_platform_accounts(accounts, company_store=store)
