from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data.companies import (
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)
from src.application.master_data.legacy_kitvending_accounts import LegacyKitVendingAccountRow
from src.application.master_data.models import COMPANY_COUNTER_KEY
from src.application.master_data.ports import CompanyStore, MasterDataCounterStore


@beartype
@dataclass(frozen=True, slots=True)
class ImportCompaniesResult:
    imported: int


@beartype
class ImportCompaniesFromKitVendingAccounts:
    def __init__(
        self,
        *,
        store: CompanyStore,
        counters: MasterDataCounterStore,
    ) -> None:
        self._store = store
        self._counters = counters

    @beartype
    def execute(self, rows: tuple[LegacyKitVendingAccountRow, ...]) -> ImportCompaniesResult:
        if not self._store.is_empty():
            return ImportCompaniesResult(imported=0)

        max_company_id = 0
        for row in rows:
            roles = (
                (KitPlatformRole.SALES_POLL, KitPlatformRole.CATALOG)
                if row.index == 0
                else (KitPlatformRole.CATALOG,)
            )
            company = MasterCompany(
                company_id=row.company_id,
                name=row.name or row.login,
                is_active=True,
                platform_bindings=(
                    KitPlatformBinding(
                        platform=KitPlatform.KIT_VENDING,
                        kit_company_id=row.company_id,
                        roles=roles,
                    ),
                ),
            )
            self._store.upsert(company)
            max_company_id = max(max_company_id, row.company_id)

        if rows:
            self._counters.set(COMPANY_COUNTER_KEY, max_company_id + 1)

        return ImportCompaniesResult(imported=len(rows))
