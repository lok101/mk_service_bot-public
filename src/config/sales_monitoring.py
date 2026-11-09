from __future__ import annotations

from typing import Annotated, Any, Self

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from src.config._base import DEFAULT_ENV_FILE, ServiceSettingsBase


def _parse_excluded_machine_codes(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, tuple):
        return value
    raw = value.split(",") if isinstance(value, str) else value
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _strip_env_quotes(value: Any) -> Any:
    """Normalize dotenv values that still carry surrounding quotes."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return value


ExcludedMachineCodes = Annotated[
    tuple[str, ...],
    NoDecode,
    BeforeValidator(_parse_excluded_machine_codes),
]

CronEnvStr = Annotated[str, BeforeValidator(_strip_env_quotes)]


class SalesMonitoringSettings(ServiceSettingsBase):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    worker_enabled: bool = Field(
        default=False,
        validation_alias="SALES_MONITORING_WORKER_ENABLED",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_TELEGRAM_BOT_TOKEN",
    )
    telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_TELEGRAM_CHAT_ID",
    )
    decline_telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_DECLINE_TELEGRAM_CHAT_ID",
    )
    alert_telegram_chat_id: int | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_ALERT_TELEGRAM_CHAT_ID",
    )
    alert_telegram_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_ALERT_TELEGRAM_BOT_TOKEN",
    )
    tz: str = Field(
        default="Asia/Yekaterinburg",
        validation_alias="SALES_MONITORING_TZ",
    )
    days_for_average: int = Field(
        default=28,
        validation_alias="SALES_MONITORING_DAYS_FOR_AVERAGE",
        ge=2,
    )
    sales_drop_percent: int = Field(
        default=30,
        validation_alias="SALES_MONITORING_SALES_DROP_PERCENT",
        ge=0,
        le=100,
    )
    last_sale_lookup_days: int = Field(
        default=28,
        validation_alias="SALES_MONITORING_LAST_SALE_LOOKUP_DAYS",
        ge=1,
    )
    baseline_min_points: int = Field(
        default=4,
        validation_alias="SALES_MONITORING_BASELINE_MIN_POINTS",
        ge=1,
    )
    baseline_winsorize_min_points: int = Field(
        default=8,
        validation_alias="SALES_MONITORING_BASELINE_WINSORIZE_MIN_POINTS",
        ge=1,
    )
    baseline_winsorize_percent: int = Field(
        default=10,
        validation_alias="SALES_MONITORING_BASELINE_WINSORIZE_PERCENT",
        ge=0,
        le=40,
    )
    no_sales_habitual_max_nonempty: int = Field(
        default=1,
        validation_alias="SALES_MONITORING_NO_SALES_HABITUAL_MAX_NONEMPTY",
        ge=0,
    )
    offline_ping_threshold_minutes: int = Field(
        default=25,
        validation_alias="SALES_MONITORING_OFFLINE_PING_THRESHOLD_MINUTES",
        ge=1,
    )
    offline_poll_interval_minutes: int = Field(
        default=60,
        validation_alias="SALES_MONITORING_OFFLINE_POLL_INTERVAL_MINUTES",
        ge=1,
    )
    offline_poll_from_hour: int = Field(
        default=8,
        validation_alias="SALES_MONITORING_OFFLINE_POLL_FROM_HOUR",
        ge=0,
        le=23,
    )
    offline_poll_to_hour: int = Field(
        default=22,
        validation_alias="SALES_MONITORING_OFFLINE_POLL_TO_HOUR",
        ge=0,
        le=23,
    )
    no_sales_stale_hours: int = Field(
        default=24,
        validation_alias="SALES_MONITORING_NO_SALES_STALE_HOURS",
        ge=1,
    )
    no_sales_eval_interval_minutes: int = Field(
        default=60,
        validation_alias="SALES_MONITORING_NO_SALES_EVAL_INTERVAL_MINUTES",
        ge=1,
    )
    incident_clear_pair_minutes: int = Field(
        default=30,
        validation_alias="SALES_MONITORING_INCIDENT_CLEAR_PAIR_MINUTES",
        ge=1,
    )
    no_sales_ingest_cursor_max_lag_minutes: int = Field(
        default=45,
        validation_alias="SALES_MONITORING_NO_SALES_INGEST_CURSOR_MAX_LAG_MINUTES",
        ge=1,
    )
    excluded_machine_codes: ExcludedMachineCodes = Field(
        default=(),
        validation_alias="SALES_MONITORING_EXCLUDED_MACHINE_CODES",
    )
    report_compare_cron: CronEnvStr = Field(
        default="0 8 * * *",
        validation_alias="SALES_MONITORING_REPORT_COMPARE_CRON",
    )
    report_today_cron: CronEnvStr = Field(
        default="0 15 * * *",
        validation_alias="SALES_MONITORING_REPORT_TODAY_CRON",
    )
    status_board_cron: CronEnvStr = Field(
        default="0 8 * * *",
        validation_alias="SALES_MONITORING_STATUS_BOARD_CRON",
    )
    sales_sheet_export_enabled: bool = Field(
        default=False,
        validation_alias="SALES_MONITORING_SALES_SHEET_EXPORT_ENABLED",
    )
    sales_sheet_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_SALES_SHEET_SPREADSHEET_ID",
    )
    sales_sheet_gid: int | None = Field(
        default=None,
        validation_alias="SALES_MONITORING_SALES_SHEET_GID",
    )
    sales_sheet_max_rows: int = Field(
        default=100_000,
        validation_alias="SALES_MONITORING_SALES_SHEET_MAX_ROWS",
        ge=1,
    )
    sales_sheet_export_cron: CronEnvStr = Field(
        default="0 1 * * *",
        validation_alias="SALES_MONITORING_SALES_SHEET_EXPORT_CRON",
    )

    @field_validator("telegram_bot_token", "alert_telegram_bot_token", mode="before")
    @classmethod
    def empty_secret_is_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @field_validator("sales_sheet_spreadsheet_id", mode="before")
    @classmethod
    def empty_spreadsheet_id_is_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_offline_poll_window(self) -> Self:
        if self.offline_poll_from_hour >= self.offline_poll_to_hour:
            raise ValueError(
                "SALES_MONITORING_OFFLINE_POLL_FROM_HOUR must be < "
                "SALES_MONITORING_OFFLINE_POLL_TO_HOUR",
            )
        return self

    @model_validator(mode="after")
    def validate_lookback_covers_baseline(self) -> Self:
        if self.last_sale_lookup_days < self.days_for_average:
            raise ValueError(
                "SALES_MONITORING_LAST_SALE_LOOKUP_DAYS must be >= "
                "SALES_MONITORING_DAYS_FOR_AVERAGE",
            )
        return self

    @model_validator(mode="after")
    def validate_baseline_min_vs_winsorize_min(self) -> Self:
        if self.baseline_min_points > self.baseline_winsorize_min_points:
            raise ValueError(
                "SALES_MONITORING_BASELINE_MIN_POINTS must be <= "
                "SALES_MONITORING_BASELINE_WINSORIZE_MIN_POINTS",
            )
        return self

    @model_validator(mode="after")
    def validate_sales_sheet_export_targets(self) -> Self:
        if not self.sales_sheet_export_enabled:
            return self
        missing: list[str] = []
        if self.sales_sheet_spreadsheet_id is None:
            missing.append("SALES_MONITORING_SALES_SHEET_SPREADSHEET_ID")
        if self.sales_sheet_gid is None:
            missing.append("SALES_MONITORING_SALES_SHEET_GID")
        if missing:
            raise ValueError(
                "sales sheet export enabled requires non-empty: " + ", ".join(missing),
            )
        return self
