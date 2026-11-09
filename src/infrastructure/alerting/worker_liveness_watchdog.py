from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype

from src.config.worker_liveness import WorkerLivenessTarget
from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_LOGGER = logging.getLogger(__name__)
_EVENT = "worker_liveness_watchdog_alert"
_WORKER_DOC_ID = "worker"
_TICK_INTERVAL_SECONDS = 60.0


@runtime_checkable
class WorkerStatusCollection(Protocol):
    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...


@runtime_checkable
class WorkerStatusDatabase(Protocol):
    def __getitem__(self, name: str) -> WorkerStatusCollection: ...


@beartype
def _parse_heartbeat(raw: object) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        moment = raw
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@beartype
@dataclass(slots=True)
class WorkerLivenessWatchdog:
    targets: tuple[WorkerLivenessTarget, ...]
    stale_seconds: int
    alert_cooldown_seconds: int
    database: WorkerStatusDatabase
    send_alert: Callable[[str], None] | None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))
    _last_alert_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    @beartype
    def check_once(self) -> None:
        if self.send_alert is None:
            _LOGGER.info(
                "%s skip=%s",
                _EVENT,
                "alerts_disabled",
                extra={"event": _EVENT, "skip_reason": "alerts_disabled"},
            )
            return

        now = self.now()
        now_ts = now.timestamp()
        for target in self.targets:
            try:
                document = self.database[target.status_collection].find_one(
                    {"_id": _WORKER_DOC_ID},
                )
            except Exception as exc:  # noqa: BLE001 — fail-closed per target, continue tick
                _LOGGER.error(
                    "%s mongo_read_failed target=%s error=%s",
                    _EVENT,
                    target.name,
                    exc,
                    extra={
                        "event": _EVENT,
                        "target": target.name,
                        "collection": target.status_collection,
                    },
                )
                continue

            heartbeat = (
                None
                if document is None
                else _parse_heartbeat(
                    document.get("last_heartbeat_at"),
                )
            )
            if heartbeat is not None:
                age_seconds = (now - heartbeat).total_seconds()
                if age_seconds <= self.stale_seconds:
                    continue
                reason = "stale"
            else:
                reason = "missing"

            last_sent = self._last_alert_at.get(target.name)
            if last_sent is not None and (now_ts - last_sent) < self.alert_cooldown_seconds:
                _LOGGER.info(
                    "%s skip=%s target=%s",
                    _EVENT,
                    "cooldown",
                    target.name,
                    extra={
                        "event": _EVENT,
                        "skip_reason": "cooldown",
                        "target": target.name,
                    },
                )
                continue

            text = (
                f"worker liveness: {target.name} heartbeat {reason}\n"
                f"collection: {target.status_collection}"
            )
            try:
                self.send_alert(text)
            except Exception as send_exc:  # noqa: BLE001
                _LOGGER.error(
                    "%s send_failed target=%s error=%s",
                    _EVENT,
                    target.name,
                    send_exc,
                    extra={"event": _EVENT, "target": target.name},
                )
                continue

            self._last_alert_at[target.name] = now_ts
            _LOGGER.info(
                "%s sent target=%s reason=%s",
                _EVENT,
                target.name,
                reason,
                extra={
                    "event": _EVENT,
                    "target": target.name,
                    "reason": reason,
                },
            )

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.check_once)
            except Exception:
                _LOGGER.exception("%s tick_failed", _EVENT)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_TICK_INTERVAL_SECONDS)


@beartype
def build_telegram_alert_sender(
    *,
    bot_token: str,
    chat_id: int | None,
) -> Callable[[str], None] | None:
    token = bot_token.strip()
    if not token or chat_id is None:
        return None

    def _send(text: str) -> None:
        send_telegram_message(bot_token=token, chat_id=chat_id, text=text)

    return _send


@beartype
def build_worker_liveness_watchdog(
    *,
    targets: tuple[WorkerLivenessTarget, ...],
    stale_seconds: int,
    alert_cooldown_seconds: int,
    database: WorkerStatusDatabase | None,
    bot_token: str,
    alert_chat_id: int | None,
) -> WorkerLivenessWatchdog | None:
    if database is None:
        return None
    return WorkerLivenessWatchdog(
        targets=targets,
        stale_seconds=stale_seconds,
        alert_cooldown_seconds=alert_cooldown_seconds,
        database=database,
        send_alert=build_telegram_alert_sender(
            bot_token=bot_token,
            chat_id=alert_chat_id,
        ),
    )


__all__ = [
    "WorkerLivenessWatchdog",
    "WorkerStatusDatabase",
    "build_telegram_alert_sender",
    "build_worker_liveness_watchdog",
]
