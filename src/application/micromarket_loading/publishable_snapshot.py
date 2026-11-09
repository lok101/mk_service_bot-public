from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading import MicromarketDeviceStock


@beartype
@dataclass(frozen=True, slots=True)
class PublishableSnapshotLine:
    line: MicromarketPlanogramLine
    disabled: bool

    @property
    def product_code(self) -> str:
        return self.line.product_code

    @property
    def price_rub(self) -> Decimal:
        return self.line.price_rub

    @property
    def kit_group_id(self) -> int | None:
        return self.line.kit_group_id


@beartype
@dataclass(frozen=True, slots=True)
class PublishableSnapshot:
    lines: tuple[PublishableSnapshotLine, ...]
    skipped_names: tuple[str, ...]


@beartype
def build_publishable_snapshot(
    doc: MicromarketPlanogram,
    products: DomainProductStore | None,
    stock: MicromarketDeviceStock | None = None,
) -> PublishableSnapshot:
    lines: list[PublishableSnapshotLine] = []
    skipped: list[str] = []
    for line in doc.lines:
        if not line.active:
            continue
        if not line.domain_product_id:
            if line.product_code:
                skipped.append(line.product_code)
            continue
        product = products.get(line.domain_product_id) if products is not None else None
        if product is None:
            skipped.append("Товар не найден")
            continue
        resolved = replace(line, product_code=product.number)
        last_factual = stock.last_factual_qty(resolved.product_code) if stock is not None else None
        disabled = last_factual == Decimal("0")
        lines.append(PublishableSnapshotLine(line=resolved, disabled=disabled))
    return PublishableSnapshot(lines=tuple(lines), skipped_names=tuple(skipped))
