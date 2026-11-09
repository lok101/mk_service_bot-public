from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from src.application.matrix_automation.job_models import MatrixDeployJob, MatrixDeployJobUnit
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.wiring.wire_matrix_worker import (
    NoOpMatrixWorkerStatusRepository,
)


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


def _settings_with_mongo(tmp_path: Path | None = None) -> Settings:
    base = tmp_path or Path(".")
    accounts = base / "kit_platform_accounts.json"
    credentials = base / "credentials.json"
    if tmp_path is not None:
        from tests.infrastructure.kitvending.platform_account_helpers import (
            platform_account_row,
            write_platform_accounts_file,
        )

        write_platform_accounts_file(
            accounts,
            platform_account_row(company_id=1, kit_company_id=1, login="u", password="p"),
        )
        credentials.write_text("{}", encoding="utf-8")
    return Settings.model_construct(
        environment="dev",
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=42,
        ),
        google_forms=_google_forms(),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file=str(credentials),
        ),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("ms-token"),
            main_store_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts),
        mongodb=MongoSettings.model_construct(uri="mongodb://localhost:27017"),
        matrix_automation=MatrixAutomationSettings.model_construct(
            worker_enabled=False,
            google_sheets_spreadsheet_id="sheet-id",
            product_multipliers_sheet_id=3,
        ),
    )


def _terminal_job(*, status: str, trigger: str = "seed") -> MatrixDeployJob:
    return MatrixDeployJob.started(
        job_id="job-1",
        started_at="2026-07-14T00:00:00Z",
        trigger=trigger,  # type: ignore[arg-type]
    ).finalize(
        status=status,  # type: ignore[arg-type]
        finished_at="2026-07-14T00:01:00Z",
        units=(),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )


def test_matrix_admin_parser_has_import_layouts() -> None:
    from scripts.matrix_admin import build_parser

    parser = build_parser()
    args = parser.parse_args(["import-layouts"])
    assert args.command == "import-layouts"


def test_matrix_admin_parser_has_import_sku_catalog() -> None:
    from scripts.matrix_admin import build_parser

    parser = build_parser()
    args = parser.parse_args(["import-sku-catalog"])
    assert args.command == "import-sku-catalog"


def test_seed_stdout_format_and_exit_completed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """happy: completed → exit 0; одна строка key=value."""
    from scripts import matrix_admin

    job = MatrixDeployJob.started(
        job_id="abc",
        started_at="2026-07-14T00:00:00Z",
        trigger="seed",
    ).finalize(
        status="completed",
        finished_at="2026-07-14T00:01:00Z",
        units=(
            MatrixDeployJobUnit(
                logical_matrix_name="S",
                machine_code="1",
                deploy_status="applied",
                deploy_reason=None,
                sku_stats=None,
                strong_price_increase_lines=(),
                product_swap_blocked_lines=(),
            ),
        ),
        blocked_matrices=(),
        auto_sync_disabled_matrices=0,
    )
    monkeypatch.setattr(matrix_admin, "_run_seed_job", lambda: job)
    monkeypatch.setattr(matrix_admin, "_ensure_ready", lambda: None)
    code = matrix_admin.main(["seed"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out == (
        "matrix_admin seed: job_id=abc trigger=seed status=completed applied=1 failed=0 skipped=0"
    )


def test_seed_exit_nonzero_on_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """error: partial → exit != 0."""
    from scripts import matrix_admin

    job = _terminal_job(status="partial", trigger="seed")
    monkeypatch.setattr(matrix_admin, "_run_seed_job", lambda: job)
    monkeypatch.setattr(matrix_admin, "_ensure_ready", lambda: None)
    assert matrix_admin.main(["seed"]) != 0


def test_seed_exit_nonzero_on_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """error: failed → exit != 0."""
    from scripts import matrix_admin

    job = _terminal_job(status="failed", trigger="seed")
    monkeypatch.setattr(matrix_admin, "_run_seed_job", lambda: job)
    monkeypatch.setattr(matrix_admin, "_ensure_ready", lambda: None)
    assert matrix_admin.main(["seed"]) != 0


def test_seed_exit_zero_on_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """edge: skipped (все baseline) → exit 0."""
    from scripts import matrix_admin

    job = _terminal_job(status="skipped", trigger="seed")
    monkeypatch.setattr(matrix_admin, "_run_seed_job", lambda: job)
    monkeypatch.setattr(matrix_admin, "_ensure_ready", lambda: None)
    assert matrix_admin.main(["seed"]) == 0


def _settings_without_mongo(tmp_path: Path) -> Settings:
    settings = _settings_with_mongo(tmp_path)
    return Settings.model_construct(
        environment=settings.environment,
        telegram=settings.telegram,
        google_forms=settings.google_forms,
        moysklad=settings.moysklad,
        kitvending=settings.kitvending,
        matrix_automation=settings.matrix_automation,
        mongodb=MongoSettings.model_construct(uri=None),
    )


def test_seed_refuses_without_mongo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """error: нет MONGODB_URI → exit != 0, сообщение must be set."""
    from scripts import matrix_admin

    monkeypatch.setattr(
        matrix_admin,
        "get_settings",
        lambda: _settings_without_mongo(tmp_path),
    )
    code = matrix_admin.main(["seed"])
    err = capsys.readouterr().err
    assert code != 0
    assert "MONGODB_URI must be set" in err


def test_seed_refuses_when_substitution_guard_enabled_without_stock_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """error: guard on без stock provider → exit != 0 (как wire_matrix_worker)."""
    from scripts import matrix_admin

    settings = _settings_with_mongo(tmp_path)
    settings.matrix_automation.substitution_guard_enabled = True
    monkeypatch.setattr(matrix_admin, "get_settings", lambda: settings)
    code = matrix_admin.main(["seed"])
    err = capsys.readouterr().err
    assert code != 0
    assert "MatrixStockProvider required" in err


def test_seed_uses_noop_status_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """edge: _run_seed_job собирает bundle с NoOpMatrixWorkerStatusRepository."""
    from scripts import matrix_admin

    captured: list[object] = []
    request_id_store = object()

    def fake_bundle(*_args: object, **kwargs: object) -> object:
        captured.append(kwargs["status_repository"])
        assert kwargs["request_id_store"] is request_id_store
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(matrix_admin, "build_matrix_deploy_job_bundle", fake_bundle)
    monkeypatch.setattr(
        matrix_admin,
        "build_kitvending_request_id_store",
        lambda settings, **kwargs: request_id_store,
    )
    monkeypatch.setattr(matrix_admin, "validate_matrix_seed_settings", lambda _s: None)
    monkeypatch.setattr(
        matrix_admin,
        "_build_persistence",
        lambda _s: PersistenceBundle(mongo_client=None, redis_client=None),
    )
    monkeypatch.setattr(
        matrix_admin,
        "get_settings",
        lambda: _settings_with_mongo(tmp_path),
    )
    code = matrix_admin.main(["seed"])
    assert code != 0
    assert isinstance(captured[0], NoOpMatrixWorkerStatusRepository)
