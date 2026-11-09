from __future__ import annotations

from beartype import beartype

from src.application.master_data.companies import KitPlatform
from src.application.master_data.ports import CompanyStore


@beartype
class KitCompanyDirectory:
    def __init__(self, store: CompanyStore) -> None:
        self._store = store
        self._index: dict[tuple[KitPlatform, int], int] = {}
        self._rebuild_index()

    @beartype
    def _rebuild_index(self) -> None:
        self._index.clear()
        for company in self._store.list_all():
            for binding in company.platform_bindings:
                self._index[(binding.platform, binding.kit_company_id)] = company.company_id

    @beartype
    def resolve(self, platform: KitPlatform, kit_company_id: int) -> int | None:
        return self._index.get((platform, kit_company_id))

    @beartype
    def display_name(self, company_id: int) -> str:
        company = self._store.get(company_id)
        if company is None:
            return ""
        return company.name.strip()

    @beartype
    def display_names(self) -> dict[int, str]:
        return {
            company.company_id: company.name.strip()
            for company in self._store.list_all()
            if company.is_active
        }
