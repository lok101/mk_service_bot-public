from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings


@runtime_checkable
class MongoDatabaseSource(Protocol):
    def __getitem__(self, name: str) -> Any: ...


@runtime_checkable
class MongoCollectionSource(Protocol):
    """Minimal superset of methods used by Mongo store collection Protocols."""

    def insert_one(self, document: dict[str, Any], **kwargs: Any) -> Any: ...

    def insert_many(self, documents: list[dict[str, Any]], **kwargs: Any) -> Any: ...

    def find_one(
        self,
        filter: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...

    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        **kwargs: Any,
    ) -> Any: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any: ...

    def update_many(
        self,
        filter: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any: ...

    def delete_one(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def delete_many(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def count_documents(self, filter: dict[str, Any], **kwargs: Any) -> int: ...

    def distinct(self, key: str, filter: dict[str, Any], **kwargs: Any) -> list[Any]: ...

    def find_one_and_delete(
        self,
        filter: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...

    def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...


@beartype
def create_mongo_client(settings: MongoSettings) -> MongoClient[dict[str, Any]]:
    if not settings.is_configured:
        raise ValueError("MongoSettings.uri must be set to create a MongoClient")
    uri = settings.uri
    assert uri is not None
    return MongoClient(uri.strip(), **settings.client_driver_kwargs())  # type: ignore[arg-type]


@beartype
def resolve_collection(
    settings: MongoSettings,
    *,
    collection_name: str,
    owner: str,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> MongoCollectionSource:
    """Resolve a Mongo collection from settings, reusing a shared client when given.

    Centralises the connection boilerplate shared by every Mongo store's
    ``from_settings``: configuration check, lazy client creation, database and
    collection lookup. ``owner`` is only used to build a clear error message.
    """
    if not settings.is_configured:
        raise ValueError(f"MongoSettings.uri must be set for {owner}")

    mongo_client = client or create_mongo_client(settings)
    database = mongo_client[settings.database.strip()]
    return cast(MongoCollectionSource, database[collection_name.strip()])
