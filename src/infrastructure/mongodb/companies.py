from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
    validate_bindings_unique,
)
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class CompaniesCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _roles_to_document(roles: tuple[KitPlatformRole, ...]) -> list[str]:
    return [role.value for role in roles]


@beartype
def _roles_from_document(raw: object) -> tuple[KitPlatformRole, ...]:
    if not isinstance(raw, list):
        raise ValueError("roles must be list")
    roles: list[KitPlatformRole] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("role must be str")
        roles.append(KitPlatformRole(item))
    return tuple(roles)


@beartype
def _binding_to_document(binding: KitPlatformBinding) -> dict[str, Any]:
    return {
        "platform": binding.platform.value,
        "kit_company_id": binding.kit_company_id,
        "roles": _roles_to_document(binding.roles),
    }


@beartype
def _binding_from_document(document: dict[str, Any]) -> KitPlatformBinding:
    platform_raw = document.get("platform")
    kit_company_id = document.get("kit_company_id")
    roles_raw = document.get("roles")
    if not isinstance(platform_raw, str):
        raise ValueError("platform must be str")
    if not isinstance(kit_company_id, int):
        raise ValueError("kit_company_id must be int")
    return KitPlatformBinding(
        platform=KitPlatform(platform_raw),
        kit_company_id=kit_company_id,
        roles=_roles_from_document(roles_raw),
    )


@beartype
def _company_to_document(company: MasterCompany) -> dict[str, Any]:
    return {
        "_id": company.company_id,
        "name": company.name,
        "is_active": company.is_active,
        "platform_bindings": [
            _binding_to_document(binding) for binding in company.platform_bindings
        ],
    }


@beartype
def _company_from_document(document: dict[str, Any]) -> MasterCompany:
    company_id = document.get("_id", document.get("company_id"))
    name = document.get("name")
    is_active = document.get("is_active")
    bindings_raw = document.get("platform_bindings")
    if not isinstance(company_id, int):
        raise ValueError("company_id must be int")
    if not isinstance(name, str):
        raise ValueError("name must be str")
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be bool")
    if not isinstance(bindings_raw, list):
        raise ValueError("platform_bindings must be list")
    bindings = tuple(
        _binding_from_document(binding) for binding in bindings_raw if isinstance(binding, dict)
    )
    return MasterCompany(
        company_id=company_id,
        name=name,
        is_active=is_active,
        platform_bindings=bindings,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoCompanyStore:
    collection: CompaniesCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        master_data: MasterDataSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoCompanyStore:
        collection = resolve_collection(
            mongo,
            collection_name=master_data.companies_collection,
            owner="MongoCompanyStore",
            client=client,
        )
        store = cls(collection=collection)
        store.ensure_indexes()
        return store

    @beartype
    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("is_active", 1)],
            name="company_is_active",
        )

    @beartype
    def get(self, company_id: int) -> MasterCompany | None:
        document = self.collection.find_one({"_id": company_id})
        if document is None:
            return None
        return _company_from_document(document)

    @beartype
    def upsert(self, company: MasterCompany) -> None:
        self.collection.replace_one(
            {"_id": company.company_id},
            _company_to_document(company),
            upsert=True,
        )
        validate_bindings_unique(self.list_all())

    @beartype
    def list_all(self) -> tuple[MasterCompany, ...]:
        items: list[MasterCompany] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_company_from_document(document))
        items.sort(key=lambda company: company.company_id)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.collection.count_documents({})) == 0
