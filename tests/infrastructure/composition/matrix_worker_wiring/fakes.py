from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from src.application.matrix_automation.models import (
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
)
from src.application.matrix_automation.provider import MatrixReferenceDataProvider
from src.config.google_forms import GoogleFormsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.service_calendar import ServiceCalendarSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle


def _google_forms() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("dev-webhook-secret"),
        revision_form_token_secret=SecretStr("dev-revision-secret"),
        loading_form_token_secret=SecretStr("dev-loading-secret"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "dev-warehouse-inventory-secret",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _enabled_settings(tmp_path: Path, *, mongo_uri: str | None = None) -> Settings:
    accounts = tmp_path / "kit_platform_accounts.json"
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    write_platform_accounts_file(accounts, platform_account_row(company_id=1, kit_company_id=1))
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=42,
        ),
        google_forms=_google_forms(),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("ms-token"),
            main_store_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts),
        mongodb=MongoSettings.model_construct(uri=mongo_uri),
        service_calendar=ServiceCalendarSettings.model_construct(
            display_timezone="Europe/Moscow",
        ),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=True,
            worker_cron_hour=3,
            google_sheets_spreadsheet_id="sheet-id",
            product_multipliers_sheet_id=3,
        ),
    )


def _mongo_persistence() -> PersistenceBundle:
    from pymongo import MongoClient

    mongo_client: MongoClient[dict[str, Any]] = MongoClient(
        "mongodb://127.0.0.1:1",
        serverSelectionTimeoutMS=1,
    )
    return PersistenceBundle(mongo_client=mongo_client, redis_client=None)


def _stub_enabled_worker_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infrastructure.composition.wiring import wire_matrix_worker as wire_mod

    monkeypatch.setattr(wire_mod, "build_matrix_catalog_reader", lambda settings: object())
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_reference_sync",
        lambda settings, **kwargs: _FakeSync(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_deployer",
        lambda settings, **kwargs: _FakeDeployer(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_purchase_attributes_reader",
        lambda settings: (_FakePurchaseReader(), lambda: None),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_provider_backed_run_build",
        lambda settings, **kwargs: _FakeBuild(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_reference_data_snapshot_store",
        lambda settings, **kwargs: object(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_snapshot_store",
        lambda settings, **kwargs: _FakeSnapshotStore(),
    )
    monkeypatch.setattr(
        wire_mod,
        "build_matrix_reference_data_provider",
        lambda matrix: object(),
    )
    monkeypatch.setattr(
        wire_mod.MongoMatrixDeployJobRepository,
        "from_settings",
        classmethod(lambda cls, settings, *, client=None: _FakeJobRepository()),
    )
    monkeypatch.setattr(
        wire_mod.MongoMatrixWorkerStatusRepository,
        "from_settings",
        classmethod(lambda cls, settings, *, client=None: _FakeStatusRepository()),
    )
    from tests.infrastructure.kitvending.platform_account_helpers import (
        seed_matching_company_store,
    )

    from src.application.master_data.companies_memory import InMemoryCompanyStore

    def _company_store(_settings: object, **kwargs: object) -> InMemoryCompanyStore:
        del kwargs
        store = InMemoryCompanyStore()
        seed_matching_company_store(store, company_id=1, kit_company_id=1)
        return store

    monkeypatch.setattr(wire_mod, "build_company_store", _company_store)


def patch_company_store_for_matrix_worker(
    monkeypatch: pytest.MonkeyPatch,
    wire_mod: object,
) -> None:
    from tests.infrastructure.kitvending.platform_account_helpers import (
        seed_matching_company_store,
    )

    from src.application.master_data.companies_memory import InMemoryCompanyStore

    def _company_store(_settings: object, **kwargs: object) -> InMemoryCompanyStore:
        del kwargs
        store = InMemoryCompanyStore()
        seed_matching_company_store(store, company_id=1, kit_company_id=1)
        return store

    monkeypatch.setattr(wire_mod, "build_company_store", _company_store)


class _StockProvider:
    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        return 0


def _FakeReferenceProvider() -> MatrixReferenceDataProvider:
    return MatrixReferenceDataProvider(
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )


class _FakeSnapshotStore:
    def has_unit_snapshot(self, *, machine_code: str, logical_matrix_name: str) -> bool:
        return False

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: object) -> None:
        return None


class _FakeSync:
    def sync(self) -> object:
        raise AssertionError("sync should not run during assemble")


class _FakeDeployer:
    def deploy(self, payloads: list[object]) -> list[object]:
        return []


class _FakePurchaseReader:
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        return PurchaseAttributesFetchResult(attributes={}, cards_found=0)


class _FakeBuild:
    def __call__(self, state: object) -> object:
        raise AssertionError("build should not run during assemble")


class _FakeJobRepository:
    def insert(self, job: object) -> None:
        return None

    def finalize(self, job: object) -> None:
        return None


class _FakeStatusRepository:
    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        return None

    def record_terminal_job(self, job: object) -> None:
        return None


def _persistence_with_mongo() -> PersistenceBundle:
    return _mongo_persistence()
