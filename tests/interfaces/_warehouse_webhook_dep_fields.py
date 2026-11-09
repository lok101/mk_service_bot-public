from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import create_autospec

from src.application.form_submissions.ports import TelegramUserResolver
from src.domain.form_tokens import peek_form_token, verify_technician_warehouse_inventory_token
from src.interfaces.google_forms.webhook import WebhookPlaceholderBot


@dataclass(frozen=True, slots=True)
class UnusedAcceptWarehouseInventory:
    def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("warehouse inventory accept must not be called")


@dataclass(frozen=True, slots=True)
class NoOpDirectWarehouseChatNotifier:
    async def notify(self, **kwargs: object) -> None:
        return None


def warehouse_webhook_dep_kwargs() -> dict[str, object]:
    resolver = create_autospec(TelegramUserResolver, instance=True)
    resolver.find_by_technician_id.return_value = None
    return {
        "accept_technician_warehouse_inventory": UnusedAcceptWarehouseInventory(),
        "direct_warehouse_chat_notifier": NoOpDirectWarehouseChatNotifier(),
        "telegram_user_resolver": resolver,
        "bot": WebhookPlaceholderBot(),
        "technician_warehouse_inventory_form_token_secret": "warehouse-secret",
        "verify_technician_warehouse_inventory_token": verify_technician_warehouse_inventory_token,
        "peek_form_token": peek_form_token,
    }
