from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.webhook.security import IPFilter
from beartype import beartype
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response

from src.interfaces.http.bounded_body import read_bounded_request_body

logger = logging.getLogger(__name__)


# SECURITY NOTE: X-Forwarded-For is trusted without verifying the peer is a reverse proxy.
# Direct access to /webhooks/telegram allows spoofing Telegram IP ranges.
# Prod: Caddy + secret token. See docs/operational-assumptions.md (Telegram XFF).
@beartype
def _client_ip_allowed(request: Request, ip_filter: IPFilter) -> bool:
    if forwarded_for := request.headers.get("X-Forwarded-For"):
        client_ip, *_ = forwarded_for.split(",", maxsplit=1)
        client_ip = client_ip.strip()
    elif request.client is not None:
        client_ip = request.client.host
    else:
        return False
    try:
        return ip_filter.check(client_ip)
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class TelegramWebhookDeps:
    bot: Bot
    dispatcher: Dispatcher
    path: str
    secret_token: str | None
    ip_filter: IPFilter
    max_body_bytes: int = 1_048_576


@beartype
def register_telegram_webhook_routes(
    app: FastAPI,
    *,
    deps: TelegramWebhookDeps,
) -> None:
    path = deps.path.strip() or "/webhooks/telegram"
    if not path.startswith("/"):
        path = f"/{path}"

    @app.post(path)
    async def telegram_webhook(request: Request) -> Response:
        if not _client_ip_allowed(request, deps.ip_filter):
            raise HTTPException(status_code=401, detail="Unauthorized")

        if deps.secret_token is not None:
            header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not secrets.compare_digest(header_secret, deps.secret_token):
                raise HTTPException(status_code=401, detail="Unauthorized")

        body = await read_bounded_request_body(request, max_body_bytes=deps.max_body_bytes)
        try:
            update = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Invalid JSON") from exc
        task = asyncio.create_task(_feed_update(deps, update))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return Response(status_code=200)


_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


@beartype
async def _feed_update(deps: TelegramWebhookDeps, update: dict[str, Any]) -> None:
    try:
        await deps.dispatcher.feed_raw_update(bot=deps.bot, update=update)
    except Exception:
        logger.exception("Failed to process Telegram webhook update")


@beartype
async def drain_telegram_background_tasks(*, timeout_seconds: float = 10.0) -> None:
    if not _BACKGROUND_TASKS:
        return
    tasks = list(_BACKGROUND_TASKS)
    _done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
    if pending:
        logger.warning(
            "Telegram background tasks still running after %.1fs shutdown drain: %d",
            timeout_seconds,
            len(pending),
        )
