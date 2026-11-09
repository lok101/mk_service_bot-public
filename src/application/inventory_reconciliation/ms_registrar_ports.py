from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class StockDocumentLine:
    product_code: str
    quantity: Decimal
    price_kop: int | None = None


@runtime_checkable
class DailySalesDemandRegistrar(Protocol):
    @beartype
    async def register_daily_sales_demand(
        self,
        *,
        warehouse_code: str,
        lines: list[StockDocumentLine],
        moment: datetime,
        sales_day: date,
        sales_channel_id: UUID,
        project_id: UUID,
    ) -> None: ...


class RegistrarPermanentError(Exception):
    """Permanent registrar failure (e.g. MS store not found); do not retry as-is."""


class RegistrarTransientError(Exception):
    """Retryable registrar failure (network/timeout/in-progress); use case continues."""
