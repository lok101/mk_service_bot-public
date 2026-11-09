from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
)
from src.application.product_identity.ports import DomainProductStore


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingPreviewRow:
    product_code: str
    name: str
    stock_qty: Decimal
    target_qty: int
    price_rub: Decimal
    kit_group_id: int | None = None


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingPreview:
    machine_code: str
    rows: tuple[MicromarketLoadingPreviewRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class GetMicromarketLoadingPreview:
    planogram_store: MicromarketPlanogramStore
    stock_store: MicromarketDeviceStockStore
    catalog_names: Mapping[str, str]
    products: DomainProductStore | None = None

    @beartype
    def execute(self, machine_code: str) -> MicromarketLoadingPreview:
        planogram = self.planogram_store.get(machine_code)
        stock = self.stock_store.load(machine_code)
        if planogram is None:
            return MicromarketLoadingPreview(machine_code=machine_code, rows=())
        rows: list[MicromarketLoadingPreviewRow] = []
        for line in sorted(planogram.lines, key=lambda item: item.sort_order):
            if not line.active:
                continue
            if line.domain_product_id and self.products is not None:
                product = self.products.get(line.domain_product_id)
                if product is not None:
                    code = product.number
                    qty = stock.qty(code) if stock is not None else Decimal("0")
                    rows.append(
                        MicromarketLoadingPreviewRow(
                            product_code=code,
                            name=product.name,
                            stock_qty=qty,
                            target_qty=line.target_qty,
                            price_rub=line.price_rub,
                            kit_group_id=line.kit_group_id,
                        ),
                    )
                    continue
            qty = stock.qty(line.product_code) if stock is not None else Decimal("0")
            rows.append(
                MicromarketLoadingPreviewRow(
                    product_code=line.product_code,
                    name=self.catalog_names.get(line.product_code, ""),
                    stock_qty=qty,
                    target_qty=line.target_qty,
                    price_rub=line.price_rub,
                    kit_group_id=line.kit_group_id,
                ),
            )
        return MicromarketLoadingPreview(machine_code=machine_code, rows=tuple(rows))
