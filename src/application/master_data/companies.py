from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from beartype import beartype

if TYPE_CHECKING:
    from src.application.master_data.ports import (
        CompanyStore,
        MasterDataAuditStore,
        MasterDataCounterStore,
    )

_LOGGER = logging.getLogger(__name__)
_CREATE_AUDIT = "create_company"
_UPDATE_AUDIT = "update_company"


class KitPlatform(StrEnum):
    KIT_VENDING = "kit_vending"
    KIT_SHOP = "kit_shop"


class KitPlatformRole(StrEnum):
    SALES_POLL = "sales_poll"
    CATALOG = "catalog"
    DEFAULT = "default"


class DuplicatePlatformBinding(Exception):
    """Two companies claim the same (platform, kit_company_id)."""


class CompanyValidationError(Exception):
    """Blank name / invalid bindings / unknown company."""


@beartype
@dataclass(frozen=True, slots=True)
class KitPlatformBinding:
    platform: KitPlatform
    kit_company_id: int
    roles: tuple[KitPlatformRole, ...]


@beartype
@dataclass(frozen=True, slots=True)
class MasterCompany:
    company_id: int
    name: str
    is_active: bool
    platform_bindings: tuple[KitPlatformBinding, ...] = ()


_VENDING_ROLES = frozenset({KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG})
_SHOP_ROLES = frozenset({KitPlatformRole.DEFAULT})


@beartype
def validate_bindings_unique(companies: tuple[MasterCompany, ...]) -> None:
    seen: set[tuple[KitPlatform, int]] = set()
    for company in companies:
        for binding in company.platform_bindings:
            key = (binding.platform, binding.kit_company_id)
            if key in seen:
                raise DuplicatePlatformBinding(
                    f"duplicate binding {binding.platform.value}:{binding.kit_company_id}",
                )
            seen.add(key)


@beartype
def validate_bindings_for_write(
    bindings: tuple[KitPlatformBinding, ...],
    *,
    existing_companies: tuple[MasterCompany, ...],
    exclude_company_id: int | None = None,
) -> None:
    seen_keys: set[tuple[KitPlatform, int]] = set()
    existing_keys = {
        (b.platform, b.kit_company_id)
        for company in existing_companies
        if exclude_company_id is None or company.company_id != exclude_company_id
        for b in company.platform_bindings
    }
    for binding in bindings:
        if binding.kit_company_id <= 0:
            raise CompanyValidationError("kit_company_id must be > 0")
        key = (binding.platform, binding.kit_company_id)
        if key in seen_keys or key in existing_keys:
            raise CompanyValidationError(
                f"duplicate binding {binding.platform.value}:{binding.kit_company_id}",
            )
        seen_keys.add(key)
        roles = frozenset(binding.roles)
        if binding.platform is KitPlatform.KIT_VENDING:
            if not roles or not roles <= _VENDING_ROLES:
                raise CompanyValidationError(
                    "kit_vending roles must be non-empty subset of sales_poll|catalog",
                )
        elif binding.platform is KitPlatform.KIT_SHOP and roles != _SHOP_ROLES:
            raise CompanyValidationError("kit_shop roles must be exactly {default}")
    poll_count = sum(
        1
        for company in existing_companies
        if exclude_company_id is None or company.company_id != exclude_company_id
        for b in company.platform_bindings
        if b.platform is KitPlatform.KIT_VENDING and KitPlatformRole.SALES_POLL in b.roles
    )
    poll_count += sum(
        1
        for b in bindings
        if b.platform is KitPlatform.KIT_VENDING and KitPlatformRole.SALES_POLL in b.roles
    )
    if poll_count > 1:
        raise CompanyValidationError("only one kit_vending sales_poll binding allowed globally")


@dataclass(slots=True)
class CreateCompany:
    store: CompanyStore
    counters: MasterDataCounterStore
    audit: MasterDataAuditStore

    @beartype
    def execute(
        self,
        *,
        name: str,
        bindings: tuple[KitPlatformBinding, ...],
        actor_telegram_user_id: int,
        now: datetime,
    ) -> MasterCompany:
        # Lazy: models → ports → companies; avoid cycle at module import.
        from src.application.master_data.models import (
            MasterDataAuditRecord,
            allocate_company_id,
        )

        stripped = name.strip()
        if not stripped:
            raise CompanyValidationError("company name must not be blank")
        validate_bindings_for_write(bindings, existing_companies=self.store.list_all())
        company_id = allocate_company_id(self.counters, store=self.store)
        company = MasterCompany(
            company_id=company_id,
            name=stripped,
            is_active=True,
            platform_bindings=bindings,
        )
        try:
            self.store.upsert(company)
        except DuplicatePlatformBinding as exc:
            raise CompanyValidationError(str(exc)) from exc
        self.audit.append(
            MasterDataAuditRecord(
                at=now,
                actor_telegram_user_id=actor_telegram_user_id,
                command=_CREATE_AUDIT,
                payload={"company_id": str(company_id)},
            )
        )
        _LOGGER.info(
            "admin_company_create",
            extra={"company_id": company_id, "actor": actor_telegram_user_id},
        )
        return company


@dataclass(slots=True)
class UpdateCompany:
    store: CompanyStore
    audit: MasterDataAuditStore

    @beartype
    def execute(
        self,
        *,
        company_id: int,
        name: str,
        is_active: bool,
        bindings: tuple[KitPlatformBinding, ...],
        actor_telegram_user_id: int,
        now: datetime,
    ) -> MasterCompany:
        from src.application.master_data.models import MasterDataAuditRecord

        existing = self.store.get(company_id)
        if existing is None:
            raise CompanyValidationError(f"unknown company {company_id}")
        stripped = name.strip()
        if not stripped:
            raise CompanyValidationError("company name must not be blank")
        validate_bindings_for_write(
            bindings,
            existing_companies=self.store.list_all(),
            exclude_company_id=company_id,
        )
        company = MasterCompany(
            company_id=company_id,
            name=stripped,
            is_active=is_active,
            platform_bindings=bindings,
        )
        try:
            self.store.upsert(company)
        except DuplicatePlatformBinding as exc:
            raise CompanyValidationError(str(exc)) from exc
        self.audit.append(
            MasterDataAuditRecord(
                at=now,
                actor_telegram_user_id=actor_telegram_user_id,
                command=_UPDATE_AUDIT,
                payload={"company_id": str(company_id)},
            )
        )
        _LOGGER.info(
            "admin_company_update",
            extra={"company_id": company_id, "actor": actor_telegram_user_id},
        )
        return company
