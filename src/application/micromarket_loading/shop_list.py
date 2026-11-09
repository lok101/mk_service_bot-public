from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from beartype import beartype


class ShopListNotReady(Exception):
    """Raised when the Kit shop-list publisher has no working adapter."""


class ShopListPublishStatus(StrEnum):
    UNPUBLISHED = "unpublished"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def label_ru(self) -> str:
        match self:
            case ShopListPublishStatus.UNPUBLISHED:
                return "не опубликован"
            case ShopListPublishStatus.PUBLISHING:
                return "публикуется"
            case ShopListPublishStatus.PUBLISHED:
                return "опубликован"
            case ShopListPublishStatus.FAILED:
                return "ошибка"


@beartype
@dataclass(frozen=True, slots=True)
class ShopListLine:
    product_code: str
    price_rub: Decimal


@runtime_checkable
class MicromarketShopListPublisher(Protocol):
    @beartype
    def publish(self, *, machine_code: str, lines: Sequence[ShopListLine]) -> None: ...

    @beartype
    def status(self, *, machine_code: str) -> ShopListPublishStatus: ...


@beartype
@dataclass(frozen=True, slots=True)
class UnavailableMicromarketShopListPublisher:
    @beartype
    def publish(self, *, machine_code: str, lines: Sequence[ShopListLine]) -> None:
        del machine_code, lines
        raise ShopListNotReady

    @beartype
    def status(self, *, machine_code: str) -> ShopListPublishStatus:
        del machine_code
        return ShopListPublishStatus.UNPUBLISHED
