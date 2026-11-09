from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.settings import Settings
from src.config.visit_photo_review import VisitPhotoReviewSettings


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


def test_visit_photo_review_disabled_does_not_require_catalog() -> None:
    settings = VisitPhotoReviewSettings()
    assert settings.enabled is False
    assert settings.catalog_path == ""
    assert settings.collection == "visit_photo_reviews"


def test_visit_photo_review_enabled_requires_session_secret(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":[{"group_id":"a","title":"A","required":false,"defects":[]}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET="",
            TELEGRAM_BOT_USERNAME="bot",
        )


def test_visit_photo_review_enabled_rejects_bot_username_with_at(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":[{"group_id":"a","title":"A","required":false,"defects":[]}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET="secret",
            TELEGRAM_BOT_USERNAME="@bot",
        )


def test_visit_photo_review_stub_login_allows_empty_bot_username(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":[{"group_id":"a","title":"A","required":false,"defects":[]}]}',
        encoding="utf-8",
    )
    settings = VisitPhotoReviewSettings(
        VISIT_PHOTO_REVIEW_ENABLED="true",
        VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
        ADMIN_SESSION_SECRET="secret",
        TELEGRAM_BOT_USERNAME="",
        ADMIN_DEV_STUB_LOGIN_ENABLED="true",
    )
    assert settings.enabled is True


def test_visit_photo_review_enabled_rejects_missing_catalog(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(missing),
            ADMIN_SESSION_SECRET="secret",
            TELEGRAM_BOT_USERNAME="bot",
        )


def test_visit_photo_review_enabled_rejects_empty_catalog(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"groups":[]}', encoding="utf-8")
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET="secret",
            TELEGRAM_BOT_USERNAME="bot",
        )


def test_visit_photo_review_enabled_rejects_invalid_json(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET="secret",
            TELEGRAM_BOT_USERNAME="bot",
        )


def test_visit_photo_review_enabled_rejects_duplicate_group_in_file(tmp_path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":['
        '{"group_id":"a","title":"A","required":false,"defects":[]},'
        '{"group_id":"a","title":"B","required":false,"defects":[]}'
        "]}",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET="secret",
            TELEGRAM_BOT_USERNAME="bot",
        )


def test_settings_nested_visit_photo_review_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    settings = Settings()
    assert settings.visit_photo_review.enabled is False


def test_settings_rejects_visit_photo_review_stub_when_webhook_host_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("VISIT_PHOTO_REVIEW_ENABLED", "false")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_IP", "203.0.113.10")
    with pytest.raises(ValidationError):
        Settings()
