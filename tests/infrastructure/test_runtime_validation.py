from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from src.config.event_reminders import EventRemindersSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.micromarket_loading import MicromarketLoadingSettings
from src.config.mongodb import MongoSettings
from src.config.moysklad import MoySkladSettings
from src.config.object_storage import ObjectStorageSettings
from src.config.redis import RedisSettings
from src.config.sales_monitoring import SalesMonitoringSettings
from src.config.settings import Settings
from src.config.snack_loading import SnackLoadingSettings
from src.config.telegram import TelegramSettings
from src.infrastructure.composition.validation import validate_runtime_settings


def _google_forms_settings() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("prod-webhook-secret-ok"),
        revision_form_token_secret=SecretStr("prod-revision-secret-ok"),
        loading_form_token_secret=SecretStr("prod-loading-secret-ok"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "prod-warehouse-inventory-secret-ok",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _google_sheets_settings(**overrides: object) -> GoogleSheetsSettings:
    defaults = {
        "credentials_file": "credentials.json",
        "product_catalog_spreadsheet_id": "catalog-spreadsheet",
        "product_catalog_sheet_id": 1,
        "coffee_technician_locations_spreadsheet_id": "locations-spreadsheet",
        "coffee_technician_locations_sheet_id": 2,
        "users_sheet_id": 3,
        "technicians_directory_spreadsheet_id": "tech-dir",
        "technicians_directory_sheet_id": 4,
    }
    defaults.update(overrides)
    return GoogleSheetsSettings.model_construct(**defaults)


def _telegram_settings(**overrides: object) -> TelegramSettings:
    defaults = {
        "bot_token": SecretStr("prod-bot-token-16chars"),
        "webhook_public_host": "bot.example.com",
        "webhook_path": "/webhooks/telegram",
        "webhook_secret": SecretStr("prod-telegram-wh-secret"),
        "alert_chat_id": -1001234567890,
    }
    defaults.update(overrides)
    return TelegramSettings.model_construct(**defaults)


def _prod_settings(**updates: object) -> Settings:
    base = Settings.model_construct(
        environment="prod",
        telegram=_telegram_settings(),
        google_forms=_google_forms_settings(),
        google_sheets=_google_sheets_settings(),
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("moysklad-token"),
            organization_id=str(UUID(int=1)),
            project_id=str(UUID(int=2)),
        ),
        mongodb=MongoSettings.model_construct(
            uri="mongodb://localhost:27017/mk_service_bot",
        ),
        redis=RedisSettings.model_construct(uri="redis://localhost:6379/0"),
        object_storage=ObjectStorageSettings.model_construct(
            backend="s3",
            s3_bucket="photos",
            s3_access_key_id="key",
            s3_secret_access_key=SecretStr("prod-s3-secret-key-ok"),
            photo_storage_ttl_days=90,
        ),
    )
    if not updates:
        return base
    return base.model_copy(update=updates)


def test_validate_runtime_settings_allows_fully_configured_prod() -> None:
    validate_runtime_settings(_prod_settings())


def test_prod_requires_telegram_alert_chat_id() -> None:
    settings = _prod_settings(
        telegram=_telegram_settings(alert_chat_id=None),
    )
    with pytest.raises(ValueError, match="TELEGRAM_ALERT_CHAT_ID"):
        validate_runtime_settings(settings)


def test_validate_runtime_settings_allows_dev_without_mongo() -> None:
    validate_runtime_settings(
        _prod_settings(
            environment="dev",
            mongodb=MongoSettings.model_construct(uri=None),
            redis=RedisSettings.model_construct(uri=None),
            moysklad=MoySkladSettings.model_construct(api_token=None),
            google_sheets=_google_sheets_settings(
                credentials_file="",
                product_catalog_spreadsheet_id="",
                product_catalog_sheet_id=None,
                coffee_technician_locations_spreadsheet_id="",
                coffee_technician_locations_sheet_id=None,
                users_sheet_id=None,
            ),
        ),
    )


def test_validate_runtime_settings_rejects_dev_with_moysklad_token() -> None:
    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        validate_runtime_settings(
            _prod_settings(
                environment="dev",
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("moysklad-token"),
                ),
            ),
        )


def test_validate_runtime_settings_allows_test_without_mongo() -> None:
    validate_runtime_settings(
        _prod_settings(
            environment="test",
            mongodb=MongoSettings.model_construct(uri=None),
        ),
    )


def test_validate_runtime_settings_rejects_prod_without_mongo() -> None:
    with pytest.raises(ValueError, match="MONGODB_URI"):
        validate_runtime_settings(
            _prod_settings(mongodb=MongoSettings.model_construct(uri=None)),
        )


def test_validate_runtime_settings_rejects_prod_without_redis() -> None:
    with pytest.raises(ValueError, match="REDIS_URI"):
        validate_runtime_settings(
            _prod_settings(redis=RedisSettings.model_construct(uri=None)),
        )


def test_validate_runtime_settings_rejects_prod_without_moysklad() -> None:
    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        validate_runtime_settings(
            _prod_settings(moysklad=MoySkladSettings.model_construct(api_token=None)),
        )


def test_validate_runtime_settings_rejects_prod_without_product_catalog() -> None:
    with pytest.raises(ValueError, match="PRODUCT_CATALOG"):
        validate_runtime_settings(
            _prod_settings(
                google_sheets=_google_sheets_settings(
                    product_catalog_spreadsheet_id="",
                    product_catalog_sheet_id=None,
                ),
            ),
        )


def test_validate_runtime_settings_rejects_prod_without_technician_locations() -> None:
    with pytest.raises(ValueError, match="COFFEE_TECHNICIAN_LOCATIONS"):
        validate_runtime_settings(
            _prod_settings(
                google_sheets=_google_sheets_settings(
                    coffee_technician_locations_spreadsheet_id="",
                    coffee_technician_locations_sheet_id=None,
                    users_sheet_id=None,
                ),
            ),
        )


def test_validate_runtime_settings_collects_multiple_prod_errors() -> None:
    with pytest.raises(ValueError) as error:
        validate_runtime_settings(
            _prod_settings(
                mongodb=MongoSettings.model_construct(uri=None),
                redis=RedisSettings.model_construct(uri=None),
                moysklad=MoySkladSettings.model_construct(api_token=None),
            ),
        )

    message = str(error.value)
    assert "MONGODB_URI" in message
    assert "REDIS_URI" in message
    assert "MOYSKLAD_API_TOKEN" in message


def test_validate_runtime_settings_rejects_prod_without_telegram_webhook_host() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_IP"):
        validate_runtime_settings(
            _prod_settings(
                telegram=_telegram_settings(webhook_public_host=""),
            ),
        )


def test_validate_runtime_settings_rejects_prod_without_telegram_webhook_secret() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        validate_runtime_settings(
            _prod_settings(
                telegram=_telegram_settings(webhook_secret=None),
            ),
        )


def test_validate_runtime_settings_rejects_prod_without_bot_token() -> None:
    with pytest.raises(ValueError, match="BOT_TOKEN"):
        validate_runtime_settings(
            _prod_settings(
                telegram=_telegram_settings(bot_token=SecretStr("")),
            ),
        )


def test_validate_runtime_settings_rejects_prod_with_short_bot_token() -> None:
    with pytest.raises(ValueError, match="BOT_TOKEN"):
        validate_runtime_settings(
            _prod_settings(
                telegram=_telegram_settings(bot_token=SecretStr("short")),
            ),
        )


def test_validate_runtime_settings_rejects_prod_with_dev_webhook_secret() -> None:
    with pytest.raises(ValueError, match="GOOGLE_FORMS_WEBHOOK_SECRET"):
        validate_runtime_settings(
            _prod_settings(
                google_forms=_google_forms_settings().model_copy(
                    update={"webhook_secret": SecretStr("dev-webhook-secret")},
                ),
            ),
        )


def test_validate_runtime_settings_prod_requires_s3_photo_storage() -> None:
    settings = _prod_settings(
        object_storage=ObjectStorageSettings.model_construct(backend="memory"),
    )
    with pytest.raises(ValueError, match="PHOTO_STORAGE_BACKEND"):
        validate_runtime_settings(settings)


def test_prod_requires_photo_storage_ttl_when_s3_backend() -> None:
    settings = _prod_settings(
        object_storage=ObjectStorageSettings.model_construct(
            backend="s3",
            s3_bucket="photos",
            s3_access_key_id="key",
            s3_secret_access_key=SecretStr("prod-s3-secret-key-ok"),
            photo_storage_ttl_days=None,
        ),
    )
    with pytest.raises(ValueError, match="PHOTO_STORAGE_TTL_DAYS"):
        validate_runtime_settings(settings)


def test_validate_runtime_settings_prod_allows_s3_photo_storage() -> None:
    settings = _prod_settings(
        object_storage=ObjectStorageSettings.model_construct(
            backend="s3",
            s3_bucket="photos",
            s3_access_key_id="key",
            s3_secret_access_key=SecretStr("prod-s3-secret-key-ok"),
            photo_storage_ttl_days=90,
        ),
    )
    validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_warehouse_form_token_secret() -> None:
    settings = _prod_settings(
        google_forms=_google_forms_settings().model_copy(
            update={
                "technician_warehouse_inventory_form_token_secret": SecretStr("short"),
            },
        ),
    )
    with pytest.raises(
        ValueError,
        match="TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
    ):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_snack_now_token_secret() -> None:
    settings = _prod_settings(
        snack_loading=SnackLoadingSettings.model_construct(
            inventory_form_now_token_secret=SecretStr("short"),
        ),
    )
    with pytest.raises(ValueError, match="SNACK_INVENTORY_FORM_NOW_TOKEN_SECRET"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_micromarket_now_token_secret() -> None:
    # error
    settings = _prod_settings(
        micromarket_loading=MicromarketLoadingSettings.model_construct(
            inventory_form_now_token_secret=SecretStr("short"),
        ),
    )
    with pytest.raises(ValueError, match="MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_micromarket_as_of_token_secret() -> None:
    # error
    settings = _prod_settings(
        micromarket_loading=MicromarketLoadingSettings.model_construct(
            inventory_form_as_of_token_secret=SecretStr("short"),
        ),
    )
    with pytest.raises(ValueError, match="MICROMARKET_INVENTORY_FORM_AS_OF_TOKEN_SECRET"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_sales_monitoring_bot_token_when_worker_enabled() -> None:
    settings = _prod_settings(
        sales_monitoring=SalesMonitoringSettings.model_construct(
            worker_enabled=True,
            telegram_bot_token=SecretStr("short"),
        ),
    )
    with pytest.raises(ValueError, match="SALES_MONITORING_TELEGRAM_BOT_TOKEN"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_event_reminders_bot_token_when_worker_enabled() -> None:
    settings = _prod_settings(
        event_reminders=EventRemindersSettings.model_construct(
            worker_enabled=True,
            telegram_bot_token=SecretStr("short"),
        ),
    )
    with pytest.raises(ValueError, match="EVENT_REMINDERS_TELEGRAM_BOT_TOKEN"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_s3_secret_access_key() -> None:
    settings = _prod_settings(
        object_storage=ObjectStorageSettings.model_construct(
            backend="s3",
            s3_bucket="photos",
            s3_access_key_id="key",
            s3_secret_access_key=SecretStr("secret"),
            photo_storage_ttl_days=90,
        ),
    )
    with pytest.raises(ValueError, match="S3_SECRET_ACCESS_KEY"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_session_secret() -> None:
    settings = _prod_settings()
    settings = settings.model_copy(
        update={
            "master_data": settings.master_data.model_copy(
                update={"enabled": True, "session_secret": SecretStr("short")},
            ),
        },
    )
    with pytest.raises(ValueError, match="ADMIN_SESSION_SECRET"):
        validate_runtime_settings(settings)


def test_prod_settings_rejects_weak_session_secret_when_only_companies_enabled() -> None:
    # error
    settings = _prod_settings()
    settings = settings.model_copy(
        update={
            "master_data": settings.master_data.model_copy(
                update={
                    "enabled": False,
                    "users_enabled": False,
                    "technicians_enabled": False,
                    "companies_enabled": True,
                    "session_secret": SecretStr("short"),
                },
            ),
            "location_roster": settings.location_roster.model_copy(update={"enabled": False}),
            "settlement_analysis": settings.settlement_analysis.model_copy(
                update={"enabled": False},
            ),
        },
    )
    with pytest.raises(ValueError, match="ADMIN_SESSION_SECRET"):
        validate_runtime_settings(settings)


def test_validate_runtime_settings_rejects_prod_with_dev_form_token_secrets() -> None:
    with pytest.raises(ValueError) as error:
        validate_runtime_settings(
            _prod_settings(
                google_forms=_google_forms_settings().model_copy(
                    update={
                        "revision_form_token_secret": SecretStr(
                            "dev-revision-form-token-secret",
                        ),
                        "loading_form_token_secret": SecretStr(
                            "dev-loading-form-token-secret",
                        ),
                    },
                ),
            ),
        )

    message = str(error.value)
    assert "REVISION_FORM_TOKEN_SECRET" in message
    assert "LOADING_FORM_TOKEN_SECRET" in message
