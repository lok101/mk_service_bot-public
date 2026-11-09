from __future__ import annotations

from pydantic import SecretStr

from src.application.snack_loading.ports import NoOpSnackLoadingFailAfterMoveNotifier
from src.config.google_forms import GoogleFormsSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings
from src.infrastructure.alerting.snack_loading_fail_after_move_notifier import (
    TelegramSnackLoadingFailAfterMoveNotifier,
)
from src.infrastructure.composition.factories.snack_loading_cli import _build_alert_notifier


def _stub_forms() -> GoogleFormsSettings:
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


def test_build_alert_notifier_noop_without_chat_id() -> None:
    settings = Settings.model_construct(
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
        google_forms=_stub_forms(),
    )
    n = _build_alert_notifier(settings)
    assert isinstance(n, NoOpSnackLoadingFailAfterMoveNotifier)


def test_build_alert_notifier_telegram_with_chat_id() -> None:
    settings = Settings.model_construct(
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=42,
        ),
        google_forms=_stub_forms(),
    )
    n = _build_alert_notifier(settings)
    assert isinstance(n, TelegramSnackLoadingFailAfterMoveNotifier)
    assert n.chat_id == 42
