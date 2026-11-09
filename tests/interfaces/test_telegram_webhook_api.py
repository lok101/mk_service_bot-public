from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.webhook.security import IPFilter
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.interfaces.telegram.webhook_api import (
    TelegramWebhookDeps,
    register_telegram_webhook_routes,
)

_TELEGRAM_IP = "149.154.160.1"
_UNAUTHORIZED_IP = "203.0.113.1"


def _build_client(
    *,
    secret_token: str | None,
    ip_filter: IPFilter | None = None,
) -> TestClient:
    bot = MagicMock()
    dispatcher = MagicMock()
    dispatcher.feed_raw_update = AsyncMock()
    app = FastAPI()
    register_telegram_webhook_routes(
        app,
        deps=TelegramWebhookDeps(
            bot=bot,
            dispatcher=dispatcher,
            path="/webhooks/telegram",
            secret_token=secret_token,
            ip_filter=ip_filter or IPFilter.default(),
        ),
    )
    return TestClient(app)


def test_telegram_webhook_rejects_unauthorized_ip() -> None:
    client = _build_client(secret_token=None)
    response = client.post(
        "/webhooks/telegram",
        json={"update_id": 1},
        headers={"X-Forwarded-For": _UNAUTHORIZED_IP},
    )
    assert response.status_code == 401


def test_telegram_webhook_rejects_invalid_secret() -> None:
    client = _build_client(secret_token="wh-secret")
    response = client.post(
        "/webhooks/telegram",
        json={"update_id": 1},
        headers={"X-Forwarded-For": _TELEGRAM_IP},
    )
    assert response.status_code == 401


def test_telegram_webhook_accepts_update() -> None:
    client = _build_client(secret_token="wh-secret")
    response = client.post(
        "/webhooks/telegram",
        json={"update_id": 42},
        headers={
            "X-Forwarded-For": _TELEGRAM_IP,
            "X-Telegram-Bot-Api-Secret-Token": "wh-secret",
        },
    )
    assert response.status_code == 200
