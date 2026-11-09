from __future__ import annotations

import logging
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.infrastructure.kitvending.test_kitvending_http_client import (
    _client_with_fixtures,
    load_fixture,
)

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.application.master_data.company_directory import KitCompanyDirectory


def _directory_with_head() -> KitCompanyDirectory:
    store = InMemoryCompanyStore()
    store.upsert(
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
    return KitCompanyDirectory(store)


def _single_sale_payload(*, company_id: int) -> dict[str, Any]:
    payload = deepcopy(load_fixture("get_sales.json"))
    sale = payload["Sales"][0]
    sale["CompanyId"] = company_id
    payload["Sales"] = [sale]
    return payload


def test_client_maps_vending_company_to_mk_id_on_sale_row() -> None:
    directory = _directory_with_head()
    client = _client_with_fixtures(
        sales_json=_single_sale_payload(company_id=123),
        company_directory=directory,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0].company_id == 123


def test_unresolved_company_id_holding_skip_no_insert() -> None:
    directory = KitCompanyDirectory(InMemoryCompanyStore())
    client = _client_with_fixtures(
        sales_json=_single_sale_payload(company_id=999),
        company_directory=directory,
    )
    rows = client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert rows == []
    assert client.last_fetch_stats.holding_skip_count == 1


def test_unresolved_company_logs_resolve_miss(caplog: pytest.LogCaptureFixture) -> None:
    directory = KitCompanyDirectory(InMemoryCompanyStore())
    caplog.set_level(logging.WARNING)
    client = _client_with_fixtures(
        sales_json=_single_sale_payload(company_id=999),
        company_directory=directory,
    )
    client.fetch_all(since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC))
    assert any("kit_company_resolve_miss" in record.message for record in caplog.records)
