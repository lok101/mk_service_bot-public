from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import mongomock
import pytest
from pydantic import SecretStr
from tests.infrastructure.composition.test_assemble_app_container import (
    _dev_settings_without_mongo,
)
from tests.infrastructure.composition_helpers import _StubVendingMachineRepository

from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.config.kitshop import KitShopSettings
from src.config.kitvending import KitVendingSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.settlement import SettlementBundle
from src.infrastructure.composition.factories import persistence as persistence_factories
from src.infrastructure.composition.factories import settlement as settlement_factories
from src.infrastructure.composition.wiring import wire_settlement as wire_settlement_mod
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.matrix_automation.mongo_snapshots import MongoMatrixPriceSnapshotStore
from src.infrastructure.memory import InMemoryEventStore
from src.infrastructure.mongodb.coffee_recipes import MongoCoffeeRecipeRepository
from src.infrastructure.mongodb.external_side_effects import MongoExternalSideEffectRegistry
from src.infrastructure.mongodb.kitshop_sale_receipts import MongoKitShopSaleReceiptStore
from src.infrastructure.mongodb.kitshop_sales_backlog import MongoKitShopSalesBacklogStore
from src.infrastructure.mongodb.kitshop_sales_ingest_cursors import (
    MongoKitShopSalesIngestCursorStore,
)
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.mongodb.machine_sales_skipped import MongoMachineSaleSkipStore
from src.infrastructure.mongodb.responsibility_period_reconciliations import (
    MongoPeriodReconciliationRepository,
)
from src.infrastructure.mongodb.technician_settlement import (
    MongoTechnicianSettlementEventStore,
)
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    StaticMachineKindLookup,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore
from src.infrastructure.testing.snack_loading_fakes import (
    InMemoryKitMatrixDeployMapStore,
    InMemorySnackMachineStockStore,
)


def test_kitshop_ingest_disabled_settlement_bundle_worker_none() -> None:
    settings = KitShopSettings(ingestion_enabled=False)
    worker = None
    if settings.ingestion_enabled:
        worker = object()
    bundle = SettlementBundle(
        sales_ingest_worker=None,
        kitshop_sales_ingest_worker=worker,  # type: ignore[arg-type]
        kitvending_client=object(),
        company_occupancy_store=InMemoryMachineCompanyOccupancyStore(),
    )
    assert bundle.kitshop_sales_ingest_worker is None


def _write_kit_shop_accounts(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": "a",
                    "company_id": 1,
                    "kit_company_id": 10,
                    "platform": "kit_shop",
                    "role": "default",
                    "login": "u1",
                    "password": "p1",
                },
            ]
        ),
        encoding="utf-8",
    )


def _unwrap_beartype(fn: Callable[..., Any]) -> Callable[..., Any]:
    return getattr(fn, "__wrapped__", fn)


def _unwrap_classmethod(method: classmethod) -> classmethod:  # type: ignore[type-arg]
    return classmethod(_unwrap_beartype(method.__func__))


def _patch_mongomock_beartype(monkeypatch: pytest.MonkeyPatch) -> None:
    # beartype на wire_settlement/factories типизирует mongo_client как pymongo.MongoClient;
    # mongomock (план) проходит только без runtime-check на этой цепочке.
    monkeypatch.setattr(
        wire_settlement_mod,
        "wire_settlement",
        _unwrap_beartype(wire_settlement_mod.wire_settlement),
    )
    for name in (
        "build_machine_sales_store",
        "build_coffee_recipe_repository",
        "build_period_reconciliation_repository",
        "build_technician_settlement_repository",
        "build_machine_sale_skip_store",
        "build_apply_snack_sale",
        "build_refresh_pending_with_accountability",
        "build_kitvending_request_id_store",
        "build_company_store",
    ):
        monkeypatch.setattr(
            wire_settlement_mod,
            name,
            _unwrap_beartype(getattr(wire_settlement_mod, name)),
        )
    for name, module in (
        ("build_matrix_snapshot_store", persistence_factories),
        ("build_matrix_snapshot_store", settlement_factories),
        ("build_apply_snack_sale", settlement_factories),
        ("build_coffee_recipe_repository", settlement_factories),
        ("build_period_reconciliation_repository", settlement_factories),
        ("build_technician_settlement_repository", settlement_factories),
        ("build_machine_sale_skip_store", settlement_factories),
        ("build_machine_sales_store", settlement_factories),
        ("build_external_side_effect_registry", persistence_factories),
        ("build_refresh_pending_with_accountability", settlement_factories),
    ):
        monkeypatch.setattr(module, name, _unwrap_beartype(getattr(module, name)))
    for cls in (
        MongoMachineSalesStore,
        MongoCoffeeRecipeRepository,
        MongoPeriodReconciliationRepository,
        MongoExternalSideEffectRegistry,
        MongoTechnicianSettlementEventStore,
        MongoMachineSaleSkipStore,
        MongoKitShopSalesBacklogStore,
        MongoKitShopSalesIngestCursorStore,
        MongoKitShopSaleReceiptStore,
        MongoMatrixPriceSnapshotStore,
    ):
        monkeypatch.setattr(
            cls, "from_settings", _unwrap_classmethod(cls.__dict__["from_settings"])
        )
        if "from_collection" in cls.__dict__:
            monkeypatch.setattr(
                cls,
                "from_collection",
                _unwrap_classmethod(cls.__dict__["from_collection"]),
            )


def _kitshop_ingest_wire_deps(
    tmp_path: Path,
    *,
    alert_chat_id: int | None,
) -> tuple[Settings, mongomock.MongoClient, dict[str, Any]]:
    accounts_path = tmp_path / "accounts.json"
    _write_kit_shop_accounts(accounts_path)
    settings = _dev_settings_without_mongo().model_copy(
        update={
            "telegram": TelegramSettings.model_construct(
                bot_token=SecretStr("dev-bot-token-16chars"),
                webhook_public_host="",
                alert_chat_id=alert_chat_id,
            ),
            "kitshop": KitShopSettings.model_construct(
                ingestion_enabled=True,
                accounts_path=accounts_path,
                api_base_url="https://api.kitshop.ru/APIService.svc",
                requests_per_window=1,
                window_seconds=6.0,
                backoff_seconds=60.0,
                reference_refresh_interval_seconds=3600,
                discovery_interval_seconds=900,
                drain_interval_seconds=6,
                ingest_overlap_seconds=1800,
                initial_lookback_days=7,
                sale_alert_cooldown_minutes=60,
            ),
            "kitvending": KitVendingSettings.model_construct(
                ingestion_enabled=False,
                accounts_path=tmp_path / "missing_vending.json",
            ),
            "mongodb": MongoSettings.model_construct(
                uri="mongodb://localhost:27017",
                database="mk_service_bot",
            ),
        },
    )
    mongo_client = mongomock.MongoClient()
    stock = InMemoryMicromarketDeviceStockStore()
    apply_micromarket_sale = ApplyMicromarketSaleToStock(
        stock_store=stock,
        machine_kind_lookup=StaticMachineKindLookup({}),
    )
    from tests.application.product_identity.fakes import FakeDomainProductStore

    deps: dict[str, Any] = {
        "event_store": InMemoryEventStore(),
        "form_submission_store": InMemoryFormSubmissionStore(),
        "vending_machines": _StubVendingMachineRepository(),
        "domain_product_store": FakeDomainProductStore(),
        "occupancy_store": InMemoryMachineCompanyOccupancyStore(),
        "apply_micromarket_sale": apply_micromarket_sale,
        "machine_sales_store": InMemoryMachineSalesStore(),
        "snack_stock_store": InMemorySnackMachineStockStore(),
        "kit_matrix_deploy_map": InMemoryKitMatrixDeployMapStore(),
    }
    return settings, mongo_client, deps


def test_kitshop_wire_uses_kitshop_alert_notifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: реальный wire_settlement, Kit Shop notifier на drain и worker
    _patch_mongomock_beartype(monkeypatch)
    settings, mongo_client, deps = _kitshop_ingest_wire_deps(
        tmp_path,
        alert_chat_id=-100123,
    )
    wiring = wire_settlement_mod.wire_settlement(
        settings,
        mongo_client=mongo_client,
        **deps,
    )
    worker = wiring.bundle.kitshop_sales_ingest_worker
    assert worker is not None
    from src.infrastructure.alerting.kitshop_sale_alert_notifier import (
        TelegramKitShopSaleAlertNotifier,
    )

    assert isinstance(worker.drain.unresolved_alert_notifier, TelegramKitShopSaleAlertNotifier)
    assert isinstance(worker.alert_notifier, TelegramKitShopSaleAlertNotifier)
    assert worker.drain.unresolved_alert_notifier is worker.alert_notifier
    assert worker.drain.occupancy_store is deps["occupancy_store"]


def test_kitshop_wire_passes_after_occupancy_rebuild_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mongomock_beartype(monkeypatch)
    settings, mongo_client, deps = _kitshop_ingest_wire_deps(
        tmp_path,
        alert_chat_id=None,
    )
    calls: list[int] = []

    def _hook() -> None:
        calls.append(1)

    wiring = wire_settlement_mod.wire_settlement(
        settings,
        mongo_client=mongo_client,
        after_occupancy_rebuild=_hook,
        **deps,
    )
    worker = wiring.bundle.kitshop_sales_ingest_worker
    assert worker is not None
    assert worker.drain.after_occupancy_rebuild is _hook
    assert calls == []


def test_kitshop_wire_settlement_unresolved_notifier_noop_without_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # edge: нет alert_chat_id → NoOp Kit Shop
    _patch_mongomock_beartype(monkeypatch)
    settings, mongo_client, deps = _kitshop_ingest_wire_deps(
        tmp_path,
        alert_chat_id=None,
    )
    wiring = wire_settlement_mod.wire_settlement(
        settings,
        mongo_client=mongo_client,
        **deps,
    )
    worker = wiring.bundle.kitshop_sales_ingest_worker
    assert worker is not None
    from src.application.inventory_reconciliation.drain_kitshop_sales import (
        NoOpKitShopSaleAlertNotifier,
    )

    assert isinstance(
        worker.drain.unresolved_alert_notifier,
        NoOpKitShopSaleAlertNotifier,
    )
    assert isinstance(worker.alert_notifier, NoOpKitShopSaleAlertNotifier)


def test_kitshop_wire_gateway_catalog_ensure_default_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mongomock_beartype(monkeypatch)
    settings, mongo_client, deps = _kitshop_ingest_wire_deps(
        tmp_path,
        alert_chat_id=None,
    )
    # ingestion on в хелпере не мешает: gateway создаётся при HttpClient
    wiring = wire_settlement_mod.wire_settlement(
        settings,
        mongo_client=mongo_client,
        **deps,
    )
    gateway = wiring.micromarket_shop_list_gateway
    assert gateway is not None
    assert gateway._catalog_ensure_enabled is False


def test_kitshop_wire_gateway_catalog_ensure_passes_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mongomock_beartype(monkeypatch)
    settings, mongo_client, deps = _kitshop_ingest_wire_deps(
        tmp_path,
        alert_chat_id=None,
    )
    settings = settings.model_copy(
        update={
            "kitshop": settings.kitshop.model_copy(
                update={"catalog_ensure_on_publish_enabled": True},
            ),
        },
    )
    wiring = wire_settlement_mod.wire_settlement(
        settings,
        mongo_client=mongo_client,
        **deps,
    )
    gateway = wiring.micromarket_shop_list_gateway
    assert gateway is not None
    assert gateway._catalog_ensure_enabled is True
