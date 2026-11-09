from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from beartype import beartype

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class CatalogEnsureLine:
    vendor_code: str
    domain_name: str


@beartype
@dataclass(frozen=True, slots=True)
class CatalogCard:
    product_id: int
    vendor_code: str
    product_name: str
    is_deleted: bool


@beartype
@dataclass(frozen=True, slots=True)
class CatalogEnsureOk:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class CatalogEnsureError:
    message: str


@runtime_checkable
class CatalogEnsureWriter(Protocol):
    def add_product(self, *, vendor_code: str, product_name: str) -> int: ...

    def edit_product_name(self, *, product_id: int, product_name: str) -> None: ...


@beartype
def ensure_kit_shop_catalog_for_snapshot(
    *,
    lines: Sequence[CatalogEnsureLine],
    cards: Sequence[CatalogCard],
    writer: CatalogEnsureWriter,
) -> CatalogEnsureOk | CatalogEnsureError:
    working: list[CatalogCard] = list(cards)
    for line in lines:
        name = line.domain_name.strip()
        if not name:
            return CatalogEnsureError(f"Пустое имя домена для товара {line.vendor_code}")
        live = [
            card for card in working if card.vendor_code == line.vendor_code and not card.is_deleted
        ]
        if len(live) > 1:
            return CatalogEnsureError(f"Несколько живых карточек Kit для товара {line.vendor_code}")
        if len(live) == 1:
            card = live[0]
            if card.product_name.strip() == name:
                _logger.info(
                    "kit_shop_catalog_ensure",
                    extra={
                        "vendor_code": line.vendor_code,
                        "action": "noop",
                        "product_id": card.product_id,
                    },
                )
                continue
            writer.edit_product_name(product_id=card.product_id, product_name=name)
            working = [
                replace(item, product_name=name) if item.product_id == card.product_id else item
                for item in working
            ]
            _logger.info(
                "kit_shop_catalog_ensure",
                extra={
                    "vendor_code": line.vendor_code,
                    "action": "rename",
                    "product_id": card.product_id,
                },
            )
            continue
        new_id = writer.add_product(vendor_code=line.vendor_code, product_name=name)
        working.append(
            CatalogCard(
                product_id=new_id,
                vendor_code=line.vendor_code,
                product_name=name,
                is_deleted=False,
            )
        )
        _logger.info(
            "kit_shop_catalog_ensure",
            extra={
                "vendor_code": line.vendor_code,
                "action": "create",
                "product_id": new_id,
            },
        )
    return CatalogEnsureOk()
