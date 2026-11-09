from __future__ import annotations

from beartype import beartype

from src.application.master_data.company_directory import KitCompanyDirectory
from src.application.master_data.ports import CompanyStore


@beartype
def build_kit_company_directory(store: CompanyStore) -> KitCompanyDirectory:
    return KitCompanyDirectory(store)


@beartype
def build_company_display_names_map(store: CompanyStore) -> dict[int, str]:
    return build_kit_company_directory(store).display_names()
