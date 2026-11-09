from __future__ import annotations

import json
from pathlib import Path

from beartype import beartype
from pydantic import SecretStr

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount


def platform_account_row(
    *,
    account_key: str = "a1",
    company_id: int = 42,
    kit_company_id: int | None = None,
    platform: str = "kit_vending",
    role: str = "sales_poll",
    login: str = "user",
    password: str = "pass",
) -> dict[str, object]:
    resolved_kit_id = kit_company_id if kit_company_id is not None else company_id
    return {
        "account_key": account_key,
        "company_id": company_id,
        "platform": platform,
        "kit_company_id": resolved_kit_id,
        "role": role,
        "login": login,
        "password": password,
    }


def write_platform_accounts_file(path: Path, *rows: dict[str, object]) -> None:
    path.write_text(json.dumps(list(rows)), encoding="utf-8")


@beartype
def seed_matching_company_store(
    store: InMemoryCompanyStore,
    *,
    company_id: int = 42,
    kit_company_id: int | None = None,
    roles: tuple[KitPlatformRole, ...] = (KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG),
) -> None:
    resolved_kit_id = kit_company_id if kit_company_id is not None else company_id
    store.upsert(
        MasterCompany(
            company_id=company_id,
            name=f"Company {company_id}",
            is_active=True,
            platform_bindings=(
                KitPlatformBinding(
                    platform=KitPlatform.KIT_VENDING,
                    kit_company_id=resolved_kit_id,
                    roles=roles,
                ),
            ),
        ),
    )


def make_platform_account(
    *,
    account_key: str = "a1",
    company_id: int = 42,
    kit_company_id: int | None = None,
    platform: KitPlatform = KitPlatform.KIT_VENDING,
    role: KitPlatformRole = KitPlatformRole.SALES_POLL,
    login: str = "user",
    password: str = "pass",
) -> KitPlatformAccount:
    resolved_kit_id = kit_company_id if kit_company_id is not None else company_id
    return KitPlatformAccount(
        account_key=account_key,
        company_id=company_id,
        platform=platform,
        kit_company_id=resolved_kit_id,
        role=role,
        login=login,
        password=SecretStr(password),
    )
