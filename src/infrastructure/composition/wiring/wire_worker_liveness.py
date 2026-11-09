from __future__ import annotations

from typing import Any, cast

from beartype import beartype
from pymongo import MongoClient

from src.config.settings import Settings
from src.config.worker_liveness import WORKER_LIVENESS_TARGETS_V1
from src.infrastructure.alerting.worker_liveness_watchdog import (
    WorkerLivenessWatchdog,
    WorkerStatusDatabase,
    build_worker_liveness_watchdog,
)
from src.infrastructure.mongodb.connection import MongoDatabaseSource


@beartype
def _resolve_status_database(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
) -> WorkerStatusDatabase | None:
    if mongo_client is None or not settings.mongodb.is_configured:
        return None
    database_name = settings.mongodb.database.strip()
    return cast(WorkerStatusDatabase, mongo_client[database_name])


@beartype
def wire_worker_liveness_watchdog(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
) -> WorkerLivenessWatchdog | None:
    database = _resolve_status_database(settings, mongo_client=mongo_client)
    return build_worker_liveness_watchdog(
        targets=WORKER_LIVENESS_TARGETS_V1,
        stale_seconds=settings.worker_liveness.stale_seconds,
        alert_cooldown_seconds=settings.worker_liveness.alert_cooldown_seconds,
        database=database,
        bot_token=settings.telegram.bot_token.get_secret_value(),
        alert_chat_id=settings.telegram.alert_chat_id,
    )


__all__ = ["wire_worker_liveness_watchdog"]
