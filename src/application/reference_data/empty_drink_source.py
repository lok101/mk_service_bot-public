from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype

from src.application.reference_data.ms_product_catalog import MsProductEntry


class EmptyProductCatalogDrinkSource:
    @beartype
    def list_drink_entries(self) -> Sequence[MsProductEntry]:
        return ()
