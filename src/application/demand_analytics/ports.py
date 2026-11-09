from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class ForecastPolicyNotRegistered:
    """Registry has no policy for the requested key. History was not read."""


@beartype
@dataclass(frozen=True, slots=True)
class SalesHistoryReadFailed:
    """The sales series could not be read."""


@beartype
@dataclass(frozen=True, slots=True)
class VirtualStockReadFailed:
    """The virtual stock series could not be read."""


@runtime_checkable
class SkuSalesHistoryPort(Protocol):
    """Quantities of one SKU on one machine inside a window."""

    @beartype
    def list_quantities(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
        sale_kind: str | None = None,
    ) -> tuple[tuple[datetime, Decimal], ...] | SalesHistoryReadFailed: ...


@runtime_checkable
class SkuVirtualStockHistoryPort(Protocol):
    """Virtual on-hand levels for one SKU as change points ``(at, qty_after)``."""

    @beartype
    def list_levels(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[tuple[datetime, Decimal], ...] | VirtualStockReadFailed: ...


@runtime_checkable
class DemandForecastPolicy(Protocol):
    """Named rule: facts plus an optional sales series → qty, unavailable, or read failure."""

    @beartype
    def forecast(
        self,
        *,
        machine_id: str,
        product_code: str,
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
        timezone: ZoneInfo,
        history: SkuSalesHistoryPort,
    ) -> Decimal | None | SalesHistoryReadFailed | VirtualStockReadFailed: ...
