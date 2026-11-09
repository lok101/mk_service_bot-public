from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.micromarket_loading.ports import SupplyOrderDemandForecastPort


@beartype
class AlwaysUnavailableSupplyOrderForecast(SupplyOrderDemandForecastPort):
    """Stub until ISS-372 / real model: every SKU is unavailable."""

    def forecast_qty(
        self,
        *,
        machine_id: str,
        product_code: str,
        category: Literal[2, 3],
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
    ) -> Decimal | None:
        return None
