from __future__ import annotations

from typing import Any

import redis as redis_lib
from beartype import beartype
from pymongo import MongoClient

from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import build_mongo_client


@beartype
def build_redis_readiness_client(uri: str | None) -> redis_lib.Redis | None:
    if uri is None or not uri.strip():
        return None
    return redis_lib.from_url(uri.strip())


@beartype
def wire_persistence(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None | object = ...,
) -> PersistenceBundle:
    resolved_mongo = mongo_client if mongo_client is not ... else build_mongo_client(settings)
    redis_client = build_redis_readiness_client(settings.redis.uri)
    return PersistenceBundle(
        mongo_client=resolved_mongo,
        redis_client=redis_client,
    )
