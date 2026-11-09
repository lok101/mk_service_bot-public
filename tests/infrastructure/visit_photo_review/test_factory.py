from __future__ import annotations

from pathlib import Path

import mongomock
import pytest
from pydantic import SecretStr

from src.config.google_forms import GoogleFormsSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.config.visit_photo_review import VisitPhotoReviewSettings
from src.infrastructure.composition.factories.visit_photo_review import (
    build_visit_photo_review_deps,
)
from src.infrastructure.photo_batches import InMemoryPhotoBatchStore


def _settings(tmp_path: Path, *, mongodb_uri: str) -> Settings:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":[{"group_id":"waste_tank","title":"Бак","required":true,"defects":[]}]}',
        encoding="utf-8",
    )
    uri = mongodb_uri.strip() or None
    return Settings.model_construct(
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
        mongodb=MongoSettings.model_construct(uri=uri),
        visit_photo_review=VisitPhotoReviewSettings(
            VISIT_PHOTO_REVIEW_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            ADMIN_SESSION_SECRET=SecretStr("session-secret"),
            TELEGRAM_BOT_USERNAME="bot",
        ),
    )


def test_factory_returns_none_without_database_uri(tmp_path: Path) -> None:
    assert build_visit_photo_review_deps(_settings(tmp_path, mongodb_uri="")) is None


def test_factory_wires_queries_when_database_uri_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = mongomock.MongoClient()

    def _fake_mongo_client(*_args: object, **_kwargs: object) -> mongomock.MongoClient:
        return fake_client

    def _fake_photo_batch_store(*_args: object, **_kwargs: object) -> InMemoryPhotoBatchStore:
        return InMemoryPhotoBatchStore()

    monkeypatch.setattr(
        "src.infrastructure.composition.factories.visit_photo_review.create_mongo_client",
        _fake_mongo_client,
    )
    monkeypatch.setattr(
        "src.infrastructure.composition.factories.visit_photo_review.build_photo_batch_store",
        _fake_photo_batch_store,
    )
    deps = build_visit_photo_review_deps(
        _settings(tmp_path, mongodb_uri="mongodb://localhost"),
    )
    assert deps is not None
    assert deps.review_queries is not None
    assert deps.group_avatar_writer is not None
    assert deps.update_group_defects is not None
    assert deps.write_group_avatar is not None
