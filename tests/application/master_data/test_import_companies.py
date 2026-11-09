from __future__ import annotations

import json
from pathlib import Path

from src.application.master_data.companies import KitPlatformRole
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.application.master_data.import_companies import ImportCompaniesFromKitVendingAccounts
from src.application.master_data.legacy_kitvending_accounts import (
    LegacyKitVendingAccountRow,
    load_legacy_kitvending_accounts,
)
from src.application.master_data.memory import InMemoryMasterDataCounterStore
from src.application.master_data.models import COMPANY_COUNTER_KEY


def test_load_legacy_kitvending_accounts(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Head",
                    "login": "L1",
                    "password": "P1",
                    "company_id": 123,
                },
                {
                    "login": "L2",
                    "password": "P2",
                    "company_id": 456,
                },
            ],
        ),
        encoding="utf-8",
    )
    rows = load_legacy_kitvending_accounts(path)
    assert rows[0].company_id == 123
    assert rows[0].name == "Head"
    assert rows[1].name is None


def test_import_preserves_legacy_company_id() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    use_case = ImportCompaniesFromKitVendingAccounts(store=store, counters=counters)
    rows = (
        LegacyKitVendingAccountRow(index=0, company_id=123, name="Head", login="L1"),
        LegacyKitVendingAccountRow(index=1, company_id=456, name="Child", login="L2"),
    )
    result = use_case.execute(rows)
    assert result.imported == 2
    assert store.get(123) is not None
    assert store.get(456) is not None


def test_import_assigns_roles_by_index() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    use_case = ImportCompaniesFromKitVendingAccounts(store=store, counters=counters)
    rows = (
        LegacyKitVendingAccountRow(index=0, company_id=123, name="Head", login="L1"),
        LegacyKitVendingAccountRow(index=1, company_id=456, name="Child", login="L2"),
    )
    use_case.execute(rows)
    head = store.get(123)
    child = store.get(456)
    assert head is not None and child is not None
    head_roles = head.platform_bindings[0].roles
    child_roles = child.platform_bindings[0].roles
    assert KitPlatformRole.SALES_POLL in head_roles
    assert KitPlatformRole.CATALOG in head_roles
    assert head_roles != child_roles
    assert child_roles == (KitPlatformRole.CATALOG,)


def test_import_sets_company_counter_max_plus_one() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    use_case = ImportCompaniesFromKitVendingAccounts(store=store, counters=counters)
    rows = (LegacyKitVendingAccountRow(index=0, company_id=123, name="Head", login="L1"),)
    use_case.execute(rows)
    assert counters.get(COMPANY_COUNTER_KEY) == 124


def test_import_noop_when_store_not_empty() -> None:
    store = InMemoryCompanyStore()
    counters = InMemoryMasterDataCounterStore()
    use_case = ImportCompaniesFromKitVendingAccounts(store=store, counters=counters)
    rows = (LegacyKitVendingAccountRow(index=0, company_id=123, name="Head", login="L1"),)
    use_case.execute(rows)
    second = use_case.execute(rows)
    assert second.imported == 0
