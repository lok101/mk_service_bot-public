from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data.companies import KitPlatform
from src.application.master_data.company_directory import KitCompanyDirectory


@beartype
@dataclass(frozen=True, slots=True)
class KitShopCompanyIdResolverAdapter:
    """KitCompanyDirectory → KitShopCompanyIdResolver (no IR→master_data import)."""

    directory: KitCompanyDirectory

    @beartype
    def resolve_mk_company_id(self, *, kit_company_id: int) -> int | None:
        return self.directory.resolve(KitPlatform.KIT_SHOP, kit_company_id)


__all__ = ["KitShopCompanyIdResolverAdapter"]
