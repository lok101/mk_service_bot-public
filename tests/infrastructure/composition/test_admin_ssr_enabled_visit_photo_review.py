from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.infrastructure.composition.runtime import admin_ssr_enabled


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


def test_admin_ssr_enabled_when_visit_photo_review_on(monkeypatch, tmp_path) -> None:
    _stub_required_app_env(monkeypatch)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":[{"group_id":"waste_tank","title":"Бак","required":true,"defects":[]}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("VISIT_PHOTO_REVIEW_ENABLED", "true")
    monkeypatch.setenv("VISIT_PHOTO_REVIEW_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-at-least-long")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "testbot")
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "false")
    monkeypatch.setenv("MASTER_DATA_ENABLED", "false")
    monkeypatch.setenv("MASTER_DATA_USERS_ENABLED", "false")
    monkeypatch.setenv("MASTER_DATA_TECHNICIANS_ENABLED", "false")
    monkeypatch.setenv("MASTER_DATA_COMPANIES_ENABLED", "false")
    monkeypatch.setenv("SETTLEMENT_ANALYSIS_ADMIN_ENABLED", "false")
    settings = Settings()
    assert settings.visit_photo_review.enabled is True
    assert admin_ssr_enabled(settings) is True
