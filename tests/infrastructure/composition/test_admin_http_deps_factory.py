from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.location_roster import LocationRosterSettings
from src.config.master_data import MasterDataSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.settlement_analysis import SettlementAnalysisSettings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.factories.admin_http_deps import build_admin_http_deps
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.assemble import assemble_app_container

_SESSION_SECRET = SecretStr("admin-session-secret-long-enough")


def _settings_with_master_data_flags() -> Settings:
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("dev-bot-token-16chars"),
            webhook_public_host="",
        ),
        google_forms=GoogleFormsSettings.model_construct(
            webhook_secret=SecretStr("dev-webhook-secret"),
            revision_form_token_secret=SecretStr("dev-revision-form-token-secret"),
            loading_form_token_secret=SecretStr("dev-loading-form-token-secret"),
            revision_form_url="https://forms.example/revision",
            loading_form_url="https://forms.example/loading",
            revision_form_token_entry_id="entry.1",
            loading_form_token_entry_id="entry.2",
            technician_warehouse_inventory_form_url="https://forms.example/warehouse",
            technician_warehouse_inventory_form_token_secret=SecretStr(
                "dev-warehouse-inventory-form-token-secret",
            ),
            technician_warehouse_inventory_form_token_entry_id="entry.3",
            token_field_name="token",
        ),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file="credentials.json",
            product_catalog_spreadsheet_id="catalog-spreadsheet",
            product_catalog_sheet_id=1,
            coffee_technician_locations_spreadsheet_id="locations-spreadsheet",
            coffee_technician_locations_sheet_id=2,
            users_sheet_id=3,
        ),
        mongodb=MongoSettings.model_construct(uri=None),
        master_data=MasterDataSettings.model_construct(
            enabled=True,
            users_enabled=True,
            session_secret=_SESSION_SECRET,
            telegram_bot_username="testbot",
        ),
        location_roster=LocationRosterSettings.model_construct(
            enabled=True,
            session_secret=_SESSION_SECRET,
            telegram_bot_username="testbot",
        ),
        matrix_automation=MatrixAutomationSettings.model_construct(
            sku_catalog_master_enabled=True,
            sku_catalog_ms_product_folder_ids=(UUID("11111111-1111-1111-1111-111111111111"),),
        ),
        settlement_analysis=SettlementAnalysisSettings.model_construct(
            enabled=True,
            session_secret=_SESSION_SECRET,
            telegram_bot_username="testbot",
        ),
    )


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def _runtime_from_container(container: object) -> ProcessRuntime:
    from src.infrastructure.composition.container import AppContainer

    assert isinstance(container, AppContainer)
    return ProcessRuntime(
        config=container.config,
        persistence=container.persistence,
        machine_ops=container.machine_ops,
        forms=container.forms,
        outbox=container.outbox,
        photos=container.photos,
        settlement=container.settlement,
        reference_data=container.reference_data,
        technician_warehouse=container.technician_warehouse,
        telegram=container.telegram,
        kitshop_client=container.kitshop_client,
        micromarket_planogram_store=container.micromarket_planogram_store,
    )


def _minimal_runtime_with_master_data(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProcessRuntime, Settings]:
    """Settings через model_construct; ProcessRuntime из in-memory assemble без Mongo."""
    _stub_required_app_env(monkeypatch)
    settings = _settings_with_master_data_flags()
    container = assemble_app_container(settings)
    return _runtime_from_container(container), settings


def _minimal_runtime_roster_only(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProcessRuntime, Settings]:
    """MASTER_DATA_ENABLED=false, roster on; master_data_stores не попадает в deps."""
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MASTER_DATA_ENABLED", "false")
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_USERS_ENABLED", "false")
    monkeypatch.setenv("MASTER_DATA_TECHNICIANS_ENABLED", "false")
    monkeypatch.setenv("SETTLEMENT_ANALYSIS_ADMIN_ENABLED", "false")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "roster-session-secret-long")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "testbot")
    settings = Settings()
    container = assemble_app_container(settings)
    return _runtime_from_container(container), settings


def test_build_admin_http_deps_factory_produces_complete_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    deps = build_admin_http_deps(runtime, settings)
    assert deps.provider is runtime.reference_data.provider
    assert deps.roster_store is runtime.reference_data.roster_store
    assert deps.master_stores is runtime.reference_data.master_data_stores
    assert deps.build_visit_board is not None
    assert deps.system_user_store is not None
    assert deps.save_field_staff is not None
    assert deps.settlement_analysis_enabled is True
    assert deps.build_settlement_analysis_tree is not None
    assert deps.admin_nav_structure_store is not None
    assert deps.sku_catalog_master_enabled is True
    assert deps.matrix_sku_catalog_store is not None
    assert deps.review_label_lookup is None


def test_build_admin_http_deps_wires_review_label_lookup_when_visit_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from tests.application.visit_photo_review.fakes import (
        FixedBatches,
        FixedCatalog,
        FixedClock,
        MemoryReviewStore,
    )

    from src.application.visit_photo_review import (
        ClearReviewRecord,
        ReviewQueries,
        SaveReviewRecord,
    )
    from src.application.visit_photo_review.ports import ReviewLabels
    from src.config.visit_photo_review import VisitPhotoReviewSettings
    from src.domain.visit_photo_review import CatalogGroup, ReviewCatalog
    from src.infrastructure.composition.adapters.visit_photo_review_labels import (
        VendingMachineReviewLabelLookup,
    )

    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    settings = settings.model_copy(
        update={
            "visit_photo_review": VisitPhotoReviewSettings.model_construct(
                enabled=True,
                catalog_path="ignored.json",
                collection="visit_photo_reviews",
                session_secret=_SESSION_SECRET,
                telegram_bot_username="testbot",
            ),
        },
    )
    catalog = FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id="waste_tank",
                    title="Бак",
                    required=True,
                    defects=(),
                ),
            ),
        ),
    )
    store = MemoryReviewStore()
    batches = FixedBatches(None)
    clock = FixedClock(datetime(2026, 10, 14, tzinfo=UTC))

    class _FakeVisitDeps:
        review_queries = ReviewQueries(catalog, store, batches)
        save_review_record = SaveReviewRecord(catalog=catalog, store=store, clock=clock.now)
        clear_review_record = ClearReviewRecord(store=store)
        dispose_unrecognized_index = None
        group_avatar_reader = None
        update_group_defects = None
        write_group_avatar = None

    monkeypatch.setattr(
        "src.infrastructure.composition.factories.admin_http_deps.build_visit_photo_review_deps",
        lambda *_args, **_kwargs: _FakeVisitDeps(),
    )
    deps = build_admin_http_deps(runtime, settings)
    assert deps.visit_photo_review_enabled is True
    assert isinstance(deps.review_label_lookup, VendingMachineReviewLabelLookup)
    labels = deps.review_label_lookup.labels_for("missing-m", "missing-t")
    assert isinstance(labels, ReviewLabels)
    assert labels.machine_name is None
    assert labels.location_name is None
    assert labels.technician_name is None


def test_build_admin_http_deps_roster_only_without_master_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, settings = _minimal_runtime_roster_only(monkeypatch)
    deps = build_admin_http_deps(runtime, settings)
    assert deps.master_stores is None
    assert deps.build_visit_board is None
    assert deps.session_secret
    assert deps.roster_store is runtime.reference_data.roster_store


def test_build_admin_http_deps_wires_micromarket_loading_cycle_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    deps = build_admin_http_deps(runtime, settings)
    assert (
        deps.micromarket_loading_cycle_store is runtime.machine_ops.micromarket_loading_cycle_store
    )
    assert deps.micromarket_loading_execute_enabled is settings.micromarket_loading.execute_enabled
    assert deps.micromarket_loading_move_gateway is None


def test_build_admin_http_deps_reuses_runtime_micromarket_planogram_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = _settings_with_master_data_flags()
    container = assemble_app_container(settings)
    deps = build_admin_http_deps(container._runtime, settings)
    assert container.micromarket_planogram_store is not None
    assert deps.micromarket_planogram_store is container._runtime.micromarket_planogram_store
    assert deps.micromarket_planogram_store is container.micromarket_planogram_store


def test_build_admin_http_deps_catalog_sync_follows_assembled_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from src.infrastructure.reference_data.product_catalog_ms_worker import (
        ProductCatalogMsSyncWorker,
    )

    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    deps = build_admin_http_deps(runtime, settings)
    assert deps.catalog_snapshot_store is runtime.reference_data.store
    assert deps.product_catalog_sync is None

    class _Runner:
        async def sync_once(self) -> None:
            return None

    holder = ProductCatalogMsSyncWorker(sync=_Runner(), interval_seconds=3600)
    runtime.reference_data = replace(
        runtime.reference_data,
        product_catalog_ms_worker=holder,
    )
    wired = build_admin_http_deps(runtime, settings)
    assert wired.product_catalog_sync == holder.sync.sync_once
    assert wired.catalog_snapshot_store is runtime.reference_data.store
