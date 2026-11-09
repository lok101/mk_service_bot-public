from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import Settings
from src.config.worker_liveness import (
    WORKER_LIVENESS_TARGETS_V1,
    WorkerLivenessSettings,
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


def test_worker_liveness_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = WorkerLivenessSettings()
    assert settings.stale_seconds == 300
    assert settings.alert_cooldown_seconds == 1800
    assert settings.bootstrap_cooldown_seconds == 1800

    assert len(WORKER_LIVENESS_TARGETS_V1) == 6
    assert tuple(t.name for t in WORKER_LIVENESS_TARGETS_V1) == (
        "sales-monitoring",
        "matrix",
        "daily-sales-demand",
        "machine-pnl-month",
        "service-visits",
        "effects-worker",
    )
    assert tuple(t.status_collection for t in WORKER_LIVENESS_TARGETS_V1) == (
        "sales_monitoring_worker_status",
        "matrix_worker_status",
        "daily_sales_demand_worker_status",
        "machine_pnl_month_worker_status",
        "service_visits_worker_status",
        "effects_worker_status",
    )
    assert all("event-reminders" not in t.name for t in WORKER_LIVENESS_TARGETS_V1)

    _stub_required_app_env(monkeypatch)
    nested = Settings()
    assert nested.worker_liveness.stale_seconds == 300
    assert nested.worker_liveness.alert_cooldown_seconds == 1800
    assert nested.worker_liveness.bootstrap_cooldown_seconds == 1800


def test_worker_liveness_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_LIVENESS_STALE_SECONDS", "120")
    monkeypatch.setenv("WORKER_LIVENESS_ALERT_COOLDOWN_SECONDS", "900")
    monkeypatch.setenv("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", "600")
    settings = WorkerLivenessSettings()
    assert settings.stale_seconds == 120
    assert settings.alert_cooldown_seconds == 900
    assert settings.bootstrap_cooldown_seconds == 600


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("WORKER_LIVENESS_STALE_SECONDS", "60"),
        ("WORKER_LIVENESS_STALE_SECONDS", "0"),
        ("WORKER_LIVENESS_ALERT_COOLDOWN_SECONDS", "0"),
        ("WORKER_LIVENESS_BOOTSTRAP_COOLDOWN_SECONDS", "-1"),
    ],
)
def test_worker_liveness_rejects_invalid_seconds(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(env_name, value)
    with pytest.raises(ValidationError):
        WorkerLivenessSettings()
