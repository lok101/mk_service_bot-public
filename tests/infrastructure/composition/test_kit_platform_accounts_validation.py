from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.companies_memory import InMemoryCompanyStore
from src.config.kitvending import KitVendingSettings
from src.infrastructure.composition.factories.integrations import build_kitvending_client
from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)


def _head_and_child_accounts() -> tuple[KitPlatformAccount, KitPlatformAccount]:
    return (
        KitPlatformAccount(
            account_key="vending-head",
            company_id=123,
            platform=KitPlatform.KIT_VENDING,
            kit_company_id=123,
            role=KitPlatformRole.SALES_POLL,
            login="L1",
            password=SecretStr("P1"),
        ),
        KitPlatformAccount(
            account_key="vending-child",
            company_id=456,
            platform=KitPlatform.KIT_VENDING,
            kit_company_id=456,
            role=KitPlatformRole.CATALOG,
            login="L2",
            password=SecretStr("P2"),
        ),
    )


def _seed_company_store() -> InMemoryCompanyStore:
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
    store.upsert(
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
    return store


def test_build_kitvending_client_uses_sales_poll_for_main_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, child = _head_and_child_accounts()
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.load_kit_platform_accounts",
        lambda _path: [head, child],
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.accounts_file_is_valid",
        lambda _path: True,
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=__import__("pathlib").Path("ignored.json"),
        ingestion_enabled=True,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        company_store=_seed_company_store(),
        http_client=httpx.Client(),
    )
    assert isinstance(client, KitVendingHttpClient)
    assert client.main_api.account.login == "L1"


def test_build_kitvending_client_catalog_clients_include_catalog_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, child = _head_and_child_accounts()
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.load_kit_platform_accounts",
        lambda _path: [head, child],
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.accounts_file_is_valid",
        lambda _path: True,
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=__import__("pathlib").Path("ignored.json"),
        ingestion_enabled=True,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        company_store=_seed_company_store(),
        http_client=httpx.Client(),
    )
    assert isinstance(client, KitVendingHttpClient)
    catalog_logins = {api.account.login for api in client.catalog_clients}
    assert len(client.catalog_clients) == 2
    assert "L2" in catalog_logins


def test_build_kitvending_client_catalog_includes_head_when_binding_has_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, child = _head_and_child_accounts()
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.load_kit_platform_accounts",
        lambda _path: [head, child],
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.accounts_file_is_valid",
        lambda _path: True,
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=__import__("pathlib").Path("ignored.json"),
        ingestion_enabled=True,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        company_store=_seed_company_store(),
        http_client=httpx.Client(),
    )
    assert isinstance(client, KitVendingHttpClient)
    catalog_logins = {api.account.login for api in client.catalog_clients}
    assert "L1" in catalog_logins


def test_build_kitvending_client_passes_company_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, child = _head_and_child_accounts()
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.load_kit_platform_accounts",
        lambda _path: [head, child],
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.integrations.accounts_file_is_valid",
        lambda _path: True,
    )
    settings = KitVendingSettings.model_construct(
        api_base_url="https://api2.kit-invest.ru/APIService.svc",
        accounts_path=__import__("pathlib").Path("ignored.json"),
        ingestion_enabled=True,
    )
    client = build_kitvending_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
        company_store=_seed_company_store(),
        http_client=httpx.Client(),
    )
    assert isinstance(client, KitVendingHttpClient)
    assert client.company_directory is not None


def test_wire_settlement_passes_company_store_to_build_kitvending_client() -> None:
    from src.infrastructure.composition.wiring import wire_settlement as wire_mod

    source = inspect.getsource(wire_mod.wire_settlement)
    assert "build_company_store" in source
    assert "company_store=company_store" in source


def test_auto_reconcile_passes_company_store_to_build_kitvending_client() -> None:
    from src.infrastructure.composition.factories import auto_reconcile

    source = inspect.getsource(auto_reconcile.build_settlement_portion_handlers)
    assert "build_company_store" in source
    assert "company_store=company_store" in source


def test_wire_matrix_worker_passes_company_store_to_build_matrix_deployer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.infrastructure.composition.matrix_worker_wiring.fakes import (
        _enabled_settings,
        _mongo_persistence,
        _stub_enabled_worker_dependencies,
    )

    from src.application.master_data.companies_memory import InMemoryCompanyStore
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    seeded_store = InMemoryCompanyStore()
    captured: dict[str, object] = {}
    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    _stub_enabled_worker_dependencies(monkeypatch)
    monkeypatch.setattr(
        wire_mod,
        "build_company_store",
        lambda settings, **kwargs: seeded_store,
    )

    def fake_deployer(settings: object, **kwargs: object) -> object:
        captured["company_store"] = kwargs.get("company_store")
        from tests.infrastructure.composition.matrix_worker_wiring.fakes import _FakeDeployer

        return _FakeDeployer()

    monkeypatch.setattr(wire_mod, "build_matrix_deployer", fake_deployer)

    container = wire_mod.wire_matrix_worker(
        settings,
        persistence=_mongo_persistence(),
    )

    assert container.runtime.enabled is True
    assert captured["company_store"] is seeded_store


def test_build_matrix_deploy_job_bundle_passes_company_store_to_deployer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.infrastructure.composition.matrix_worker_wiring.fakes import (
        _enabled_settings,
        _FakeStatusRepository,
        _persistence_with_mongo,
        _stub_enabled_worker_dependencies,
    )

    from src.application.master_data.companies_memory import InMemoryCompanyStore
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod
    from src.infrastructure.integrations.kitvending.request_id_store import (
        InMemoryKitVendingRequestIdStore,
    )

    seeded_store = InMemoryCompanyStore()
    captured: dict[str, object] = {}
    settings = _enabled_settings(tmp_path, mongo_uri="mongodb://127.0.0.1:1")
    _stub_enabled_worker_dependencies(monkeypatch)
    monkeypatch.setattr(
        wire_mod,
        "build_company_store",
        lambda settings, **kwargs: seeded_store,
    )

    def fake_deployer(settings: object, **kwargs: object) -> object:
        captured["company_store"] = kwargs.get("company_store")
        from tests.infrastructure.composition.matrix_worker_wiring.fakes import _FakeDeployer

        return _FakeDeployer()

    monkeypatch.setattr(wire_mod, "build_matrix_deployer", fake_deployer)

    wire_mod.build_matrix_deploy_job_bundle(
        settings,
        persistence=_persistence_with_mongo(),
        request_id_store=InMemoryKitVendingRequestIdStore(),
        stock_provider=None,
        seed_only=False,
        trigger="cron",
        status_repository=_FakeStatusRepository(),
    )

    assert captured["company_store"] is seeded_store
