from __future__ import annotations

import json

from aiogram import Bot, Dispatcher
from aiogram.webhook.security import IPFilter
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.interfaces.telegram.webhook_api import (
    TelegramWebhookDeps,
    register_telegram_webhook_routes,
)

_TELEGRAM_IP = "149.154.160.1"


def _client(*, max_body_bytes: int = 32) -> TestClient:
    app = FastAPI()
    bot = Bot(token="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")
    register_telegram_webhook_routes(
        app,
        deps=TelegramWebhookDeps(
            bot=bot,
            dispatcher=Dispatcher(),
            path="/webhooks/telegram",
            secret_token=None,
            ip_filter=IPFilter.default(),
            max_body_bytes=max_body_bytes,
        ),
    )
    return TestClient(app)


def test_telegram_webhook_oversized_body_returns_413() -> None:
    payload = {"update_id": 1, "message": {"text": "x" * 128}}
    body = json.dumps(payload).encode()
    response = _client(max_body_bytes=32).post(
        "/webhooks/telegram",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _TELEGRAM_IP,
        },
    )
    assert response.status_code == 413


def test_telegram_webhook_accepts_small_update_returns_200() -> None:
    payload = {"update_id": 1, "message": {"text": "hi"}}
    body = json.dumps(payload).encode()
    response = _client(max_body_bytes=1024).post(
        "/webhooks/telegram",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _TELEGRAM_IP,
        },
    )
    assert response.status_code == 200


def test_telegram_webhook_rejects_oversized_content_length() -> None:
    response = _client(max_body_bytes=32).post(
        "/webhooks/telegram",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "999999",
            "X-Forwarded-For": _TELEGRAM_IP,
        },
    )
    assert response.status_code == 413
