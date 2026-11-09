from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.mongodb import MongoSettings
from src.config.sales_monitoring import SalesMonitoringSettings
from src.config.settings import Settings, validate_sales_monitoring_worker_settings


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_defaults_worker_disabled_and_thresholds() -> None:
    s = SalesMonitoringSettings()
    assert s.worker_enabled is False
    assert s.tz == "Asia/Yekaterinburg"
    assert s.days_for_average == 28
    assert s.sales_drop_percent == 30
    assert s.last_sale_lookup_days == 28
    assert s.offline_ping_threshold_minutes == 25
    assert s.offline_poll_interval_minutes == 60
    assert s.offline_poll_from_hour == 8
    assert s.offline_poll_to_hour == 22
    assert s.excluded_machine_codes == ()
    assert s.report_compare_cron == "0 8 * * *"
    assert s.report_today_cron == "0 15 * * *"
    assert s.alert_telegram_bot_token is None


def test_baseline_settings_defaults() -> None:
    s = SalesMonitoringSettings()
    assert s.baseline_min_points == 4
    assert s.baseline_winsorize_min_points == 8
    assert s.baseline_winsorize_percent == 10


def test_no_sales_habitual_max_nonempty_default() -> None:
    s = SalesMonitoringSettings()
    assert s.no_sales_habitual_max_nonempty == 1


def test_no_sales_habitual_max_nonempty_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_NO_SALES_HABITUAL_MAX_NONEMPTY", "0")
    assert SalesMonitoringSettings().no_sales_habitual_max_nonempty == 0


def test_no_sales_habitual_max_nonempty_rejects_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_NO_SALES_HABITUAL_MAX_NONEMPTY", "-1")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_no_sales_stale_hours_defaults() -> None:
    """happy: defaults 24 / 60 / 45."""
    s = SalesMonitoringSettings()
    assert s.no_sales_stale_hours == 24
    assert s.no_sales_eval_interval_minutes == 60
    assert s.no_sales_ingest_cursor_max_lag_minutes == 45


@pytest.mark.parametrize(
    "env_name",
    [
        "SALES_MONITORING_NO_SALES_STALE_HOURS",
        "SALES_MONITORING_NO_SALES_EVAL_INTERVAL_MINUTES",
        "SALES_MONITORING_NO_SALES_INGEST_CURSOR_MAX_LAG_MINUTES",
    ],
)
def test_no_sales_stale_hours_rejects_below_one(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
) -> None:
    """error: ge=1."""
    monkeypatch.setenv(env_name, "0")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_incident_clear_pair_minutes_defaults() -> None:
    """happy: default окна пары = 30."""
    s = SalesMonitoringSettings()
    assert s.incident_clear_pair_minutes == 30


def test_incident_clear_pair_minutes_rejects_below_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: значение < 1 отклоняется."""
    monkeypatch.setenv("SALES_MONITORING_INCIDENT_CLEAR_PAIR_MINUTES", "0")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


@pytest.mark.parametrize(
    ("compare_raw", "today_raw"),
    [
        ('"0 8 * * *"', '"0 15 * * *"'),
        ("'0 8 * * *'", "'0 15 * * *'"),
        ("0 8 * * *", "0 15 * * *"),
    ],
)
def test_report_cron_strips_surrounding_quotes(
    monkeypatch: pytest.MonkeyPatch,
    compare_raw: str,
    today_raw: str,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_REPORT_COMPARE_CRON", compare_raw)
    monkeypatch.setenv("SALES_MONITORING_REPORT_TODAY_CRON", today_raw)
    s = SalesMonitoringSettings()
    assert s.report_compare_cron == "0 8 * * *"
    assert s.report_today_cron == "0 15 * * *"


def test_excluded_codes_csv_trim_drop_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_EXCLUDED_MACHINE_CODES", " A1, ,B2, ")
    assert SalesMonitoringSettings().excluded_machine_codes == ("A1", "B2")


def test_days_for_average_rejects_below_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_DAYS_FOR_AVERAGE", "1")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_last_sale_lookup_days_must_cover_baseline_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_DAYS_FOR_AVERAGE", "28")
    monkeypatch.setenv("SALES_MONITORING_LAST_SALE_LOOKUP_DAYS", "27")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_baseline_min_points_must_not_exceed_winsorize_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_BASELINE_MIN_POINTS", "9")
    monkeypatch.setenv("SALES_MONITORING_BASELINE_WINSORIZE_MIN_POINTS", "8")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_offline_poll_window_requires_from_lt_to(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_OFFLINE_POLL_FROM_HOUR", "22")
    monkeypatch.setenv("SALES_MONITORING_OFFLINE_POLL_TO_HOUR", "8")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_drop_percent_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_DROP_PERCENT", "101")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


@pytest.mark.parametrize("raw", ["-1", "41"])
def test_baseline_winsorize_percent_bounds(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_BASELINE_WINSORIZE_PERCENT", raw)
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_status_board_cron_default_daily_0800() -> None:
    """happy: daily rotate cron default 0 8 * * *."""
    assert SalesMonitoringSettings().status_board_cron == "0 8 * * *"


def test_status_board_cron_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """happy: CronEnvStr читает env (кавычки как у report crons)."""
    monkeypatch.setenv("SALES_MONITORING_STATUS_BOARD_CRON", '"0 9 * * 1"')
    assert SalesMonitoringSettings().status_board_cron == "0 9 * * 1"


def test_status_board_cleared_ttl_hours_field_removed() -> None:
    """edge: TTL hours Field удалён — attribute отсутствует."""
    assert "status_board_cleared_ttl_hours" not in SalesMonitoringSettings.model_fields
    assert not hasattr(SalesMonitoringSettings(), "status_board_cleared_ttl_hours")


def test_status_board_collection_default() -> None:
    """happy: Mongo collection default."""
    assert MongoSettings().sales_monitoring_status_board_collection == (
        "sales_monitoring_status_board"
    )


def test_sales_monitoring_collection_defaults() -> None:
    m = MongoSettings()
    assert m.sales_monitoring_audit_collection == "sales_monitoring_audit"
    assert m.sales_monitoring_worker_status_collection == "sales_monitoring_worker_status"


def test_sales_sheet_export_cursor_collection_default() -> None:
    assert MongoSettings().sales_sheet_export_cursor_collection == ("sales_sheet_export_cursors")


def test_sales_sheet_export_defaults_disabled() -> None:
    s = SalesMonitoringSettings()
    assert s.sales_sheet_export_enabled is False
    assert s.sales_sheet_spreadsheet_id is None
    assert s.sales_sheet_gid is None
    assert s.sales_sheet_max_rows == 100_000
    assert s.sales_sheet_export_cron == "0 1 * * *"


def test_export_enabled_requires_spreadsheet_id_and_gid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_EXPORT_ENABLED", "true")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


@pytest.mark.parametrize("raw_id", ["", "  "])
def test_export_enabled_rejects_blank_spreadsheet_id(
    monkeypatch: pytest.MonkeyPatch,
    raw_id: str,
) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_EXPORT_ENABLED", "true")
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_SPREADSHEET_ID", raw_id)
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_GID", "1")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_export_enabled_with_id_and_gid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_EXPORT_ENABLED", "true")
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_SPREADSHEET_ID", "sheet-abc")
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_GID", "42")
    s = SalesMonitoringSettings()
    assert s.sales_sheet_spreadsheet_id == "sheet-abc"
    assert s.sales_sheet_gid == 42


def test_sales_sheet_gid_is_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_EXPORT_ENABLED", "true")
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_SPREADSHEET_ID", "sheet-abc")
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_GID", "7")
    assert SalesMonitoringSettings().sales_sheet_gid == 7


def test_max_rows_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_SALES_SHEET_MAX_ROWS", "0")
    with pytest.raises(ValidationError):
        SalesMonitoringSettings()


def test_decline_chat_id_default_none() -> None:
    s = SalesMonitoringSettings()
    assert s.decline_telegram_chat_id is None


def test_decline_chat_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID", "-1003")
    assert SalesMonitoringSettings().decline_telegram_chat_id == -1003


def test_disabled_skips_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("SALES_MONITORING_WORKER_ENABLED", "false")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("SALES_MONITORING_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SALES_MONITORING_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("SALES_MONITORING_ALERT_TELEGRAM_CHAT_ID", raising=False)
    validate_sales_monitoring_worker_settings(Settings())


def test_enabled_requires_decline_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("SALES_MONITORING_WORKER_ENABLED", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("SALES_MONITORING_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("SALES_MONITORING_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("SALES_MONITORING_ALERT_TELEGRAM_CHAT_ID", "2")
    monkeypatch.delenv("SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID"):
        validate_sales_monitoring_worker_settings(Settings())


def test_enabled_requires_mongo_and_report_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("SALES_MONITORING_WORKER_ENABLED", "true")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("SALES_MONITORING_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SALES_MONITORING_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("SALES_MONITORING_ALERT_TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="SALES_MONITORING"):
        validate_sales_monitoring_worker_settings(Settings())
