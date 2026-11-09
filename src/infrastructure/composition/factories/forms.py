from __future__ import annotations

from typing import Any

from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from beartype import beartype
from pymongo import MongoClient

from src.config.settings import Settings
from src.infrastructure.form_workflow import InMemoryFormWorkflowSessionStore
from src.infrastructure.mongodb.form_workflow_sessions import MongoFormWorkflowSessionStore
from src.interfaces.telegram.form_workflow.ports import FormWorkflowSessionStore


@beartype
def default_form_workflow_session_ttl_seconds(settings: Settings) -> int:
    mongo = settings.mongodb
    if mongo.form_workflow_session_ttl_seconds is not None:
        return mongo.form_workflow_session_ttl_seconds

    token_ttl_hours = settings.google_forms.form_token_ttl_hours
    return int(token_ttl_hours * 3600) + 86_400


@beartype
def build_fsm_storage(settings: Settings) -> BaseStorage:
    redis = settings.redis
    if redis.is_configured:
        uri = redis.uri
        assert uri is not None
        return RedisStorage.from_url(
            uri.strip(),
            key_builder=DefaultKeyBuilder(
                prefix=redis.fsm_key_prefix,
                with_destiny=True,
            ),
        )

    return MemoryStorage()


@beartype
def build_form_workflow_session_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> FormWorkflowSessionStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoFormWorkflowSessionStore.from_settings(
            mongo,
            ttl_seconds=default_form_workflow_session_ttl_seconds(settings),
            client=client,
        )
    return InMemoryFormWorkflowSessionStore()
