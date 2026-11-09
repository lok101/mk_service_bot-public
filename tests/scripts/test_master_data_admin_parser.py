from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from scripts.master_data_admin import build_parser, main

from src.application.master_data import InMemoryMasterDataStores, InMemoryTechnicianStore
from src.config.mongodb import MongoSettings
from src.config.settings import Settings


def test_import_cli_parser_has_import_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["import"])
    assert args.command == "import"


def test_parser_accepts_import_users_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["import-users"])
    assert args.command == "import-users"


def test_parser_accepts_reconcile_location_ids_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "reconcile-location-ids",
            "locations.csv",
            "--allow-extra-domain",
            "--accept-name-mismatch",
        ],
    )
    assert args.command == "reconcile-location-ids"
    assert args.csv_path.name == "locations.csv"
    assert args.allow_extra_domain is True
    assert args.accept_name_mismatch is True
    assert args.apply is False


def test_run_import_users_noop_when_store_not_empty() -> None:
    from datetime import UTC, datetime

    from scripts.master_data_admin import _run_import_users

    from src.application.master_data import InMemorySystemUserStore, SystemUserRecord
    from src.application.sheets.bot_users import SystemUsersSnapshot
    from src.domain.system_user import BotRole, CompanyRole, SystemUser, SystemUserId

    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    store = InMemorySystemUserStore()
    store.replace_all(
        (
            SystemUserRecord(
                user=SystemUser(
                    user_id=SystemUserId("9"),
                    name="Keep",
                    role=BotRole.NONE,
                    is_active=True,
                    telegram_user_id=9,
                    technician_id=None,
                    company_roles=frozenset({CompanyRole.ACCESS_ADMINISTRATOR}),
                ),
                updated_at=now,
                updated_by_telegram_user_id=0,
            ),
        )
    )
    snapshot = SystemUsersSnapshot(users_by_telegram_id={}, users_by_technician_id={})
    assert _run_import_users(store=store, snapshot=snapshot, now=now) == 0
    assert store.get(9) is not None


def test_run_import_users_writes_empty_company_roles_from_snapshot() -> None:
    from datetime import UTC, datetime

    from scripts.master_data_admin import _run_import_users

    from src.application.master_data import InMemorySystemUserStore
    from src.application.sheets.bot_users import SystemUsersSnapshot
    from src.domain.system_user import BotRole, SystemUser, SystemUserId

    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    store = InMemorySystemUserStore()
    admin = SystemUser(
        user_id=SystemUserId("1"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=1001,
        technician_id=None,
        company_roles=frozenset(),
    )
    snapshot = SystemUsersSnapshot(
        users_by_telegram_id={1001: admin},
        users_by_technician_id={},
    )
    assert _run_import_users(store=store, snapshot=snapshot, now=now) == 0
    loaded = store.get(1001)
    assert loaded is not None
    assert loaded.user.company_roles == frozenset()
    assert loaded.user.panels == frozenset()


def test_import_cli_uses_build_master_data_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory decides memory vs Mongo; CLI must not hardcode InMemory persist-path."""
    calls: list[object] = []

    def _stub_required_app_env() -> None:
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
        monkeypatch.delenv("MONGODB_URI", raising=False)
        monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)

    _stub_required_app_env()
    settings = Settings(mongodb=MongoSettings.model_construct(uri=None))
    monkeypatch.setattr("scripts.master_data_admin.get_settings", lambda: settings)

    stores = InMemoryMasterDataStores()

    def fake_build(
        settings_arg: Settings,
        *,
        mongo_client: object = None,
    ) -> InMemoryMasterDataStores:
        calls.append(mongo_client)
        return stores

    monkeypatch.setattr(
        "scripts.master_data_admin.build_master_data_stores",
        fake_build,
    )
    monkeypatch.setattr(
        "scripts.master_data_admin.build_reference_data_snapshot_store",
        lambda settings_arg, client=None: MagicMock(),
    )

    def fake_run_import(*, snapshot_store: object, master_stores: object) -> int:
        assert master_stores is stores
        return 0

    monkeypatch.setattr("scripts.master_data_admin._run_import", fake_run_import)
    assert main(["import"]) == 0
    assert len(calls) == 1


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
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_import_technicians_cli_fails_closed_when_mongo_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI must not persist technicians in a throwaway InMemory store when Mongo URI is set."""
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    settings = Settings()
    assert settings.mongodb.is_configured is True
    fake_client = MagicMock()
    factory_store = InMemoryTechnicianStore()
    factory_calls: list[object] = []
    monkeypatch.setattr("scripts.master_data_admin.get_settings", lambda: settings)
    monkeypatch.setattr(
        "scripts.master_data_admin.build_mongo_client",
        lambda settings_arg: fake_client,
    )
    monkeypatch.setattr(
        "scripts.master_data_admin.build_reference_data_snapshot_store",
        lambda settings_arg, client=None: MagicMock(),
    )
    monkeypatch.setattr(
        "scripts.master_data_admin._rows_from_store",
        lambda store, source_id: [["Id", "Имя"], ["10003", "Данил"]],
    )
    monkeypatch.setattr(
        "scripts.master_data_admin.build_technicians_directory_snapshot",
        lambda rows: MagicMock(),
    )
    monkeypatch.setattr(
        "scripts.master_data_admin.build_master_data_stores",
        lambda settings_arg, mongo_client=None: InMemoryMasterDataStores(),
    )

    def fake_build_technician_store(
        settings_arg: Settings,
        *,
        mongo_client: object = None,
    ) -> InMemoryTechnicianStore:
        factory_calls.append(mongo_client)
        return factory_store

    monkeypatch.setattr(
        "scripts.master_data_admin.build_technician_store",
        fake_build_technician_store,
    )

    def fake_run_import_technicians(
        *,
        store: object,
        counters: object,
        snapshot: object,
    ) -> int:
        assert store is factory_store
        return 0

    monkeypatch.setattr(
        "scripts.master_data_admin._run_import_technicians",
        fake_run_import_technicians,
    )

    assert main(["import-technicians"]) == 0
    assert factory_calls == [fake_client]
